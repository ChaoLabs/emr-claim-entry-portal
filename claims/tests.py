from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Claim,
    ClaimAuditEvent,
    ClaimCoverage,
    ClaimDiagnosis,
    ClaimProvider,
    Icd10Code,
    InsurancePolicy,
    InsuredParty,
    NpiReference,
    Patient,
    Payer,
    ProcedureCode,
    Provider,
    ReferenceDataUpdate,
    ServiceLine,
)


class ClaimCaptureWorkflowTests(TestCase):
    def setUp(self):
        completed_at = timezone.now()
        nppes_update = ReferenceDataUpdate.objects.create(
            dataset_name=ReferenceDataUpdate.DATASET_NPPES,
            source_name="NPPES development subset",
            source_version="test-2026-08",
            status=ReferenceDataUpdate.STATUS_COMPLETED,
            records_loaded=1,
            completed_at=completed_at,
            triggered_by="test",
        )
        icd10_update = ReferenceDataUpdate.objects.create(
            dataset_name=ReferenceDataUpdate.DATASET_ICD10,
            source_name="ICD-10-CM development subset",
            source_version="test-2026",
            status=ReferenceDataUpdate.STATUS_COMPLETED,
            records_loaded=2,
            completed_at=completed_at,
            triggered_by="test",
        )
        procedure_update = ReferenceDataUpdate.objects.create(
            dataset_name=ReferenceDataUpdate.DATASET_PROCEDURE,
            source_name="CPT / HCPCS development subset",
            source_version="test-2026",
            status=ReferenceDataUpdate.STATUS_COMPLETED,
            records_loaded=1,
            completed_at=completed_at,
            triggered_by="test",
        )
        self.npi_reference = NpiReference.objects.create(
            npi="1234567893",
            entity_type=NpiReference.ENTITY_ORGANIZATION,
            provider_name="EMRTS Demo Clinic",
            primary_taxonomy_code="207Q00000X",
            city="Durham",
            state="NC",
            is_active=True,
            source_update=nppes_update,
        )
        self.low_back_pain = Icd10Code.objects.create(
            code="M54.50",
            short_description="Low back pain, unspecified",
            is_active=True,
            source_update=icd10_update,
        )
        self.headache = Icd10Code.objects.create(
            code="R51.9",
            short_description="Headache, unspecified",
            is_active=True,
            source_update=icd10_update,
        )
        self.office_visit = ProcedureCode.objects.create(
            code="99213",
            code_system=ProcedureCode.SYSTEM_CPT,
            short_description="Office/outpatient visit, established patient",
            is_active=True,
            source_update=procedure_update,
        )
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
            address_line_1="300 Demo Payer Road",
            city="Durham",
            state="NC",
            zip_code="27701",
            zip_code_extension="1234",
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
            npi_reference=self.npi_reference,
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
            icd10_reference=self.low_back_pain,
            diagnosis_order=1,
            description="Low back pain, unspecified",
        )
        ServiceLine.objects.create(
            claim=self.claim,
            procedure_code="99213",
            procedure_reference=self.office_visit,
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
        self.assertContains(response, "Reference Data Readiness")
        self.assertContains(response, "NPPES / NPI")

    def test_claim_detail_loads_related_claim_data(self):
        response = self.client.get(reverse("claims:claim_detail", args=[self.claim.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Claim Detail")
        self.assertContains(response, "CLM-TEST-001")
        self.assertContains(response, "Coverage / Policy Information")
        self.assertContains(response, "Medicare")
        self.assertContains(response, "DEMO-MBI-0001")
        self.assertContains(response, "Demo Medicare Professional Coverage")
        self.assertContains(response, "300 Demo Payer Road")
        self.assertContains(response, "27701-1234")
        self.assertContains(response, "EMRTS Demo Clinic")
        self.assertContains(response, "M54.50")
        self.assertContains(response, "99213")
        self.assertContains(response, "Reference matched")

    def test_capture_claim_form_exposes_dynamic_service_line_controls(self):
        response = self.client.get(reverse("claims:capture_claim"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["service_line_formset"].total_form_count(), 1)
        self.assertContains(response, 'id="id_service_lines-TOTAL_FORMS"')
        self.assertContains(response, 'id="add-service-line"')
        self.assertContains(response, 'id="empty-service-line-form"')
        self.assertContains(response, "Add Service Line")

    def test_capture_claim_form_creates_claim_workflow_records(self):
        response = self.client.post(reverse("claims:capture_claim"), data=self._capture_payload())

        self.assertEqual(response.status_code, 302)

        claim = Claim.objects.get(claim_number="CLM-TEST-POST-001")
        self.assertEqual(claim.patient.last_name, "Carter")
        self.assertEqual(claim.status, Claim.STATUS_READY_FOR_REVIEW)
        self.assertEqual(claim.validation_status, "reference_validated")
        self.assertEqual(claim.total_charge_amount, Decimal("150.00"))

        self.assertEqual(claim.coverages.count(), 1)
        coverage = claim.coverages.select_related("insurance_policy__payer", "insurance_policy__insured_party").get()
        self.assertEqual(coverage.payer_sequence, ClaimCoverage.PAYER_SEQUENCE_PRIMARY)
        self.assertEqual(coverage.relationship_to_patient, "self")
        self.assertTrue(coverage.assignment_of_benefits)
        self.assertTrue(coverage.release_of_information)
        self.assertEqual(coverage.prior_authorization_number, "AUTH-123")
        payer = coverage.insurance_policy.payer
        self.assertEqual(payer.payer_name, "Medicare")
        self.assertEqual(payer.address_line_1, "300 Demo Payer Road")
        self.assertEqual(payer.address_line_2, "Suite 400")
        self.assertEqual(payer.city, "Durham")
        self.assertEqual(payer.state, "NC")
        self.assertEqual(payer.zip_code, "27701")
        self.assertEqual(payer.zip_code_extension, "1234")
        self.assertEqual(coverage.insurance_policy.member_id, "TEST-MBI-0002")
        self.assertEqual(coverage.insurance_policy.group_number, "TEST-GROUP")
        self.assertEqual(coverage.insurance_policy.plan_name, "Test Medicare Plan")

        self.assertEqual(claim.diagnoses.count(), 1)
        self.assertEqual(claim.diagnoses.get().icd10_reference, self.headache)
        self.assertEqual(claim.service_lines.count(), 1)
        service_line = claim.service_lines.get()
        self.assertEqual(service_line.procedure_reference, self.office_visit)
        self.assertEqual(service_line.modifier_1, "25")
        self.assertEqual(service_line.modifier_2, "GT")
        self.assertEqual(service_line.modifier_3, "59")
        self.assertEqual(service_line.modifier_4, "KX")
        self.assertEqual(claim.claim_providers.count(), 1)
        self.assertEqual(claim.claim_providers.get().provider.npi_reference, self.npi_reference)
        self.assertEqual(claim.audit_events.count(), 1)

        detail_response = self.client.get(reverse("claims:claim_detail", args=[claim.id]))
        self.assertContains(detail_response, "25")
        self.assertContains(detail_response, "GT")
        self.assertContains(detail_response, "59")
        self.assertContains(detail_response, "KX")
        self.assertContains(detail_response, "300 Demo Payer Road")
        self.assertContains(detail_response, "27701-1234")

    def test_capture_claim_accepts_more_than_six_service_lines_and_sums_charges(self):
        payload = self._capture_payload()
        payload["claim_number"] = "CLM-TEST-MULTI-001"
        payload["service_lines-TOTAL_FORMS"] = "7"

        for index in range(7):
            payload.update(
                self._service_line_payload(
                    index,
                    charge_amount=f"{index + 1}0.00",
                    modifier_1=f"M{index + 1}",
                )
            )

        response = self.client.post(reverse("claims:capture_claim"), data=payload)

        self.assertEqual(response.status_code, 302)
        claim = Claim.objects.get(claim_number="CLM-TEST-MULTI-001")
        self.assertEqual(claim.service_lines.count(), 7)
        self.assertEqual(claim.total_charge_amount, Decimal("280.00"))
        self.assertEqual(
            list(claim.service_lines.order_by("created_at").values_list("modifier_1", flat=True)),
            ["M1", "M2", "M3", "M4", "M5", "M6", "M7"],
        )

        detail_response = self.client.get(reverse("claims:claim_detail", args=[claim.id]))
        self.assertContains(detail_response, "99213", count=7)
        self.assertContains(detail_response, "M7")

    def test_capture_claim_ignores_a_removed_service_line(self):
        payload = self._capture_payload()
        payload["claim_number"] = "CLM-TEST-REMOVE-001"
        payload["service_lines-TOTAL_FORMS"] = "2"
        payload.update(self._service_line_payload(1, charge_amount="75.00", modifier_1="59"))
        payload["service_lines-0-DELETE"] = "on"

        response = self.client.post(reverse("claims:capture_claim"), data=payload)

        self.assertEqual(response.status_code, 302)
        claim = Claim.objects.get(claim_number="CLM-TEST-REMOVE-001")
        self.assertEqual(claim.service_lines.count(), 1)
        self.assertEqual(claim.total_charge_amount, Decimal("75.00"))
        self.assertEqual(claim.service_lines.get().modifier_1, "59")

    def test_capture_rejects_a_duplicate_claim_number_without_partial_records(self):
        existing_claim = Claim.objects.create(
            claim_number="CLM-TEST-POST-001",
            patient=Patient.objects.create(first_name="Existing", last_name="Patient"),
        )
        patient_count = Patient.objects.count()

        response = self.client.post(reverse("claims:capture_claim"), data=self._capture_payload())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A claim with this claim number already exists.")
        self.assertContains(response, "Jamie")
        self.assertEqual(Claim.objects.filter(claim_number="CLM-TEST-POST-001").count(), 1)
        self.assertEqual(Claim.objects.get(claim_number="CLM-TEST-POST-001"), existing_claim)
        self.assertEqual(Patient.objects.count(), patient_count)

    def test_capture_rejects_codes_not_in_active_reference_data(self):
        payload = self._capture_payload()
        payload["billing_provider_npi"] = "1234567890"
        payload["diagnosis_code_1"] = "ZZZ.99"
        payload["service_lines-0-procedure_code"] = "XXXXX"

        response = self.client.post(reverse("claims:capture_claim"), data=payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Review the highlighted claim fields")
        self.assertContains(response, "NPI was not found in the active reference data")
        self.assertContains(response, "Diagnosis code was not found")
        self.assertContains(response, "Procedure code was not found")
        self.assertFalse(Claim.objects.filter(claim_number="CLM-TEST-POST-001").exists())

    def test_capture_rejects_pointer_to_missing_diagnosis(self):
        payload = self._capture_payload()
        payload["service_lines-0-diagnosis_pointer_1"] = "2"

        response = self.client.post(reverse("claims:capture_claim"), data=payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Diagnosis pointer must reference an entered diagnosis code")
        self.assertFalse(Claim.objects.filter(claim_number="CLM-TEST-POST-001").exists())

    def test_capture_requires_valid_payer_mailing_address(self):
        payload = self._capture_payload()
        payload["payer_address_line_1"] = ""
        payload["payer_city"] = ""
        payload["payer_state"] = "N"
        payload["payer_zip_code"] = "2770A"
        payload["payer_zip_code_extension"] = "12A4"

        response = self.client.post(reverse("claims:capture_claim"), data=payload)

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form.errors["payer_address_line_1"], ["This field is required."])
        self.assertEqual(form.errors["payer_city"], ["This field is required."])
        self.assertEqual(form.errors["payer_state"], ["State must be a two-letter code."])
        self.assertEqual(
            form.errors["payer_zip_code"],
            ["Payer ZIP code must contain exactly 5 digits."],
        )
        self.assertEqual(
            form.errors["payer_zip_code_extension"],
            ["Payer ZIP+4 extension must contain exactly 4 digits."],
        )
        self.assertFalse(Claim.objects.filter(claim_number="CLM-TEST-POST-001").exists())

    def test_capture_accepts_payer_zip_without_optional_extension(self):
        payload = self._capture_payload()
        payload["claim_number"] = "CLM-TEST-ZIP5-001"
        payload["payer_zip_code_extension"] = ""

        response = self.client.post(reverse("claims:capture_claim"), data=payload)

        self.assertEqual(response.status_code, 302)
        claim = Claim.objects.get(claim_number="CLM-TEST-ZIP5-001")
        coverage = claim.coverages.select_related("insurance_policy__payer").get()
        payer = coverage.insurance_policy.payer
        self.assertEqual(payer.zip_code, "27701")
        self.assertEqual(payer.zip_code_extension, "")

    def test_sample_seed_is_idempotent_and_repairs_demo_coverage(self):
        call_command("seed_sample_claims", verbosity=0)
        call_command("seed_sample_claims", verbosity=0)

        claim = Claim.objects.get(claim_number="CLM-DEMO-001")
        coverage = claim.coverages.select_related("insurance_policy__payer").get(
            payer_sequence=ClaimCoverage.PAYER_SEQUENCE_PRIMARY
        )
        self.assertEqual(coverage.insurance_policy.payer.payer_name, "Medicare")
        self.assertEqual(coverage.insurance_policy.member_id, "DEMO-MBI-0001")
        self.assertEqual(claim.validation_status, "reference_validated")
        self.assertEqual(Claim.objects.filter(claim_number="CLM-DEMO-001").count(), 1)

    def _capture_payload(self):
        payload = {
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
                "payer_address_line_1": "300 Demo Payer Road",
                "payer_address_line_2": "Suite 400",
                "payer_city": "Durham",
                "payer_state": "nc",
                "payer_zip_code": "27701",
                "payer_zip_code_extension": "1234",
                "billing_provider_name": "EMRTS Test Clinic",
                "billing_provider_npi": "1234567893",
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
                "service_lines-TOTAL_FORMS": "1",
                "service_lines-INITIAL_FORMS": "0",
                "service_lines-MIN_NUM_FORMS": "1",
                "service_lines-MAX_NUM_FORMS": "1000",
        }
        payload.update(self._service_line_payload(0))
        return payload

    def _service_line_payload(self, index, charge_amount="150.00", modifier_1="25"):
        prefix = f"service_lines-{index}"
        return {
            f"{prefix}-service_line_from_date": "",
            f"{prefix}-service_line_to_date": "",
            f"{prefix}-place_of_service": "11",
            f"{prefix}-procedure_code": "99213",
            f"{prefix}-modifier_1": modifier_1,
            f"{prefix}-modifier_2": "GT",
            f"{prefix}-modifier_3": "59",
            f"{prefix}-modifier_4": "KX",
            f"{prefix}-diagnosis_pointer_1": "1",
            f"{prefix}-diagnosis_pointer_2": "",
            f"{prefix}-diagnosis_pointer_3": "",
            f"{prefix}-diagnosis_pointer_4": "",
            f"{prefix}-charge_amount": charge_amount,
            f"{prefix}-units": "1",
        }
