"""The capture model can grow; 837P cannot silently drop its relationships."""
import io
import json
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from claims.models import Claim, ClaimDiagnosis, ServiceLine, ServiceLineDiagnosis, ServiceLineModifier
from edi import builders, context, validators
from edi.models import ControlNumber, X12Document
from tools.make_test_claims import create


class NormalizedExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with redirect_stdout(io.StringIO()):
            create()
        call_command("seed_trading_partner", stdout=io.StringIO())

    def setUp(self):
        self.claim = Claim.objects.get(claim_number="CLM-TEST-003")
        self.line = self.claim.service_lines.get()

    def add_diagnoses(self, count):
        for order in range(2, count + 1):
            diagnosis = ClaimDiagnosis.objects.create(claim=self.claim, diagnosis_code=f"Z{order:02}.0", diagnosis_order=order)
            ServiceLineDiagnosis.objects.create(service_line=self.line, diagnosis=diagnosis, position=order)

    def test_ordered_links_map_to_claim_diagnosis_numbers(self):
        self.add_diagnoses(3)
        self.line.diagnosis_links.all().delete()
        for position, order in enumerate([3, 1, 2], start=1):
            ServiceLineDiagnosis.objects.create(service_line=self.line, diagnosis=self.claim.diagnoses.get(diagnosis_order=order), position=position)
        for position, code in enumerate(["59", "25"], start=1):
            ServiceLineModifier.objects.create(service_line=self.line, code=code, position=position)
        result = builders.service_line_loop(context.build(self.claim), self.line, 1)
        sv1 = next(segment for segment in result if segment.segment_id == "SV1")
        self.assertEqual(sv1.element(7), "3:1:2")
        self.assertEqual(sv1.element(1), "HC:99213:59:25")

    def test_one_diagnosis_can_support_multiple_service_lines(self):
        second = ServiceLine.objects.create(claim=self.claim, service_from_date=self.line.service_from_date,
            procedure_code="99213", charge_amount="0.00", units=1)
        ServiceLineDiagnosis.objects.create(service_line=second, diagnosis=self.claim.diagnoses.get(), position=1)
        body, _ = builders.build_body([context.build(self.claim)])
        self.assertEqual([s.element(7) for s in body if s.segment_id == "SV1"], ["1", "1"])

    def test_five_links_are_saved_but_blocked_at_wire_boundary(self):
        self.add_diagnoses(5)
        ctx = context.build(self.claim)
        self.assertEqual(self.line.diagnosis_links.count(), 5)
        self.assertTrue(any("at most 4 diagnosis" in i.message for i in validators.validate(ctx)))
        with self.assertRaisesRegex(ValueError, "at most 4 diagnosis"):
            builders.build_body([ctx])

    def test_five_modifiers_are_saved_but_blocked_at_wire_boundary(self):
        for position, code in enumerate(["25", "59", "GT", "KX", "RT"], start=1):
            ServiceLineModifier.objects.create(service_line=self.line, code=code, position=position)
        with self.assertRaisesRegex(ValueError, "at most 4 modifiers"):
            builders.service_line_loop(context.build(self.claim), self.line, 1)
        self.assertEqual(self.line.modifiers.count(), 5)

    def test_thirteen_diagnoses_do_not_truncate_hi(self):
        for order in range(2, 14):
            ClaimDiagnosis.objects.create(claim=self.claim, diagnosis_code=f"Z{order:02}.0", diagnosis_order=order)
        with self.assertRaisesRegex(ValueError, "at most 12"):
            builders.claim_loop(context.build(self.claim))
        self.assertEqual(self.claim.diagnoses.count(), 13)

    def test_force_ignore_cannot_bypass_wire_limit_or_create_partial_artifact(self):
        self.add_diagnoses(5)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "overflow.edi"
            with self.assertRaisesRegex(CommandError, "at most 4 diagnosis"):
                call_command("generate_837p", claim=[self.claim.claim_number], out=str(path), force=True,
                             ignore=["2400"], stdout=io.StringIO())
            self.assertFalse(path.exists())
        self.assertFalse(ControlNumber.objects.exists())
        self.assertFalse(X12Document.objects.exists())

    def test_export_checks_same_claim_even_after_bulk_write_bypasses_clean(self):
        other = Claim.objects.get(claim_number="CLM-TEST-002").diagnoses.first()
        self.line.diagnosis_links.all().update(diagnosis=other)
        with self.assertRaisesRegex(ValueError, "another claim"):
            builders.build_body([context.build(self.claim)])

    def test_csv_keeps_every_diagnosis_and_pointer_when_wire_is_blocked(self):
        from tools.export_claims_csv import build_rows
        self.add_diagnoses(5)
        ctx = context.build(self.claim)
        # Even when presentation checks were suppressed, the format boundary
        # and lossless review fields remain explicit.
        rows = build_rows(ctx, [])
        self.assertEqual(len(json.loads(rows[0]["HI_diagnoses_json"])), 5)
        self.assertEqual(json.loads(rows[0]["captured_diagnosis_pointers_json"]), [1, 2, 3, 4, 5])
        self.assertEqual(rows[0]["2400_SV107_diagnosis_pointers"], "")
        self.assertEqual(rows[0]["ready_for_837p"], "N")
