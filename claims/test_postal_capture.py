"""Capture may be incomplete; export must validate the address actually sent."""
import io

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from claims.forms import CMS1500CaptureForm
from claims.models import Claim
from claims import tests as capture_tests
from edi.models import SubmissionBatch, TradingPartner, X12Document


class PostalCaptureTests(TestCase):
    _capture_payload = capture_tests.ClaimCaptureWorkflowTests._capture_payload
    _service_line_payload = capture_tests.ClaimCaptureWorkflowTests._service_line_payload

    def setUp(self):
        capture_tests.ClaimCaptureWorkflowTests.setUp(self)
        self.data = self._capture_payload()
        self.data.update({
            "patient_address_line_1": "100 Synthetic Patient Road",
            "payer_identifier": "SYNTHETIC-PAYER",
            "payer_zip_code_extension": "",
            "billing_provider_tax_id": "12-3456789",
            "billing_provider_address_line_1": "200 Synthetic Clinic Road",
            "billing_provider_zip_code": "27701",
            "service_lines-0-service_line_from_date": "2026-11-07",
            "service_lines-0-service_line_to_date": "2026-11-07",
        })
        self.staff = get_user_model().objects.create_user("postal-operator", is_staff=True)
        self.client.force_login(self.staff)
        call_command("seed_trading_partner", stdout=io.StringIO())
        self.partner = TradingPartner.objects.get(name="Demo MAC Test")

    def capture(self):
        response = self.client.post(reverse("claims:capture_claim"), self.data)
        self.assertEqual(response.status_code, 302)
        return Claim.objects.get(claim_number=self.data["claim_number"])

    def test_five_digit_billing_zip_can_be_saved_but_cannot_generate(self):
        claim = self.capture()
        url = reverse("workflow:submission", args=[claim.pk])
        response = self.client.post(url, {"partner": self.partner.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Billing provider ZIP+4 is required")
        self.assertFalse(SubmissionBatch.objects.exists())
        self.assertFalse(X12Document.objects.exists())
        self.assertEqual(claim.claim_providers.get(provider_role="billing").provider.zip_code, "27701")

    def test_optional_payer_extension_and_five_digit_patient_export_unchanged(self):
        self.data["billing_provider_zip_code"] = "27701-1234"
        claim = self.capture()
        response = self.client.post(reverse("workflow:submission", args=[claim.pk]), {"partner": self.partner.pk})
        self.assertEqual(response.status_code, 302)
        document = X12Document.objects.get()
        self.assertIn("N4*DURHAM*NC*277011234~", document.content)
        self.assertIn("N4*DURHAM*NC*27701~", document.content)
        self.assertIn("REF*EI*123456789~", document.content)
        self.assertNotIn("27701-1234", document.content)
        downloaded = self.client.get(reverse("workflow:download", args=[document.pk]))
        self.assertEqual(downloaded.content, document.content.encode())
        self.assertEqual(claim.patient.zip_code, self.data["patient_zip_code"])
        self.assertEqual(claim.coverages.get().insurance_policy.payer.zip_code_extension, "")

    def test_bad_entered_zip_or_ein_is_not_silently_sanitized(self):
        for field, value in (
            ("patient_zip_code", "NC27701"),
            ("billing_provider_zip_code", "27701A1234"),
            ("billing_provider_tax_id", "12A3456789"),
        ):
            with self.subTest(field=field):
                form = CMS1500CaptureForm({**self.data, field: value})
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)

    def test_unknown_optional_capture_values_remain_optional(self):
        form = CMS1500CaptureForm({**self.data, "billing_provider_tax_id": "", "billing_provider_zip_code": ""})
        self.assertTrue(form.is_valid(), form.errors)

    def test_missing_receiver_blocks_ui_and_post_without_creating_an_archive(self):
        self.partner.is_active = False
        self.partner.save(update_fields=["is_active"])
        self.data["billing_provider_zip_code"] = "27701-1234"
        claim = self.capture()
        url = reverse("workflow:submission", args=[claim.pk])
        page = self.client.get(url)
        self.assertContains(page, "Receiving partner required")
        self.assertContains(page, "Review required")
        self.assertNotContains(page, "Checks passed")
        self.assertFalse(page.context["has_partners"])
        self.assertContains(page, 'type="submit" disabled')
        self.assertEqual(self.client.post(url, {"partner": self.partner.pk}).status_code, 200)
        self.assertFalse(X12Document.objects.exists())

    def test_correction_link_requires_admin_permission(self):
        claim = self.capture()
        url = reverse("workflow:submission", args=[claim.pk])
        self.assertNotContains(self.client.get(url), "Review billing provider in Admin")
        self.staff.is_superuser = True
        self.staff.save(update_fields=["is_superuser"])
        response = self.client.get(url)
        provider = claim.claim_providers.get(provider_role="billing").provider
        self.assertContains(response, reverse("admin:claims_provider_change", args=[provider.pk]))
