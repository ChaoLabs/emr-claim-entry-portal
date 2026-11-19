from datetime import date

from django.test import TestCase

from .models import Claim, ClaimDiagnosis, Icd10Code, Patient, ProcedureCode, ServiceLine, ServiceLineDiagnosis
from .reference_checks import find_diagnosis_reference, reference_report


class LocalReferenceReportTests(TestCase):
    def setUp(self):
        self.claim = Claim.objects.create(
            patient=Patient.objects.create(first_name="Synthetic", last_name="Reference"),
        )

    def add_diagnosis(self, code="E11.9"):
        return ClaimDiagnosis.objects.create(claim=self.claim, diagnosis_code=code, diagnosis_order=1)

    def reference(self, **kwargs):
        return Icd10Code.objects.create(code="E119", short_description="Synthetic reference", **kwargs)

    def test_dotted_input_finds_existing_compact_reference(self):
        self.add_diagnosis()
        reference = self.reference()
        self.assertEqual(find_diagnosis_reference("e11.9"), reference)
        self.assertEqual(reference_report(self.claim)["validation_status"], "reference_validated")

    def test_malformed_reference_is_ignored_without_mutation(self):
        self.add_diagnosis()
        malformed = Icd10Code.objects.create(code="E1.19", short_description="Malformed import")
        report = reference_report(self.claim)
        self.assertEqual(report["validation_status"], "reference_pending")
        self.assertIn("not verified", report["reference_warnings"][0])
        self.assertIsNone(find_diagnosis_reference("E119"))
        malformed.refresh_from_db()
        self.assertEqual(malformed.code, "E1.19")
        self.assertEqual(Icd10Code.objects.count(), 1)

    def test_inactive_historical_reference_is_advisory(self):
        self.add_diagnosis()
        self.claim.service_start_date = date(2025, 1, 1)
        self.reference(is_active=False, effective_end_date=date(2025, 12, 31))
        report = reference_report(self.claim)
        self.assertIn("marked inactive", report["reference_warnings"][0])
        self.assertIn("review its applicability", report["reference_warnings"][0])
        self.assertIsNone(find_diagnosis_reference("E11.9"))

    def test_effective_date_mismatch_needs_review(self):
        self.add_diagnosis()
        self.claim.service_start_date = date(2026, 11, 1)
        self.reference(effective_end_date=date(2026, 10, 31))
        self.assertIn("outside", reference_report(self.claim)["reference_warnings"][0])

    def test_linked_line_dates_take_precedence_for_diagnosis(self):
        diagnosis = self.add_diagnosis()
        self.claim.service_start_date = date(2026, 9, 1)
        self.claim.service_end_date = date(2026, 11, 30)
        self.reference(effective_start_date=date(2026, 10, 1), effective_end_date=date(2026, 11, 1))
        line = ServiceLine.objects.create(
            claim=self.claim, procedure_code="99214", service_from_date=date(2026, 11, 1),
        )
        ServiceLineDiagnosis.objects.create(service_line=line, diagnosis=diagnosis, position=1)
        ProcedureCode.objects.create(code="99214", code_system="cpt", short_description="Synthetic reference")
        self.assertEqual(reference_report(self.claim)["reference_warnings"], [])

    def test_missing_dates_do_not_certify_dated_reference(self):
        self.add_diagnosis()
        self.reference(effective_start_date=date(2026, 10, 1))
        report = reference_report(self.claim)
        self.assertEqual(report["validation_status"], "reference_pending")
        self.assertIn("service dates are unavailable", report["reference_warnings"][0])

    def test_unknown_code_does_not_create_reference(self):
        self.add_diagnosis()
        report = reference_report(self.claim)
        self.assertEqual(report["reference_status_label"], "Reference review needed")
        self.assertEqual(Icd10Code.objects.count(), 0)
        self.assertEqual(ProcedureCode.objects.count(), 0)

    def test_empty_claim_is_not_reported_as_matched(self):
        report = reference_report(self.claim)
        self.assertEqual(report["validation_status"], "reference_pending")
        self.assertEqual(report["reference_status_label"], "Not checked")

    def test_malformed_claim_value_is_visible_as_format_warning(self):
        self.add_diagnosis("E1.19")
        report = reference_report(self.claim)
        self.assertEqual(report["validation_status"], "reference_pending")
        self.assertIn("format needs correction", report["reference_warnings"][0])
