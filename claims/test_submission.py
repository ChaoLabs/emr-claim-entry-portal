import hashlib
import io
from contextlib import redirect_stdout
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import DatabaseError
from django.test import Client, TestCase
from django.urls import reverse

from claims.models import Claim
from edi.models import ControlNumber, SubmissionBatch, TradingPartner, X12Document
from tools.make_test_claims import create as create_test_claims


class SubmissionWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with redirect_stdout(io.StringIO()):
            create_test_claims()
        call_command("seed_trading_partner", stdout=io.StringIO())
        cls.staff = get_user_model().objects.create_user("operator", is_staff=True)
        cls.claim = Claim.objects.get(claim_number="CLM-TEST-003")
        cls.partner = TradingPartner.objects.get(name="Demo MAC Test")

    def setUp(self):
        self.url = reverse("workflow:submission", args=[self.claim.pk])

    def generate(self):
        self.client.force_login(self.staff)
        return self.client.post(self.url, {"partner": self.partner.pk})

    def test_anonymous_and_nonstaff_cannot_generate_or_read_archive(self):
        self.assertEqual(self.client.post(self.url, {"partner": self.partner.pk}).status_code, 302)
        self.client.force_login(get_user_model().objects.create_user("viewer"))
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(SubmissionBatch.objects.count(), 0)
        self.generate()
        document = X12Document.objects.get()
        self.client.logout()
        for route in ("workflow:document", "workflow:download"):
            self.assertEqual(self.client.get(reverse(route, args=[document.pk])).status_code, 302)

    def test_generation_archives_exact_download_and_never_marks_sent(self):
        self.assertEqual(self.generate().status_code, 302)
        document = X12Document.objects.get()
        response = self.client.get(reverse("workflow:download", args=[document.pk]))
        self.assertEqual(response.content, document.content.encode("utf-8"))
        self.assertEqual(hashlib.sha256(response.content).hexdigest(), document.sha256)
        self.assertEqual(document.batch.status, "generated")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(self.claim.audit_events.filter(event_type="x12_generated").count(), 1)
        detail = self.client.get(reverse("workflow:document", args=[document.pk]))
        self.assertContains(detail, "Import returned 835")
        self.assertContains(detail, "not mark it as sent")

    def test_get_never_generates_and_post_requires_csrf(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        self.assertEqual(csrf_client.post(self.url, {"partner": self.partner.pk}).status_code, 403)
        self.assertFalse(SubmissionBatch.objects.exists())

    def test_invalid_claim_is_blocked_before_counters_or_archive(self):
        self.claim.service_lines.all().delete()
        response = self.generate()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "no service line")
        self.assertFalse(SubmissionBatch.objects.exists())
        self.assertFalse(ControlNumber.objects.exists())

    def test_archive_failure_rolls_back_batch_counter_and_audit(self):
        with patch("claims.workflow_views.ExportCommand.write_batch", side_effect=DatabaseError("failure")):
            with self.assertRaises(DatabaseError):
                self.generate()
        self.assertFalse(SubmissionBatch.objects.exists())
        self.assertFalse(ControlNumber.objects.exists())
        self.assertFalse(self.claim.audit_events.filter(event_type="x12_generated").exists())

    def test_changed_archive_fails_download_integrity_check(self):
        self.generate()
        document = X12Document.objects.get()
        X12Document.objects.filter(pk=document.pk).update(content="modified")
        response = self.client.get(reverse("workflow:download", args=[document.pk]))
        self.assertEqual(response.status_code, 409)

    def test_readable_summary_uses_archived_values_after_live_records_change(self):
        self.generate()
        document = X12Document.objects.get()
        self.claim.claim_number = "EDITED-LATER"
        self.claim.total_charge_amount = "999.99"
        self.claim.save()
        self.claim.diagnoses.update(diagnosis_code="Z99.9")
        self.claim.service_lines.update(procedure_code="99999", units=99, charge_amount="999.99")
        self.claim.patient.first_name = "ChangedPatient"
        self.claim.patient.save()
        billing = self.claim.claim_providers.get(provider_role="billing").provider
        billing.organization_name = "ChangedClinic"
        billing.save()
        self.partner.name = "ChangedPartner"
        self.partner.receiver_name = "ChangedReceiver"
        self.partner.usage_indicator = "P"
        self.partner.save()
        response = self.client.get(reverse("workflow:document", args=[document.pk]))
        self.assertEqual(response.status_code, 200)
        summary = response.context["archive_summary"]
        result = summary["claims"][0]
        self.assertEqual(result["claim_number"], "CLM-TEST-003")
        self.assertEqual(result["patient_name"], "ROSA DIAZ")
        self.assertEqual(result["total_charge"], "88.40")
        self.assertEqual(result["billing_name"], "SECOND DEMO CLINIC")
        self.assertEqual(result["diagnoses"][0]["code"], "M5450")
        line = result["lines"][0]
        self.assertEqual(line["procedure"], "99213")
        self.assertEqual(line["units"], "1")
        self.assertEqual(line["charge"], "88.40")
        self.assertEqual(line["diagnoses"], result["diagnoses"])
        self.assertEqual(summary["envelope"]["usage_label"], "Test")
        self.assertNotEqual(summary["envelope"]["receiver_name"], "ChangedReceiver")
        self.assertNotContains(response, "ChangedPatient")
        self.assertNotContains(response, "ChangedClinic")
        self.assertNotContains(response, "EDITED-LATER")

    def test_readable_table_maps_multiple_diagnoses_and_modifiers_in_wire_order(self):
        from claims.models import ClaimDiagnosis, ServiceLineDiagnosis, ServiceLineModifier
        line = self.claim.service_lines.get()
        second = ClaimDiagnosis.objects.create(claim=self.claim, diagnosis_code="R51.9", diagnosis_order=2)
        line.diagnosis_links.all().delete()
        ServiceLineDiagnosis.objects.create(service_line=line, diagnosis=second, position=1)
        ServiceLineDiagnosis.objects.create(service_line=line, diagnosis=self.claim.diagnoses.get(diagnosis_order=1), position=2)
        ServiceLineModifier.objects.create(service_line=line, code="59", position=1)
        ServiceLineModifier.objects.create(service_line=line, code="25", position=2)
        self.generate()
        document = X12Document.objects.get()
        response = self.client.get(reverse("workflow:document", args=[document.pk]))
        row = response.context["archive_summary"]["claims"][0]["lines"][0]
        self.assertEqual(row["pointers"], [2, 1])
        self.assertEqual([item["code"] for item in row["diagnoses"]], ["R519", "M5450"])
        self.assertEqual(row["modifiers"], ["59", "25"])
        self.assertEqual(row["service_from"], "2026-07-05")

    def test_download_preserves_archive_filename_and_admin_identity(self):
        from django.contrib.auth.models import Permission
        self.staff.user_permissions.add(Permission.objects.get(content_type__app_label="edi", codename="view_x12document"))
        self.generate()
        document = X12Document.objects.get()
        downloaded = self.client.get(reverse("workflow:download", args=[document.pk]))
        self.assertEqual(downloaded["Content-Disposition"], f'attachment; filename="{document.batch.file_name}"')
        admin_response = self.client.get(reverse("admin:edi_x12document_change", args=[document.pk]))
        self.assertEqual(admin_response.status_code, 200)
        self.assertEqual(admin_response.context["original"].content.encode("utf-8"), downloaded.content)
        self.assertEqual(admin_response.context["original"].sha256, hashlib.sha256(downloaded.content).hexdigest())
        self.assertEqual(X12Document.objects.count(), 1)
        self.assertEqual(SubmissionBatch.objects.get().status, "generated")

    def test_download_filename_excludes_paths_and_header_control_characters(self):
        self.generate()
        document = X12Document.objects.get()
        document.batch.file_name = "../../legacy\\legacy-file.edi\r\n"
        document.batch.save(update_fields=["file_name"])
        downloaded = self.client.get(reverse("workflow:download", args=[document.pk]))
        self.assertEqual(downloaded["Content-Disposition"], 'attachment; filename="legacy-file.edi"')
        self.assertEqual(downloaded.content, document.content.encode("utf-8"))

    def test_legacy_unreadable_summary_keeps_exact_raw_file_available(self):
        self.generate()
        document = X12Document.objects.get()
        # Model archive accepts historical text; readable tables must fail
        # honestly rather than reconstructing it from today's claim.
        legacy = "ST*837*LEGACY~\n"
        X12Document.objects.filter(pk=document.pk).update(content=legacy,
            byte_count=len(legacy), sha256=hashlib.sha256(legacy.encode()).hexdigest())
        response = self.client.get(reverse("workflow:document", args=[document.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["archive_summary"])
        self.assertTrue(response.context["summary_error"])
        self.assertEqual(self.client.get(reverse("workflow:download", args=[document.pk])).content, legacy.encode())

    def test_archive_index_requires_staff_and_lists_persisted_documents(self):
        url = reverse("workflow:archive")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.generate()
        document = X12Document.objects.get()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["documents"]), [document])
        self.assertContains(response, document.batch.file_name)
        self.assertIn("no-store", response["Cache-Control"])
