"""Capture real form submissions, then generate the exact persisted 837P file."""
import hashlib
import io

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from . import tests as capture_tests
from .capture_test_helpers import submit_new_claim
from .models import Claim
from edi import context, validators
from edi.models import TradingPartner, X12Document


class CaptureToExportTests(TestCase):
    _capture_payload = capture_tests.ClaimCaptureWorkflowTests._capture_payload
    _service_line_payload = capture_tests.ClaimCaptureWorkflowTests._service_line_payload

    def setUp(self):
        capture_tests.ClaimCaptureWorkflowTests.setUp(self)
        call_command("seed_trading_partner", stdout=io.StringIO())
        self.staff = get_user_model().objects.create_user("capture-operator", is_staff=True)
        self.partner = TradingPartner.objects.get(name="Demo MAC Test")

    def exportable_payload(self, *, dependent=False):
        data = self._capture_payload()
        data.update({
            "patient_address_line_1": "100 Synthetic Patient Road",
            "payer_identifier": "SYNTHETIC-PAYER",
            "billing_provider_tax_id": "123456789",
            "billing_provider_address_line_1": "200 Synthetic Clinic Road",
            "billing_provider_zip_code": "27701-1234",
            "service_lines-0-service_line_from_date": "2026-11-06",
            "service_lines-0-service_line_to_date": "2026-11-06",
        })
        if dependent:
            data.update({
                "insured_same_as_patient": "",
                "insured_first_name": "Taylor",
                "insured_last_name": "Carter",
                "insured_date_of_birth": "1960-02-01",
                "insured_sex": "female",
                "insured_address_line_1": "450 Subscriber Street",
                "insured_address_line_2": "Apt 8",
                "insured_city": "Chapel Hill",
                "insured_state": "nc",
                "insured_zip_code": "27514-9876",
                "relationship_to_patient": "child",
            })
        return data

    def capture_and_generate(self, data):
        response = submit_new_claim(self.client, data)
        self.assertEqual(response.status_code, 302)
        claim = Claim.objects.get(claim_number=data["claim_number"])
        self.assertEqual(validators.validate(context.build(claim)), [])
        self.client.force_login(self.staff)
        response = self.client.post(reverse("workflow:submission", args=[claim.pk]), {"partner": self.partner.pk})
        self.assertEqual(response.status_code, 302)
        document = X12Document.objects.get()
        downloaded = self.client.get(reverse("workflow:download", args=[document.pk]))
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.content, document.content.encode("utf-8"))
        self.assertEqual(hashlib.sha256(downloaded.content).hexdigest(), document.sha256)
        self.assertEqual(document.batch.status, "generated")
        response = self.client.get(reverse("workflow:document", args=[document.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["summary_error"])
        self.assertEqual(response.context["archive_summary"]["claims"][0]["claim_number"], claim.claim_number)
        return claim, document, response

    def test_dependent_capture_generates_subscriber_address_and_separate_patient_loop(self):
        claim, document, response = self.capture_and_generate(self.exportable_payload(dependent=True))
        subscriber = claim.coverages.get().insurance_policy.insured_party
        self.assertEqual(subscriber.address_line_1, "450 Subscriber Street")
        self.assertEqual(subscriber.address_line_2, "Apt 8")
        self.assertEqual(subscriber.city, "Chapel Hill")
        self.assertEqual(subscriber.state, "NC")
        self.assertEqual(subscriber.zip_code, "27514-9876")
        self.assertIn("N3*450 SUBSCRIBER STREET*APT 8~", document.content)
        self.assertIn("N4*CHAPEL HILL*NC*275149876~", document.content)
        self.assertIn("PAT*19~", document.content)
        summary = response.context["archive_summary"]["claims"][0]
        self.assertEqual(summary["subscriber_name"], "TAYLOR CARTER")
        self.assertEqual(summary["patient_name"], "JAMIE CARTER")
        self.assertEqual(summary["lines"][0]["diagnoses"][0]["code"], "R519")

    def test_self_capture_generates_without_duplicate_subscriber_fields(self):
        data = self.exportable_payload()
        data.update({"insured_address_line_1": "Ignored address", "insured_zip_code": "not-used"})
        claim, document, response = self.capture_and_generate(data)
        subscriber = claim.coverages.get().insurance_policy.insured_party
        self.assertEqual(subscriber.address_line_1, data["patient_address_line_1"])
        self.assertEqual(subscriber.zip_code, data["patient_zip_code"])
        self.assertNotIn("Ignored address", document.content)
        summary = response.context["archive_summary"]["claims"][0]
        self.assertEqual(summary["subscriber_name"], summary["patient_name"])

    def test_nonself_missing_address_and_dob_are_rejected_before_save(self):
        data = self.exportable_payload(dependent=True)
        fields = ("insured_date_of_birth", "insured_address_line_1", "insured_city", "insured_state", "insured_zip_code")
        for field in fields:
            data[field] = ""
        response = submit_new_claim(self.client, data)
        self.assertEqual(response.status_code, 200)
        for field in fields:
            self.assertIn(field, response.context["form"].errors)
        self.assertFalse(Claim.objects.filter(claim_number=data["claim_number"]).exists())

    def test_nonself_zip_validation_and_input_preservation(self):
        for postal in ("123", "123456", "１２３４５", "ABCDE", "27514-98765"):
            with self.subTest(postal=postal):
                data = self.exportable_payload(dependent=True)
                data["insured_zip_code"] = postal
                response = submit_new_claim(self.client, data)
                self.assertEqual(response.status_code, 200)
                self.assertIn("insured_zip_code", response.context["form"].errors)
                self.assertEqual(response.context["form"]["insured_address_line_1"].value(), "450 Subscriber Street")
                self.assertFalse(Claim.objects.filter(claim_number=data["claim_number"]).exists())
