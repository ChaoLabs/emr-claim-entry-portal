"""Browser-level regressions for provider capture, including cross-session ownership."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from edi.models import X12Document
from . import tests as capture_fixtures
from .models import CaptureDraft, Claim, Icd10Code, NpiReference, Patient, ProcedureCode


class DraftLifecycleTests(TestCase):
    _capture_payload = capture_fixtures.ClaimCaptureWorkflowTests._capture_payload
    _service_line_payload = capture_fixtures.ClaimCaptureWorkflowTests._service_line_payload

    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.provider = users.objects.create_user("draft-provider")
        cls.peer = users.objects.create_user("draft-peer")
        NpiReference.objects.create(npi="1234567893", provider_name="Test Clinic",
                                    entity_type=NpiReference.ENTITY_ORGANIZATION)
        for code in ("R51.9", "M54.50"):
            Icd10Code.objects.create(code=code, short_description="Synthetic reference")
        ProcedureCode.objects.create(code="99213", code_system=ProcedureCode.SYSTEM_CPT,
                                     short_description="Synthetic office visit")

    def setUp(self):
        self.client.force_login(self.provider)
        self.new = reverse("claims:capture_claim")
        self.home = reverse("claims:dashboard")

    def form_ticket(self, url, client=None):
        page = (client or self.client).get(url)
        self.assertEqual(page.status_code, 200)
        return {key: page.context[key] for key in ("draft_token", "draft_version")}

    def partial(self):
        return {
            "claim_number": "SYNTHETIC-WIP",
            "patient_first_name": "Example",
            "diagnoses-TOTAL_FORMS": "3", "diagnoses-INITIAL_FORMS": "0",
            "service_lines-TOTAL_FORMS": "2", "service_lines-INITIAL_FORMS": "0",
            "diagnoses-0-diagnosis_code": "R51.9", "diagnoses-1-DELETE": "on",
            "diagnoses-2-diagnosis_code": "M54.50",
            "service_lines-0-procedure_code": "99",
            "service_lines-0-diagnosis_refs": ["2", "0"],
            "service_lines-0-modifier_codes": ["GT", "2"],
            "service_lines-1-procedure_code": "99213",
        }

    def saved(self, data=None):
        result = self.client.post(self.new, {
            **(data if data is not None else self.partial()),
            **self.form_ticket(self.new), "action": "save",
        })
        self.assertEqual(result.status_code, 302)
        draft = CaptureDraft.objects.get(claim__isnull=True)
        return draft, reverse("claims:resume_draft", args=[draft.pk])

    def test_incomplete_form_survives_new_session_without_creating_billing_records(self):
        draft, resume = self.saved()
        self.assertFalse(Claim.objects.exists())
        self.assertFalse(Patient.objects.exists())
        self.assertFalse(X12Document.objects.exists())

        self.client.logout()
        fresh_browser = Client()
        fresh_browser.force_login(self.provider)
        self.assertContains(fresh_browser.get(self.home), resume)
        page = fresh_browser.get(resume)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["form"]["patient_first_name"].value(), "Example")
        self.assertFalse(page.context["form"]["insured_same_as_patient"].value())
        lines = page.context["service_line_formset"]
        diagnoses = page.context["diagnosis_formset"]
        self.assertEqual(len(lines.forms), 2)
        self.assertEqual(len(diagnoses.forms), 3)
        self.assertTrue(diagnoses.forms[1]["DELETE"].value())
        self.assertEqual(diagnoses.forms[2]["diagnosis_code"].value(), "M54.50")
        first_line = lines.forms[0]
        self.assertEqual(first_line["procedure_code"].value(), "99")
        self.assertEqual(first_line["diagnosis_refs"].value(), ["2", "0"])
        self.assertEqual(first_line["modifier_codes"].value(), ["GT", "2"])
        self.assertFalse(page.context["form"].errors)
        draft.refresh_from_db()
        self.assertIsNone(draft.claim_id)

    def test_only_explicit_valid_submit_advances_and_repeat_is_idempotent(self):
        draft, resume = self.saved()
        invalid = self.client.post(resume, {
            **self.partial(), **self.form_ticket(resume), "action": "submit",
        })
        self.assertEqual(invalid.status_code, 200)
        self.assertIn("patient_last_name", invalid.context["form"].errors)
        self.assertFalse(Claim.objects.exists())
        self.assertIsNone(CaptureDraft.objects.get(pk=draft.pk).claim_id)
        self.assertContains(self.client.get(self.home), resume)

        data = self._capture_payload()
        data.update({"diagnoses-TOTAL_FORMS": "2", "diagnoses-1-diagnosis_code": "M54.50",
                     "service_lines-0-diagnosis_refs": ["1", "0"],
                     "service_lines-0-modifier_codes": ["GT", "25"]})
        data.update(self.form_ticket(resume), action="submit")
        first = self.client.post(resume, data)
        replay = self.client.post(resume, data)
        claim = Claim.objects.get()
        target = reverse("claims:claim_detail", args=[claim.pk])
        self.assertRedirects(first, target)
        self.assertRedirects(replay, target)
        self.assertEqual(claim.status, Claim.STATUS_READY_FOR_REVIEW)
        self.assertEqual(claim.capture_draft.pk, draft.pk)
        line = claim.service_lines.get()
        self.assertEqual(line.diagnosis_pointers, [2, 1])
        self.assertEqual(line.modifier_codes, ["GT", "25"])
        self.assertNotContains(self.client.get(self.home), resume)
        self.assertFalse(X12Document.objects.exists())

    def test_anonymous_draft_is_available_in_its_own_session_only(self):
        self.client.logout()
        draft, resume = self.saved()
        self.assertContains(self.client.get(self.home), resume)
        self.assertEqual(self.client.get(resume).context["form"]["claim_number"].value(),
                         "SYNTHETIC-WIP")
        other_browser = Client()
        self.assertNotContains(other_browser.get(self.home), resume)
        self.assertEqual(other_browser.get(resume).status_code, 404)
        with_own_ticket = {
            **self.partial(), **self.form_ticket(self.new, other_browser), "action": "save",
        }
        self.assertIn(other_browser.post(resume, with_own_ticket).status_code, (400, 403, 404))
        self.assertFalse(Claim.objects.exists())

    def test_complete_data_saved_deliberately_remains_a_draft(self):
        draft, resume = self.saved(self._capture_payload())
        self.assertIsNone(draft.claim_id)
        self.assertFalse(Claim.objects.exists())
        self.assertContains(self.client.get(self.home), resume)

    def test_submit_without_first_saving_is_replay_safe_even_without_claim_number(self):
        data = {**self._capture_payload(), **self.form_ticket(self.new),
                "claim_number": "", "action": "submit"}
        first = self.client.post(self.new, data)
        repeat = self.client.post(self.new, data)
        target = reverse("claims:claim_detail", args=[Claim.objects.get().pk])
        self.assertRedirects(first, target)
        self.assertRedirects(repeat, target)
        self.assertEqual(Patient.objects.count(), 1)

    def test_stale_tab_cannot_overwrite_or_submit_a_newer_draft(self):
        draft, resume = self.saved()
        ticket = self.form_ticket(resume)
        newest = {**self.partial(), **ticket, "action": "save", "patient_first_name": "Latest"}
        self.assertEqual(self.client.post(resume, newest).status_code, 302)
        for intent in ("save", "submit"):
            with self.subTest(intent=intent):
                obsolete = {**self._capture_payload(), **ticket, "action": intent}
                self.assertEqual(self.client.post(resume, obsolete).status_code, 409)
        page = self.client.get(resume)
        self.assertEqual(page.context["form"]["patient_first_name"].value(), "Latest")
        self.assertFalse(Claim.objects.exists())
        self.assertIsNone(CaptureDraft.objects.get(pk=draft.pk).claim_id)

    def test_peer_cannot_list_open_or_promote_another_providers_draft(self):
        draft, resume = self.saved()
        ticket = self.form_ticket(resume)
        peer = Client()
        peer.force_login(self.peer)
        self.assertNotContains(peer.get(self.home), resume)
        self.assertEqual(peer.get(resume).status_code, 404)
        foreign_request = {**self._capture_payload(), **ticket, "action": "submit"}
        for url in (resume, self.new):
            with self.subTest(url=url):
                self.assertIn(peer.post(url, foreign_request).status_code, (400, 403, 404))
        # A real ticket belonging to the peer is no substitute for owning the URL's draft.
        forged_save = {**self.partial(), **self.form_ticket(self.new, peer), "action": "save",
                       "patient_first_name": "Changed by peer"}
        self.assertIn(peer.post(resume, forged_save).status_code, (400, 403, 404))
        self.assertEqual(self.client.get(resume).context["form"]["patient_first_name"].value(),
                         "Example")
        self.assertIsNone(CaptureDraft.objects.get(pk=draft.pk).claim_id)
        self.assertFalse(Claim.objects.exists())

        self.assertEqual(self.client.post(resume, foreign_request).status_code, 302)
        self.assertEqual(Claim.objects.count(), 1)

    def test_two_providers_can_save_the_same_claim_number_but_cannot_replace_a_submission(self):
        data = self._capture_payload()
        self.client.post(self.new, {**data, **self.form_ticket(self.new), "action": "submit"})
        original = Claim.objects.get()
        self.client.force_login(self.peer)
        data["patient_first_name"] = "Second"
        self.assertEqual(self.client.post(self.new, {
            **data, **self.form_ticket(self.new), "action": "save",
        }).status_code, 302)
        draft = CaptureDraft.objects.get(claim__isnull=True)
        resume = reverse("claims:resume_draft", args=[draft.pk])
        collision = self.client.post(resume, {
            **data, **self.form_ticket(resume), "action": "submit",
        })
        self.assertEqual(collision.status_code, 200)
        self.assertIn("claim_number", collision.context["form"].errors)
        self.assertEqual(Claim.objects.count(), 1)
        original.refresh_from_db()
        self.assertEqual(original.patient.first_name, "Jamie")
        # Omitting the optional manual number gives this submission a fresh number.
        result = self.client.post(resume, {
            **data, **self.form_ticket(resume), "action": "submit", "claim_number": "",
        })
        self.assertEqual(result.status_code, 302)
        draft.refresh_from_db()
        self.assertNotEqual(draft.claim.claim_number, original.claim_number)
        self.assertEqual(draft.claim.patient.first_name, "Second")

    def test_forged_or_missing_action_does_not_create_anything(self):
        data = {**self._capture_payload(), **self.form_ticket(self.new)}
        data.pop("action", None)
        self.assertEqual(self.client.post(self.new, data).status_code, 400)
        data["action"] = "publish"
        self.assertEqual(self.client.post(self.new, data).status_code, 400)
        self.assertFalse(Claim.objects.exists())
        self.assertFalse(CaptureDraft.objects.exists())
