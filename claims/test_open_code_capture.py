"""Capture and export codes absent from the demonstration reference subset.

These tests exercise syntactic acceptance, not code-set validity or provider
enrollment. All patients, providers, and claim amounts below are synthetic.
"""
import hashlib
import io
from datetime import date

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from edi import context, validators
from edi.models import TradingPartner, X12Document

from . import tests as capture_fixtures
from .capture_test_helpers import submit_new_claim
from .models import CaptureDraft, Claim, Icd10Code, NpiReference, ProcedureCode


class OpenCodeCaptureTests(TestCase):
    _capture_payload = capture_fixtures.ClaimCaptureWorkflowTests._capture_payload
    _service_line_payload = capture_fixtures.ClaimCaptureWorkflowTests._service_line_payload

    def setUp(self):
        self.staff = get_user_model().objects.create_user("open-code-operator", is_staff=True)
        self.client.force_login(self.staff)
        self.new_url = reverse("claims:capture_claim")

    def payload(self, **overrides):
        data = self._capture_payload()
        data.update({
            "patient_address_line_1": "100 Synthetic Patient Road",
            "payer_identifier": "SYNTHETIC-PAYER",
            "billing_provider_tax_id": "123456789",
            "billing_provider_address_line_1": "200 Synthetic Clinic Road",
            "billing_provider_zip_code": "27701-1234",
            "diagnoses-0-diagnosis_code": "E11.9",
            "diagnoses-0-description": "",
            "service_lines-0-procedure_code": "99214",
            "service_lines-0-service_line_from_date": "2026-11-06",
            "service_lines-0-service_line_to_date": "2026-11-06",
            "service_lines-0-modifier_codes": [],
        })
        data.update(overrides)
        return data

    def ticket(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return {key: response.context[key] for key in ("draft_token", "draft_version")}

    def capture(self, data=None):
        data = self.payload() if data is None else data
        response = submit_new_claim(self.client, data)
        self.assertEqual(response.status_code, 302, response.content.decode())
        return Claim.objects.get(claim_number=data["claim_number"])

    def reference_counts(self):
        return (Icd10Code.objects.count(), ProcedureCode.objects.count(), NpiReference.objects.count())

    def add_references(self, *, active=True):
        Icd10Code.objects.create(code="E11.9", short_description="Synthetic reference", is_active=active)
        ProcedureCode.objects.create(code="99214", code_system=ProcedureCode.SYSTEM_CPT,
                                     short_description="Synthetic reference", is_active=active)
        NpiReference.objects.create(npi="1234567893", provider_name="Synthetic reference",
                                    entity_type=NpiReference.ENTITY_ORGANIZATION, is_active=active)

    def assert_null_references(self, claim):
        self.assertFalse(claim.diagnoses.filter(icd10_reference__isnull=False).exists())
        self.assertFalse(claim.service_lines.filter(procedure_reference__isnull=False).exists())
        self.assertFalse(claim.claim_providers.filter(provider__npi_reference__isnull=False).exists())

    def generate(self, claim):
        call_command("seed_trading_partner", stdout=io.StringIO())
        partner = TradingPartner.objects.get(name="Demo MAC Test")
        response = self.client.post(reverse("workflow:submission", args=[claim.pk]), {"partner": partner.pk})
        self.assertEqual(response.status_code, 302, response.content.decode())
        return X12Document.objects.get()

    def test_blank_save_resume_then_submit_unknown_codes(self):
        response = self.client.post(self.new_url, {**self.ticket(self.new_url), "action": "save"})
        self.assertEqual(response.status_code, 302)
        draft = CaptureDraft.objects.get()
        resume_url = reverse("claims:resume_draft", args=[draft.pk])
        self.assertFalse(Claim.objects.exists())

        partial = {"patient_first_name": "Jamie", "diagnoses-TOTAL_FORMS": "1",
                   "diagnoses-INITIAL_FORMS": "0", "diagnoses-0-diagnosis_code": "E119",
                   "service_lines-TOTAL_FORMS": "1", "service_lines-INITIAL_FORMS": "0",
                   "service_lines-0-procedure_code": "0001U"}
        self.assertEqual(self.client.post(resume_url, {
            **partial, **self.ticket(resume_url), "action": "save",
        }).status_code, 302)
        resumed = self.client.get(resume_url)
        self.assertEqual(resumed.context["diagnosis_formset"].forms[0]["diagnosis_code"].value(), "E119")
        self.assertEqual(resumed.context["service_line_formset"].forms[0]["procedure_code"].value(), "0001U")
        self.assertFalse(Claim.objects.exists())
        completed = self.payload(**{"diagnoses-0-diagnosis_code": "E119", "service_lines-0-procedure_code": "0001U"})
        response = self.client.post(resume_url, {**completed, **self.ticket(resume_url), "action": "submit"})
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        claim = draft.claim
        self.assertEqual(claim.status, Claim.STATUS_READY_FOR_REVIEW)
        self.assertEqual(claim.validation_status, "reference_pending")
        self.assertEqual(claim.diagnoses.get().diagnosis_code, "E11.9")
        self.assertEqual(claim.service_lines.get().procedure_code, "0001U")
        self.assertEqual(self.reference_counts(), (0, 0, 0))
        self.assertFalse(X12Document.objects.exists())

    def test_cpt_hcpcs_and_alphanumeric_cpt_capture_without_local_reference(self):
        for code in ("99214", "J1100", "3074F", "0483T", "0001U"):
            with self.subTest(code=code):
                claim = self.capture(self.payload(**{"claim_number": f"SYNTHETIC-{code}",
                                                     "service_lines-0-procedure_code": code}))
                self.assertEqual(claim.service_lines.get().procedure_code, code)
                self.assertEqual(claim.validation_status, "reference_pending")
                self.assert_null_references(claim)
        self.assertEqual(self.reference_counts(), (0, 0, 0))

    def test_undotted_and_lowercase_diagnosis_codes_normalize_before_persistence(self):
        for supplied, expected in (("e119", "E11.9"), ("U071", "U07.1"), ("u07.1", "U07.1")):
            with self.subTest(supplied=supplied):
                claim = self.capture(self.payload(**{"claim_number": f"SYNTHETIC-{supplied}",
                                                     "diagnoses-0-diagnosis_code": supplied,
                                                     "service_lines-0-procedure_code": "j1100"}))
                self.assertEqual(claim.diagnoses.get().diagnosis_code, expected)
                self.assertEqual(claim.service_lines.get().procedure_code, "J1100")

    def test_checksum_valid_unlisted_billing_and_rendering_npis_are_preserved(self):
        claim = self.capture(self.payload(**{"billing_provider_npi": "1245319599",
                                            "rendering_provider_npi": "1111111112",
                                            "rendering_provider_first_name": "Synthetic",
                                            "rendering_provider_last_name": "Renderer"}))
        self.assertEqual(claim.claim_providers.get(provider_role="billing").provider.npi, "1245319599")
        self.assertEqual(claim.claim_providers.get(provider_role="rendering").provider.npi, "1111111112")
        self.assert_null_references(claim)
        self.assertEqual(claim.validation_status, "reference_pending")
        self.assertEqual(self.reference_counts(), (0, 0, 0))

    def test_active_reference_matches_keep_reference_links_and_validated_status(self):
        self.add_references()
        claim = self.capture(self.payload(**{"diagnoses-0-diagnosis_code": "e119"}))
        self.assertEqual(claim.validation_status, "reference_validated")
        self.assertEqual(claim.diagnoses.get().icd10_reference_id, "E11.9")
        self.assertEqual(claim.service_lines.get().procedure_reference_id, "99214")
        self.assertEqual(claim.claim_providers.get(provider_role="billing").provider.npi_reference_id, "1234567893")
        self.assertEqual(self.reference_counts(), (1, 1, 1))

    def test_one_unknown_code_marks_claim_pending_while_preserving_known_links(self):
        self.add_references()
        claim = self.capture(self.payload(**{"service_lines-0-procedure_code": "J1100"}))
        self.assertEqual(claim.validation_status, "reference_pending")
        self.assertEqual(claim.diagnoses.get().icd10_reference_id, "E11.9")
        self.assertIsNone(claim.service_lines.get().procedure_reference_id)
        self.assertEqual(self.reference_counts(), (1, 1, 1))

    def test_undotted_local_reference_matches_dotted_input_without_new_reference(self):
        self.add_references()
        Icd10Code.objects.all().delete()
        Icd10Code.objects.create(code="E119", short_description="Synthetic reference")
        claim = self.capture()
        self.assertEqual(claim.diagnoses.get().diagnosis_code, "E11.9")
        self.assertEqual(claim.diagnoses.get().icd10_reference_id, "E119")
        self.assertEqual(claim.validation_status, "reference_validated")
        self.assertEqual(self.reference_counts(), (1, 1, 1))

    def test_reference_outside_service_dates_is_pending_instead_of_claim_rejection(self):
        self.add_references()
        ProcedureCode.objects.filter(code="99214").update(effective_end_date=date(2020, 12, 31))
        claim = self.capture()
        self.assertEqual(claim.validation_status, "reference_pending")
        self.assertEqual(claim.service_lines.get().procedure_code, "99214")
        self.assertEqual(validators.validate(context.build(claim)), [])
        self.assertEqual(self.reference_counts(), (1, 1, 1))

    def test_inactive_reference_rows_do_not_block_or_become_reactivated(self):
        self.add_references(active=False)
        claim = self.capture()
        self.assertEqual(claim.validation_status, "reference_pending")
        self.assert_null_references(claim)
        self.assertEqual(self.reference_counts(), (1, 1, 1))
        self.assertFalse(Icd10Code.objects.get().is_active)
        self.assertFalse(ProcedureCode.objects.get().is_active)
        self.assertFalse(NpiReference.objects.get().is_active)

    def test_entered_description_is_saved_without_creating_reference_data(self):
        claim = self.capture(self.payload(**{"diagnoses-0-description": "User-entered description"}))
        self.assertEqual(claim.diagnoses.get().description, "User-entered description")
        self.assertEqual(self.reference_counts(), (0, 0, 0))

    def test_duplicate_dotted_and_undotted_diagnoses_are_rejected(self):
        response = submit_new_claim(self.client, self.payload(**{
            "diagnoses-TOTAL_FORMS": "2", "diagnoses-0-diagnosis_code": "E11.9",
            "diagnoses-1-diagnosis_code": "e119", "service_lines-0-diagnosis_refs": ["0", "1"],
        }))
        self.assertEqual(response.status_code, 200)
        self.assertIn("diagnosis_code", response.context["diagnosis_formset"].forms[1].errors)
        self.assertFalse(Claim.objects.exists())

    def test_malformed_diagnosis_and_x12_delimiters_are_rejected(self):
        for code in ("11.9", "E1", "E11..9", "E11.99999", "E11*9", "E11~9", "E11:9", "Ｅ11.9", "E１１.9"):
            with self.subTest(code=code):
                response = submit_new_claim(self.client, self.payload(**{"diagnoses-0-diagnosis_code": code}))
                self.assertEqual(response.status_code, 200)
                self.assertIn("diagnosis_code", response.context["diagnosis_formset"].forms[0].errors)
        self.assertFalse(Claim.objects.exists())
        self.assertEqual(self.reference_counts(), (0, 0, 0))

    def test_malformed_procedure_and_x12_delimiters_are_rejected(self):
        for code in ("9921", "992140", "XXXXX", "99*14", "99~14", "99:14", "９９２１４", "J１１00"):
            with self.subTest(code=code):
                response = submit_new_claim(self.client, self.payload(**{"service_lines-0-procedure_code": code}))
                self.assertEqual(response.status_code, 200)
                self.assertIn("procedure_code", response.context["service_line_formset"].forms[0].errors)
        self.assertFalse(Claim.objects.exists())

    def test_invalid_billing_npi_is_not_bypassed_by_missing_reference(self):
        for npi in ("1234567890", "123456789", "12345678933", "12345*7893", "１２３４５６７８９３"):
            with self.subTest(npi=npi):
                response = submit_new_claim(self.client, self.payload(**{"billing_provider_npi": npi}))
                self.assertEqual(response.status_code, 200)
                self.assertIn("billing_provider_npi", response.context["form"].errors)
        self.assertFalse(Claim.objects.exists())

    def test_invalid_rendering_npi_is_not_bypassed_by_missing_reference(self):
        response = submit_new_claim(self.client, self.payload(**{
            "rendering_provider_first_name": "Synthetic", "rendering_provider_last_name": "Renderer",
            "rendering_provider_npi": "1111111111",
        }))
        self.assertEqual(response.status_code, 200)
        self.assertIn("rendering_provider_npi", response.context["form"].errors)
        self.assertFalse(Claim.objects.exists())

    def test_empty_required_code_fields_still_block_submission(self):
        response = submit_new_claim(self.client, self.payload(**{
            "diagnoses-0-diagnosis_code": "", "service_lines-0-procedure_code": "",
        }))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["diagnosis_formset"].errors or response.context["diagnosis_formset"].non_form_errors())
        self.assertIn("procedure_code", response.context["service_line_formset"].forms[0].errors)
        self.assertFalse(Claim.objects.exists())

    def test_claim_page_reports_reference_review_for_unmatched_codes(self):
        claim = self.capture()
        page = self.client.get(reverse("claims:claim_detail", args=[claim.pk]))
        self.assertContains(page, "Reference review needed")
        self.assertNotContains(page, "Reference validated")

    def test_prepare_page_warns_without_treating_missing_subset_as_export_error(self):
        claim = self.capture()
        self.assertEqual(validators.validate(context.build(claim)), [])
        call_command("seed_trading_partner", stdout=io.StringIO())
        page = self.client.get(reverse("workflow:submission", args=[claim.pk]))
        self.assertContains(page, "Reference review needed")
        self.assertNotContains(page, "Resolve these items before generation")
        self.assertFalse(X12Document.objects.exists())

    def test_unknown_codes_generate_and_download_the_exact_archived_x12(self):
        claim = self.capture(self.payload(**{"diagnoses-0-diagnosis_code": "U071",
                                            "service_lines-0-procedure_code": "0483T"}))
        document = self.generate(claim)
        downloaded = self.client.get(reverse("workflow:download", args=[document.pk]))
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.content, document.content.encode("utf-8"))
        self.assertEqual(hashlib.sha256(downloaded.content).hexdigest(), document.sha256)
        self.assertIn("HI*ABK:U071~", document.content)
        self.assertIn("SV1*HC:0483T*150*UN*1", document.content)
        self.assertEqual(document.batch.status, "generated")
        self.assert_null_references(claim)
        self.assertEqual(self.reference_counts(), (0, 0, 0))
        claim.refresh_from_db()
        self.assertEqual(claim.validation_status, "reference_pending")

    def test_multiple_unlisted_diagnoses_keep_service_line_link_order_in_archive(self):
        data = self.payload(**{"diagnoses-TOTAL_FORMS": "2", "diagnoses-0-diagnosis_code": "E119",
                               "diagnoses-1-diagnosis_code": "U071", "service_lines-TOTAL_FORMS": "2",
                               "service_lines-0-diagnosis_refs": ["1", "0"],
                               "service_lines-0-modifier_codes": ["59", "25"]})
        data.update(self._service_line_payload(1, charge_amount="25.00"))
        data.update({"service_lines-1-procedure_code": "J1100", "service_lines-1-diagnosis_refs": ["0"],
                     "service_lines-1-modifier_codes": [], "service_lines-1-service_line_from_date": "2026-11-06",
                     "service_lines-1-service_line_to_date": "2026-11-06"})
        claim = self.capture(data)
        document = self.generate(claim)
        page = self.client.get(reverse("workflow:document", args=[document.pk]))
        summary = page.context["archive_summary"]["claims"][0]
        self.assertEqual([d["code"] for d in summary["diagnoses"]], ["E119", "U071"])
        self.assertEqual(summary["lines"][0]["pointers"], [2, 1])
        self.assertEqual([d["code"] for d in summary["lines"][0]["diagnoses"]], ["U071", "E119"])
        self.assertEqual(summary["lines"][0]["modifiers"], ["59", "25"])
        self.assertEqual(summary["lines"][1]["pointers"], [1])
        self.assertEqual(summary["lines"][1]["procedure"], "J1100")

    def test_missing_reference_does_not_bypass_existing_export_requirements(self):
        claim = self.capture(self.payload(**{"billing_provider_tax_id": ""}))
        call_command("seed_trading_partner", stdout=io.StringIO())
        partner = TradingPartner.objects.get(name="Demo MAC Test")
        page = self.client.post(reverse("workflow:submission", args=[claim.pk]), {"partner": partner.pk})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Billing provider EIN is required")
        self.assertFalse(X12Document.objects.exists())

    def test_archive_summary_remains_original_when_live_unlisted_code_is_edited(self):
        claim = self.capture()
        document = self.generate(claim)
        claim.diagnoses.update(diagnosis_code="U07.1")
        claim.service_lines.update(procedure_code="J1100")
        page = self.client.get(reverse("workflow:document", args=[document.pk]))
        summary = page.context["archive_summary"]["claims"][0]
        self.assertEqual(summary["diagnoses"][0]["code"], "E119")
        self.assertEqual(summary["lines"][0]["procedure"], "99214")
        downloaded = self.client.get(reverse("workflow:download", args=[document.pk]))
        self.assertEqual(downloaded.content, document.content.encode("utf-8"))
