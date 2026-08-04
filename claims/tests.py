from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from .models import (
    Claim,
    ClaimAuditEvent,
    ClaimCoverage,
    ClaimDiagnosis,
    ClaimProvider,
    InsurancePolicy,
    InsuredParty,
    Patient,
    Payer,
    Provider,
    ServiceLine,
)


class ClaimCaptureWorkflowTests(TestCase):
    def setUp(self):
        self.patient = Patient.objects.create(
            first_name="Alex",
            last_name="Morgan",
            date_of_birth=date(1985, 4, 12),
            sex="unknown",
            city="Raleigh",
            state="NC",
            zip_code="27601",
        )
        self.insured = InsuredParty.objects.create(
            first_name="Alex",
            last_name="Morgan",
            date_of_birth=date(1985, 4, 12),
            sex="unknown",
        )
        self.payer = Payer.objects.create(
            payer_name="Medicare",
            payer_type=Payer.PAYER_TYPE_MEDICARE,
            payer_identifier="CMS-DEMO",
        )
        self.insurance_policy = InsurancePolicy.objects.create(
            insured_party=self.insured,
            payer=self.payer,
            member_id="DEMO-MBI-0001",
            group_number="DEMO-GROUP",
            plan_name="Demo Medicare Professional Coverage",
            policy_type=InsurancePolicy.POLICY_TYPE_MEDICARE,
        )
        self.provider = Provider.objects.create(
            organization_name="EMRTS Demo Clinic",
            npi="1234567893",
            taxonomy_code="207Q00000X",
            city="Durham",
            state="NC",
        )
        self.claim = Claim.objects.create(
            claim_number="CLM-TEST-001",
            patient=self.patient,
            status=Claim.STATUS_READY_FOR_REVIEW,
            validation_status="capture_complete",
            total_charge_amount=Decimal("125.00"),
        )
        ClaimCoverage.objects.create(
            claim=self.claim,
            insurance_policy=self.insurance_policy,
            payer_sequence=ClaimCoverage.PAYER_SEQUENCE_PRIMARY,
            relationship_to_patient="self",
            assignment_of_benefits=True,
            release_of_information=True,
        )
        ClaimProvider.objects.create(
            claim=self.claim,
            provider=self.provider,
            provider_role=ClaimProvider.ROLE_BILLING,
        )
        ClaimDiagnosis.objects.create(
            claim=self.claim,
            diagnosis_code="M54.50",
            diagnosis_order=1,
            description="Low back pain, unspecified",
        )
        ServiceLine.objects.create(
            claim=self.claim,
            procedure_code="99213",
            place_of_service="11",
            diagnosis_pointer_1=1,
            charge_amount=Decimal("125.00"),
            units=1,
        )
        ClaimAuditEvent.objects.create(
            claim=self.claim,
            event_type="test_created",
            event_description="Test claim created.",
            changed_by="test",
        )

    def test_dashboard_loads_recent_claim(self):
        response = self.client.get(reverse("claims:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Claim Entry Dashboard")
        self.assertContains(response, "CLM-TEST-001")
        self.assertContains(response, "Morgan, Alex")
        self.assertContains(response, "Medicare")

    def test_claim_detail_loads_related_claim_data(self):
        response = self.client.get(reverse("claims:claim_detail", args=[self.claim.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Claim Detail")
        self.assertContains(response, "CLM-TEST-001")
        self.assertContains(response, "Coverage / Policy Information")
        self.assertContains(response, "Medicare")
        self.assertContains(response, "DEMO-MBI-0001")
        self.assertContains(response, "Demo Medicare Professional Coverage")
        self.assertContains(response, "EMRTS Demo Clinic")
        self.assertContains(response, "M54.50")
        self.assertContains(response, "99213")

    def test_capture_claim_form_creates_claim_workflow_records(self):
        response = self.client.post(
            reverse("claims:capture_claim"),
            data={
                "patient_first_name": "Jamie",
                "patient_middle_name": "",
                "patient_last_name": "Carter",
                "patient_date_of_birth": "1990-01-15",
                "patient_sex": "unknown",
                "patient_address_line_1": "",
                "patient_address_line_2": "",
                "patient_city": "Durham",
                "patient_state": "NC",
                "patient_zip_code": "27701",
                "patient_phone_number": "",
                "insured_same_as_patient": "on",
                "insured_first_name": "",
                "insured_middle_name": "",
                "insured_last_name": "",
                "insured_date_of_birth": "",
                "insured_sex": "",
                "relationship_to_patient": "",
                "insured_id_number": "TEST-MBI-0002",
                "group_number": "TEST-GROUP",
                "plan_name": "Test Medicare Plan",
                "policy_type": "medicare",
                "payer_sequence": "primary",
                "assignment_of_benefits": "on",
                "release_of_information": "on",
                "prior_authorization_number": "AUTH-123",
                "payer_name": "Medicare",
                "payer_type": "medicare",
                "payer_identifier": "",
                "medicare_administrative_contractor": "",
                "billing_provider_name": "EMRTS Test Clinic",
                "billing_provider_npi": "1234567890",
                "billing_provider_taxonomy_code": "207Q00000X",
                "billing_provider_tax_id": "",
                "billing_provider_address_line_1": "",
                "billing_provider_city": "Durham",
                "billing_provider_state": "NC",
                "billing_provider_zip_code": "27701",
                "rendering_provider_first_name": "",
                "rendering_provider_last_name": "",
                "rendering_provider_npi": "",
                "claim_number": "CLM-TEST-POST-001",
                "service_start_date": "",
                "service_end_date": "",
                "diagnosis_code_1": "R51.9",
                "diagnosis_description_1": "Headache, unspecified",
                "diagnosis_code_2": "",
                "diagnosis_description_2": "",
                "diagnosis_code_3": "",
                "diagnosis_description_3": "",
                "diagnosis_code_4": "",
                "diagnosis_description_4": "",
                "service_line_from_date": "",
                "service_line_to_date": "",
                "place_of_service": "11",
                "procedure_code": "99213",
                "modifier_1": "",
                "modifier_2": "",
                "modifier_3": "",
                "modifier_4": "",
                "diagnosis_pointer_1": "1",
                "diagnosis_pointer_2": "",
                "diagnosis_pointer_3": "",
                "diagnosis_pointer_4": "",
                "charge_amount": "150.00",
                "units": "1",
            },
        )

        self.assertEqual(response.status_code, 302)

        claim = Claim.objects.get(claim_number="CLM-TEST-POST-001")
        self.assertEqual(claim.patient.last_name, "Carter")
        self.assertEqual(claim.status, Claim.STATUS_READY_FOR_REVIEW)
        self.assertEqual(claim.total_charge_amount, Decimal("150.00"))

        self.assertEqual(claim.coverages.count(), 1)
        coverage = claim.coverages.select_related("insurance_policy__payer", "insurance_policy__insured_party").get()
        self.assertEqual(coverage.payer_sequence, ClaimCoverage.PAYER_SEQUENCE_PRIMARY)
        self.assertEqual(coverage.relationship_to_patient, "self")
        self.assertTrue(coverage.assignment_of_benefits)
        self.assertTrue(coverage.release_of_information)
        self.assertEqual(coverage.prior_authorization_number, "AUTH-123")
        self.assertEqual(coverage.insurance_policy.payer.payer_name, "Medicare")
        self.assertEqual(coverage.insurance_policy.member_id, "TEST-MBI-0002")
        self.assertEqual(coverage.insurance_policy.group_number, "TEST-GROUP")
        self.assertEqual(coverage.insurance_policy.plan_name, "Test Medicare Plan")

        self.assertEqual(claim.diagnoses.count(), 1)
        self.assertEqual(claim.service_lines.count(), 1)
        self.assertEqual(claim.claim_providers.count(), 1)
        self.assertEqual(claim.audit_events.count(), 1)
