"""Export accepts code snapshots beyond the seed data without losing syntax checks."""
import io
from contextlib import redirect_stdout

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from claims.models import (
    Claim, ClaimProvider, Icd10Code, NpiReference, ProcedureCode, Provider,
)
from edi import context, validators
from edi.models import ControlNumber, X12Document
from tools.make_test_claims import create


class ExportCodeFormatTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with redirect_stdout(io.StringIO()):
            create()
        call_command("seed_trading_partner", stdout=io.StringIO())

    def setUp(self):
        self.claim = Claim.objects.get(claim_number="CLM-TEST-003")
        self.line = self.claim.service_lines.get()
        self.diagnosis = self.claim.diagnoses.get()
        self.billing = self.claim.claim_providers.get(provider_role="billing").provider

    def issues(self):
        return validators.validate(context.build(self.claim))

    def test_null_reference_snapshots_export_without_reference_catalogs(self):
        self.assertFalse(Icd10Code.objects.exists())
        self.assertFalse(ProcedureCode.objects.exists())
        self.assertFalse(NpiReference.objects.exists())
        self.assertIsNone(self.diagnosis.icd10_reference_id)
        self.assertIsNone(self.line.procedure_reference_id)
        self.assertIsNone(self.billing.npi_reference_id)
        self.diagnosis.diagnosis_code = "e11.9"
        self.diagnosis.save(update_fields=["diagnosis_code"])
        self.line.procedure_code = "j3301"
        self.line.save(update_fields=["procedure_code"])

        self.assertEqual(self.issues(), [])
        output = io.StringIO()
        call_command("generate_837p", claim=[self.claim.claim_number],
                     dry_run=True, stdout=output)
        self.assertIn("HI*ABK:E119~", output.getvalue())
        self.assertIn("SV1*HC:J3301*", output.getvalue())
        self.assertFalse(X12Document.objects.exists())

    def test_diagnosis_snapshot_syntax_is_checked_after_database_import(self):
        for invalid in ("", "ZZZ.99", "E11..9", "E11*9", "Ｅ11.9", "E11 9"):
            with self.subTest(code=invalid):
                self.claim.diagnoses.update(diagnosis_code=invalid)
                self.assertIn("2300 HI", [issue.tag for issue in self.issues()])

    def test_procedure_snapshot_syntax_is_checked_after_database_import(self):
        for invalid in ("", "XXXXX", "9921", "99*213", "９９２１３", "99 213"):
            with self.subTest(code=invalid):
                self.claim.service_lines.update(procedure_code=invalid)
                self.assertIn("2400 SV101", [issue.tag for issue in self.issues()])

    def test_procedure_code_families_do_not_require_seed_records(self):
        for code in ("99214", "J3301", "G0439", "0001F", "0001T", "0001U", "0001M"):
            with self.subTest(code=code):
                self.claim.service_lines.update(procedure_code=code)
                self.assertEqual(self.issues(), [])

    def test_billing_npi_checks_checksum_and_original_characters(self):
        for invalid in ("", "1234567890", "abc1234567893", "123-456-7893", "１２３４５６７８９３"):
            with self.subTest(npi=invalid):
                Provider.objects.filter(pk=self.billing.pk).update(npi=invalid)
                self.assertIn("2010AA NM109", [issue.tag for issue in self.issues()])

    def test_valid_npi_snapshots_do_not_require_seed_records(self):
        for code in ("1234567893", "1098765435"):
            with self.subTest(npi=code):
                Provider.objects.filter(pk=self.billing.pk).update(npi=code)
                self.assertEqual(self.issues(), [])

    def test_claim_rendering_npi_is_checked_when_supplied(self):
        renderer = Provider.objects.create(first_name="Test", last_name="Renderer", npi="1234567890")
        ClaimProvider.objects.create(claim=self.claim, provider=renderer,
                                     provider_role=ClaimProvider.ROLE_RENDERING)
        self.assertIn("2310B NM109", [issue.tag for issue in self.issues()])
        renderer.npi = "1234567893"
        renderer.save(update_fields=["npi"])
        self.assertEqual(self.issues(), [])

    def test_line_rendering_npi_is_checked_when_supplied(self):
        renderer = Provider.objects.create(first_name="Test", last_name="Renderer", npi="1234567890")
        self.line.rendering_provider = renderer
        self.line.save(update_fields=["rendering_provider"])
        issues = self.issues()
        self.assertTrue(any(issue.tag == "2420A NM109" and issue.line == 1 for issue in issues))
        renderer.npi = "1098765435"
        renderer.save(update_fields=["npi"])
        self.assertEqual(self.issues(), [])

    def test_optional_blank_rendering_npi_keeps_existing_behavior(self):
        renderer = Provider.objects.create(first_name="Test", last_name="Renderer", npi="")
        ClaimProvider.objects.create(claim=self.claim, provider=renderer,
                                     provider_role=ClaimProvider.ROLE_RENDERING)
        self.line.rendering_provider = renderer
        self.line.save(update_fields=["rendering_provider"])
        self.assertEqual(self.issues(), [])

    def test_invalid_imported_procedure_cannot_generate_an_archive(self):
        self.claim.service_lines.update(procedure_code="99*213")
        with self.assertRaises(CommandError):
            call_command("generate_837p", claim=[self.claim.claim_number],
                         stdout=io.StringIO())
        self.assertFalse(ControlNumber.objects.exists())
        self.assertFalse(X12Document.objects.exists())

    def assert_force_export_rejected(self, tag):
        with self.assertRaisesRegex(CommandError, tag):
            call_command("generate_837p", claim=[self.claim.claim_number],
                         force=True, ignore=["2010AA", "2300", "2400"],
                         stdout=io.StringIO())
        self.assertFalse(ControlNumber.objects.exists())
        self.assertFalse(X12Document.objects.exists())

    def test_force_cannot_strip_malformed_diagnosis_into_a_different_code(self):
        self.claim.diagnoses.update(diagnosis_code="M54*50")
        self.assert_force_export_rejected("2300 HI")

    def test_force_cannot_strip_malformed_procedure_into_a_different_code(self):
        self.claim.service_lines.update(procedure_code="99*213")
        self.assert_force_export_rejected("2400 SV101")

    def test_force_cannot_strip_malformed_npi_into_a_different_identifier(self):
        Provider.objects.filter(pk=self.billing.pk).update(npi="abc1234567893")
        self.assert_force_export_rejected("2010AA NM109")
