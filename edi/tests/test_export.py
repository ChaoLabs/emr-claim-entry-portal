import io
import os
import stat
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from claims.models import Claim, ClaimCoverage, ClaimDiagnosis, ClaimProvider
from edi import builders, context, envelope, segments, validators
from edi.models import BatchClaim, ControlNumber, SubmissionBatch, TradingPartner
from tools.make_test_claims import create as create_test_claims


class EnvelopeTests(SimpleTestCase):
    def partner(self):
        return TradingPartner(
            isa_sender_id="EMRTSDEMO", isa_receiver_id="DEMOMAC",
            gs_sender_code="EMRTSDEMO", gs_receiver_code="DEMOMAC",
            submitter_name="Fictional Clinic", submitter_id="EMRTSDEMO",
            receiver_name="Fictional Payer", receiver_id="DEMOMAC",
        )

    def test_control_numbers_are_not_truncated(self):
        for value in (1, 9999, 10000, 999999999):
            with self.subTest(value=value):
                self.assertEqual(envelope.st(value).element(2), f"{value:04d}")
                self.assertEqual(envelope.se(10, value).element(2), f"{value:04d}")

    def test_out_of_range_numbers_are_rejected(self):
        for value in (-1, 1000000000, "abc"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                envelope.st(value)

    def test_isa_is_exactly_106_characters_including_terminator(self):
        isa = envelope.isa(self.partner(), 1, datetime(2026, 1, 1))
        wire = segments.serialize([isa])
        self.assertEqual(len(wire), 106)
        self.assertEqual(wire[3], "*")
        self.assertEqual(wire[104:106], ":~")
        self.assertEqual(isa.element(13), "000000001")

    def test_envelope_counts_and_pairs_match(self):
        body = [segments.Segment("HL", "1", "", "20", "0")]
        wire = envelope.wrap(body, self.partner(), (17, 23, 10000), "TEST",
                             datetime(2026, 1, 1, tzinfo=timezone.utc))
        by_id = {s.segment_id: s for s in wire}
        self.assertEqual(by_id["ISA"].element(13), by_id["IEA"].element(2))
        self.assertEqual(by_id["GS"].element(6), by_id["GE"].element(2))
        self.assertEqual(by_id["ST"].element(2), by_id["SE"].element(2))
        self.assertEqual(int(by_id["SE"].element(1)), len(wire) - 4)
        self.assertEqual(by_id["GE"].element(1), "1")
        self.assertEqual(by_id["IEA"].element(1), "1")


class ExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with redirect_stdout(io.StringIO()):
            create_test_claims()
        call_command("seed_trading_partner", stdout=io.StringIO())

    def setUp(self):
        self.claim = Claim.objects.get(claim_number="CLM-TEST-003")
        self.partner = TradingPartner.objects.get(name="Demo MAC Test")

    def run_export(self, **options):
        output = io.StringIO()
        call_command("generate_837p", stdout=output, **options)
        return output.getvalue()

    def test_valid_fixture_passes_and_invalid_fixture_fails(self):
        self.assertEqual(validators.validate(context.build(self.claim)), [])
        child = Claim.objects.get(claim_number="CLM-TEST-002")
        self.assertIn("2010BB NM109", [i.tag for i in validators.validate(context.build(child))])

    def test_diagnoses_have_no_wire_decimal_but_snapshot_is_preserved(self):
        ctx = context.build(self.claim)
        self.assertEqual(ctx.diagnosis_pairs(), [("ABK", "M5450")])
        self.assertEqual(self.claim.diagnoses.get().diagnosis_code, "M54.50")

    def test_equivalent_diagnoses_are_detected_after_normalization(self):
        ClaimDiagnosis.objects.create(claim=self.claim, diagnosis_code="M5450", diagnosis_order=2)
        self.assertTrue(validators.validate_diagnoses(context.build(self.claim)))

    def test_explicit_relationship_overrides_demographic_match(self):
        self.claim.coverages.update(relationship_to_patient="child")
        self.assertFalse(context.build(self.claim).patient_is_subscriber)

    def test_unrecognized_relationship_does_not_guess_self(self):
        self.claim.coverages.update(relationship_to_patient="not specified")
        self.assertEqual(context.build(self.claim).sbr02, "")

    def test_dependent_relationship_is_in_pat_not_subscriber_sbr(self):
        child = Claim.objects.get(claim_number="CLM-TEST-002")
        body, _ = builders.build_body([context.build(child)])
        self.assertEqual(next(s for s in body if s.segment_id == "SBR").element(2), "")
        self.assertEqual(next(s for s in body if s.segment_id == "PAT").element(1), "19")

    def test_group_number_suppresses_group_name(self):
        child = Claim.objects.get(claim_number="CLM-TEST-002")
        body, _ = builders.build_body([context.build(child)])
        sbr = next(s for s in body if s.segment_id == "SBR")
        self.assertEqual(sbr.element(3), "GRP-9")
        self.assertEqual(sbr.element(4), "")

    def test_secondary_only_is_not_silently_exported(self):
        self.claim.coverages.update(payer_sequence="secondary")
        self.assertFalse(context.build(self.claim).is_usable)

    def test_multiple_coverages_are_not_silently_dropped(self):
        other_policy = Claim.objects.get(claim_number="CLM-TEST-002").coverages.get().insurance_policy
        ClaimCoverage.objects.create(claim=self.claim, insurance_policy=other_policy,
                                     payer_sequence="secondary")
        self.assertFalse(context.build(self.claim).is_usable)
        with self.assertRaises(CommandError):
            self.run_export(claim=[self.claim.claim_number], dry_run=True, force=True)

    def test_multiple_billing_providers_are_rejected(self):
        renderer = Claim.objects.get(claim_number="CLM-TEST-002").claim_providers.get(
            provider_role="rendering").provider
        ClaimProvider.objects.create(claim=self.claim, provider=renderer, provider_role="billing")
        self.assertFalse(context.build(self.claim).is_usable)

    def test_dry_run_has_no_database_or_file_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            output = self.run_export(claim=[self.claim.claim_number], dry_run=True,
                                     out=str(Path(directory) / "test.edi"))
            self.assertIn("ISA*", output)
            self.assertIn("HI*ABK:M5450~", output)
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(ControlNumber.objects.count(), 0)
        self.assertEqual(SubmissionBatch.objects.count(), 0)

    def test_file_batch_and_control_numbers_match(self):
        ControlNumber.objects.create(trading_partner=self.partner,
                                     level=ControlNumber.LEVEL_TRANSACTION, current_value=9999)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.edi"
            output = self.run_export(claim=[self.claim.claim_number], out=str(path))
            text = path.read_text()
            self.assertIn("ST*837*10000*005010X222A1~", text)
            self.assertIn("included      1", output)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        batch = SubmissionBatch.objects.get()
        self.assertEqual(batch.st_control_number, "10000")
        self.assertEqual(batch.status, SubmissionBatch.STATUS_GENERATED)
        self.assertEqual(batch.claim_count, 1)
        self.assertEqual(batch.file_name, "test.edi")
        self.assertEqual(batch.claims.get().claim_id, self.claim.id)
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, Claim.STATUS_READY_FOR_REVIEW)

    def test_existing_file_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.edi"
            path.write_text("do not overwrite")
            with self.assertRaises(CommandError):
                self.run_export(claim=[self.claim.claim_number], out=str(path))
            self.assertEqual(path.read_text(), "do not overwrite")
        self.assertEqual(SubmissionBatch.objects.count(), 0)

    def test_missing_output_directory_does_not_record_a_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(CommandError):
                self.run_export(claim=[self.claim.claim_number],
                                out=str(Path(directory) / "absent" / "test.edi"))
        self.assertEqual(SubmissionBatch.objects.count(), 0)

    def test_database_failure_removes_new_output_and_rolls_back_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.edi"
            with patch("edi.models.BatchClaim.objects.bulk_create", side_effect=DatabaseError("test")):
                with self.assertRaises(DatabaseError):
                    self.run_export(claim=[self.claim.claim_number], out=str(path))
            self.assertFalse(path.exists())
        self.assertEqual(SubmissionBatch.objects.count(), 0)
        # Reserved counters intentionally remain consumed; never reuse after a failure.
        self.assertEqual(ControlNumber.objects.count(), 3)

    def test_batch_positions_follow_wire_order(self):
        child = Claim.objects.get(claim_number="CLM-TEST-002")
        # Interleave claims for two subscribers to exercise builder regrouping.
        copy = Claim.objects.get(pk=child.pk)
        copy.pk = None
        copy.claim_number = "CLM-TEST-004"
        copy.save()
        first = context.build(child)
        last = context.build(child)
        last.claim = copy
        middle = context.build(self.claim)
        with patch("edi.management.commands.generate_837p.Command.screen",
                   return_value=([first, middle, last], [], [])):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "test.edi"
                self.run_export(out=str(path))
                wire = segments.parse(path.read_text())
        expected = [s.element(1) for s in wire if s.segment_id == "CLM"]
        actual = list(BatchClaim.objects.order_by("position").values_list("claim_number", flat=True))
        self.assertEqual(actual, expected)
        self.assertEqual(actual, ["CLM-TEST-002", "CLM-TEST-004", "CLM-TEST-003"])

    def test_no_partner_fails_without_consuming_numbers(self):
        TradingPartner.objects.all().delete()
        with self.assertRaises(CommandError):
            self.run_export(dry_run=True)
        self.assertFalse(ControlNumber.objects.exists())

    def test_invalid_explicit_selection_or_limit_fails(self):
        for options in ({"claim": ["absent"]}, {"limit": 0}, {"limit": -1}):
            with self.subTest(options=options), self.assertRaises(CommandError):
                self.run_export(dry_run=True, **options)

    def test_counter_does_not_wrap_to_a_previously_used_number(self):
        ControlNumber.objects.create(trading_partner=self.partner,
                                     level=ControlNumber.LEVEL_TRANSACTION, current_value=999999999)
        with self.assertRaises(ValueError):
            ControlNumber.take(self.partner, ControlNumber.LEVEL_TRANSACTION)
        self.assertEqual(ControlNumber.objects.get().current_value, 999999999)

    def test_counters_are_scoped_by_partner_and_level(self):
        self.assertEqual(ControlNumber.take(self.partner, ControlNumber.LEVEL_TRANSACTION), 1)
        self.assertEqual(ControlNumber.take(self.partner, ControlNumber.LEVEL_TRANSACTION), 2)
        self.assertEqual(ControlNumber.take(self.partner, ControlNumber.LEVEL_GROUP), 1)

    def test_partner_seed_is_repeatable(self):
        call_command("seed_trading_partner", stdout=io.StringIO())
        self.assertEqual(TradingPartner.objects.count(), 1)

    def test_detail_readiness_is_read_only(self):
        response = self.client.get(reverse("claims:claim_detail", args=[self.claim.id]))
        self.assertContains(response, "837P Export Readiness")
        self.assertContains(response, "Prototype checks passed")
        self.assertFalse(SubmissionBatch.objects.exists())
        self.assertFalse(ControlNumber.objects.exists())

    def test_detail_shows_validation_issues(self):
        child = Claim.objects.get(claim_number="CLM-TEST-002")
        response = self.client.get(reverse("claims:claim_detail", args=[child.id]))
        self.assertContains(response, "Corrections needed before export")
        self.assertContains(response, "payer identifier is empty")

    def test_generated_admin_records_are_read_only(self):
        user = get_user_model().objects.create_superuser(
            username="test-admin", password="fictional-tests-only")
        self.client.force_login(user)
        with tempfile.TemporaryDirectory() as directory:
            self.run_export(claim=[self.claim.claim_number], out=str(Path(directory) / "test.edi"))
        batch = SubmissionBatch.objects.get()
        url = reverse("admin:edi_submissionbatch_change", args=[batch.id])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {"status": "accepted"}).status_code, 403)
        batch.refresh_from_db()
        self.assertEqual(batch.status, "generated")
