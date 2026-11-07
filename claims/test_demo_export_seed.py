"""The published development sample must export without weakening real-data checks."""
import io

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from claims.management.commands.seed_sample_claims import Command
from claims.models import Claim, ClaimCoverage, ClaimProvider, Provider, ServiceLine
from edi import context, validators
from edi.models import ControlNumber, TradingPartner, X12Document


class DemoExportSeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_sample_claims", stdout=io.StringIO())
        cls.claim = Claim.objects.get(claim_number="CLM-DEMO-001")
        cls.provider = cls.claim.claim_providers.get(provider_role="billing").provider
        cls.partner = TradingPartner.objects.get(name="Demo MAC Test")
        cls.staff = get_user_model().objects.create_user("demo-operator", is_staff=True)

    def seed(self):
        output = io.StringIO()
        call_command("seed_sample_claims", stdout=output)
        return output.getvalue()

    def legacy_provider(self):
        Provider.objects.filter(pk=self.provider.pk).update(zip_code="27701", tax_id="DEMO-TAX-ID")
        self.provider.refresh_from_db()

    def generate(self):
        self.client.force_login(self.staff)
        return self.client.post(reverse("workflow:submission", args=[self.claim.pk]),
                                {"partner": self.partner.pk})

    def test_fresh_seed_is_exportable_with_five_digit_member_zip_and_test_receiver(self):
        self.assertEqual(validators.validate(context.build(self.claim)), [])
        self.assertEqual(self.claim.patient.zip_code, "27601")
        self.assertEqual(self.claim.coverages.get().insurance_policy.insured_party.zip_code, "27601")
        self.assertEqual(self.provider.zip_code, Command.DEMO_BILLING_ZIP)
        self.assertEqual(self.provider.tax_id, Command.DEMO_BILLING_EIN)
        self.assertEqual(self.partner.usage_indicator, "T")
        self.assertTrue(self.partner.is_active)
        self.assertEqual(self.generate().status_code, 302)
        document = X12Document.objects.get()
        self.assertIn("N4*DURHAM*NC*277011234~", document.content)
        self.assertIn("REF*EI*123456789~", document.content)
        self.assertIn("N4*RALEIGH*NC*27601~", document.content)
        response = self.client.get(reverse("workflow:download", args=[document.pk]))
        self.assertEqual(response.content, document.content.encode())
        self.assertEqual(document.batch.status, "generated")

    def test_legacy_fixture_repair_is_idempotent_and_audited_once(self):
        self.legacy_provider()
        self.seed()
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.zip_code, Command.DEMO_BILLING_ZIP)
        self.assertEqual(self.provider.tax_id, Command.DEMO_BILLING_EIN)
        self.assertEqual(validators.validate(context.build(self.claim)), [])
        self.seed()
        self.assertEqual(self.claim.audit_events.filter(event_type="sample_export_prepared").count(), 1)
        self.assertEqual(TradingPartner.objects.count(), 1)
        self.assertEqual(Claim.objects.count(), 1)
        self.assertEqual(self.generate().status_code, 302)

    def test_edited_provider_is_preserved_even_when_other_legacy_field_remains(self):
        for field, value in (("zip_code", "27701-9876"), ("tax_id", "987654321"),
                             ("address_line_1", "Operator address"),
                             ("organization_name", "Operator clinic")):
            with self.subTest(field=field):
                self.legacy_provider()
                original = getattr(self.provider, field)
                Provider.objects.filter(pk=self.provider.pk).update(**{field: value})
                before = Provider.objects.filter(pk=self.provider.pk).values().get()
                self.seed()
                self.assertEqual(Provider.objects.filter(pk=self.provider.pk).values().get(), before)
                Provider.objects.filter(pk=self.provider.pk).update(**{field: original})
        self.assertFalse(self.claim.audit_events.filter(event_type="sample_export_prepared").exists())

    def test_shared_provider_is_not_changed_for_another_claim(self):
        self.legacy_provider()
        other = Claim.objects.create(claim_number="UNRELATED-001", patient=self.claim.patient)
        ClaimProvider.objects.create(claim=other, provider=self.provider, provider_role="billing")
        self.seed()
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.zip_code, "27701")
        self.assertEqual(self.provider.tax_id, "DEMO-TAX-ID")
        self.assertFalse(self.claim.audit_events.filter(event_type="sample_export_prepared").exists())

    def test_provider_used_on_another_service_line_is_not_changed(self):
        self.legacy_provider()
        other = Claim.objects.create(claim_number="UNRELATED-002", patient=self.claim.patient)
        ServiceLine.objects.create(claim=other, procedure_code="99213", rendering_provider=self.provider)
        self.seed()
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.zip_code, "27701")
        self.assertEqual(self.provider.tax_id, "DEMO-TAX-ID")

    def test_matching_claim_number_without_seed_provenance_is_not_modified(self):
        self.legacy_provider()
        self.claim.audit_events.all().delete()
        before = Provider.objects.filter(pk=self.provider.pk).values().get()
        output = self.seed()
        self.assertIn("no matching sample provenance", output)
        self.assertEqual(Provider.objects.filter(pk=self.provider.pk).values().get(), before)
        self.assertFalse(self.claim.audit_events.exists())

    def test_reseed_preserves_edited_payer_policy_and_coverage(self):
        coverage = self.claim.coverages.select_related("insurance_policy__payer").get()
        payer = coverage.insurance_policy.payer
        payer.address_line_1 = "Edited payer address"
        payer.zip_code_extension = ""
        payer.save()
        coverage.relationship_to_patient = "child"
        coverage.assignment_of_benefits = False
        coverage.save()
        self.seed()
        payer.refresh_from_db()
        coverage.refresh_from_db()
        self.assertEqual(payer.address_line_1, "Edited payer address")
        self.assertEqual(payer.zip_code_extension, "")
        self.assertEqual(coverage.relationship_to_patient, "child")
        self.assertFalse(coverage.assignment_of_benefits)

    def test_receiver_edits_disabled_state_and_control_numbers_survive_reseed(self):
        self.partner.usage_indicator = "P"
        self.partner.is_active = False
        self.partner.receiver_id = "OPERATOR-SET"
        self.partner.save()
        ControlNumber.objects.create(trading_partner=self.partner, level="interchange", current_value=77)
        self.seed()
        call_command("seed_trading_partner", stdout=io.StringIO())
        self.partner.refresh_from_db()
        self.assertEqual(self.partner.usage_indicator, "P")
        self.assertFalse(self.partner.is_active)
        self.assertEqual(self.partner.receiver_id, "OPERATOR-SET")
        self.assertEqual(ControlNumber.objects.get().current_value, 77)
        self.assertEqual(TradingPartner.objects.count(), 1)

    def test_fixture_repair_never_changes_existing_archive(self):
        self.assertEqual(self.generate().status_code, 302)
        document = X12Document.objects.get()
        before = (document.content, document.sha256, document.byte_count, document.batch_id)
        self.legacy_provider()
        self.seed()
        document.refresh_from_db()
        self.assertEqual((document.content, document.sha256, document.byte_count, document.batch_id), before)
        self.assertEqual(X12Document.objects.count(), 1)
        self.assertEqual(self.client.get(reverse("workflow:download", args=[document.pk])).content,
                         before[0].encode())
