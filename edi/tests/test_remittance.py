import hashlib
import io
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from claims.models import Claim, Patient
from edi.models import BatchClaim, RemittanceClaim, RemittanceDocument
from edi.remittance import MAX_835_BYTES, import_835, parse_835
from edi.tests.test_archive import make_batch


def synthetic_response(claim_number="CLM-TEST-003", extra=(), line_ending="\r\n"):
    isa = "ISA*00*          *00*          *ZZ*SYNTHETICPAYER *ZZ*SYNTHETICPORTAL*261106*1200*^*00501*000000001*0*T*:"
    assert len(isa) == 105
    body = ["ST*835*0001", "BPR*I*70.00*C*NON************20261106", "TRN*1*SYNTHETIC-ONLY*1999999999",
        "N1*PR*FICTIONAL DEMO PAYER", "N1*PE*FICTIONAL DEMO CLINIC",
        f"CLP*{claim_number}*1*88.40*70.00*5.00*CI*DEMO-PAYER-001",
        "SVC*HC:99213*88.40*70.00", "CAS*CO*45*13.40", "CAS*PR*1*5.00", "REF*6R*1", *extra]
    body.append(f"SE*{len(body) + 1}*0001")
    segments = [isa, "GS*HP*SYNTHETICPAYER*SYNTHETICPORTAL*20261106*1200*1*X*005010X221A1", *body,
        "GE*1*1", "IEA*1*000000001"]
    return (line_ending.join(segment + "~" for segment in segments) + line_ending).encode("ascii")


class RemittanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        patient = Patient.objects.create(first_name="Fictional", last_name="Patient")
        cls.claim = Claim.objects.create(patient=patient, claim_number="CLM-TEST-003", total_charge_amount="88.40")
        cls.staff = get_user_model().objects.create_user("reviewer", password="test-only-password", is_staff=True)
        cls.member = get_user_model().objects.create_user("viewer", password="test-only-password")

    def test_exact_archive_decimal_results_and_idempotent_retry(self):
        payload = synthetic_response()
        doc, created = import_835(payload, source_name="/incoming/sample.835", imported_by="reviewer")
        again, retried = import_835(payload, source_name="renamed.835", imported_by="another reviewer")
        self.assertTrue(created)
        self.assertFalse(retried)
        self.assertEqual(doc.pk, again.pk)
        self.assertEqual(doc.content.encode("ascii"), payload)
        self.assertEqual(doc.sha256, hashlib.sha256(payload).hexdigest())
        self.assertEqual(doc.source_name, "sample.835")
        self.assertEqual(again.imported_by, "reviewer")
        result = doc.claim_results.get()
        self.assertEqual(result.claim_id, self.claim.pk)
        self.assertEqual(result.paid_amount, Decimal("70.00"))
        self.assertEqual(result.details["services"][0]["adjustments"][0]["amount"], "13.40")
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, Claim.STATUS_DRAFT)

    def test_unmatched_result_is_preserved_without_inventing_claim(self):
        doc, _ = import_835(synthetic_response("UNKNOWN-CLAIM"), source_name="return.835", imported_by="test")
        self.assertIsNone(doc.claim_results.get().claim_id)
        self.assertEqual(Claim.objects.count(), 1)

    def test_batch_assertion_is_checked_and_wrong_batch_rolls_back(self):
        batch = make_batch()
        with self.assertRaises(ValidationError):
            import_835(synthetic_response(), source_name="return.835", imported_by="test", batch=batch)
        self.assertFalse(RemittanceDocument.objects.exists())
        BatchClaim.objects.create(batch=batch, claim_id=self.claim.pk, claim_number=self.claim.claim_number, position=1)
        doc, _ = import_835(synthetic_response(), source_name="return.835", imported_by="test", batch=batch)
        self.assertEqual(doc.batch_id, batch.pk)

    def test_bad_files_are_rejected_without_partial_records(self):
        good = synthetic_response()
        variants = [b"", b"<html>not an EDI file</html>", good[:100], good.replace(b"ST*835", b"ST*837"),
            good.replace(b"SE*11*0001", b"SE*99*0001"), good.replace(b"GE*1*1", b"GE*2*1"),
            good.replace(b"IEA*1*000000001", b"IEA*1*000000002"), good[:-10],
            good.replace(b"88.40", b"NaN", 1), good.replace(b"88.40", b"88.401", 1),
            good.replace(b"88.40", b"1E2", 1), good.replace(b"SYNTHETIC-ONLY", b"bad\x00text"),
            b"X" * (MAX_835_BYTES + 1)]
        for payload in variants:
            with self.subTest(payload=payload[:30]):
                with self.assertRaises(ValidationError):
                    import_835(payload, source_name="bad.835", imported_by="test")
        self.assertEqual(RemittanceDocument.objects.count(), 0)
        self.assertEqual(RemittanceClaim.objects.count(), 0)

    def test_signed_reversal_and_unknown_segments_are_not_lost(self):
        payload = synthetic_response(extra=("PLB*1234567893*20261231*WO:DEMO*5", "NTE*ADD*FICTIONAL NOTE"))
        payload = payload.replace(b"CLP*CLM-TEST-003*1*88.40*70.00*5.00", b"CLP*CLM-TEST-003*22*-88.40*-70.00*-5.00")
        doc, _ = import_835(payload, source_name="reversal.835", imported_by="test")
        self.assertEqual(doc.claim_results.get().paid_amount, Decimal("-70.00"))
        self.assertIn("NTE", doc.summary["uninterpreted_segments"])
        self.assertTrue(any("PLB" in note for note in doc.summary["notes"]))
        self.assertIn("FICTIONAL NOTE", doc.content)

    def test_alternate_x12_delimiters_and_line_endings(self):
        payload = synthetic_response(line_ending="\n").replace(b"*", b"|").replace(b"~", b"!")
        content, _, results = parse_835(payload)
        self.assertEqual(content.encode("ascii"), payload)
        self.assertEqual(results[0]["paid_amount"], "70.00")

    def test_archive_cannot_be_modified_by_instance_save(self):
        doc, _ = import_835(synthetic_response(), source_name="test.835", imported_by="test")
        doc.content = "changed"
        with self.assertRaises(ValidationError):
            doc.save()

    def test_all_response_routes_require_active_staff(self):
        doc, _ = import_835(synthetic_response(), source_name="test.835", imported_by="test")
        urls = [reverse("edi:remittance_list"), reverse("edi:remittance_import"),
            reverse("edi:remittance_detail", args=[doc.pk]), reverse("edi:remittance_download", args=[doc.pk])]
        for user in [None, self.member]:
            if user:
                self.client.force_login(user)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.staff)
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(self.client.get(urls[-1]).content, synthetic_response())

    def test_upload_escapes_untrusted_filename_and_shows_matched_details(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse("edi:remittance_import"), {
            "file": SimpleUploadedFile("<script>alert(1)</script>.835", synthetic_response())}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Returned claim results")
        self.assertContains(response, "70.00")
        self.assertContains(response, "View captured claim")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertEqual(RemittanceDocument.objects.count(), 1)

    def test_bad_upload_retains_form_error_and_cli_does_not_print_payload(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse("edi:remittance_import"), {"file": SimpleUploadedFile("bad.835", b"private patient content")})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "fixed-width ISA")
        self.assertFalse(RemittanceDocument.objects.exists())
        output = io.StringIO()
        call_command("import_835", file=str(Path(__file__).parent / "fixtures" / "synthetic_response.835"), stdout=output)
        self.assertIn("Imported 835", output.getvalue())
        self.assertNotIn("CLM-TEST-003", output.getvalue())

    def test_historical_claim_number_uses_export_identity_and_reuse_is_unmatched(self):
        batch = make_batch()
        original_number = self.claim.claim_number
        BatchClaim.objects.create(batch=batch, claim_id=self.claim.pk, claim_number=original_number, position=1)
        self.claim.claim_number = "RENAMED-CLAIM"
        self.claim.save()
        doc, _ = import_835(synthetic_response(), source_name="renamed.835", imported_by="test")
        self.assertEqual(doc.claim_results.get().claim_id, self.claim.pk)
        replacement = Claim.objects.create(patient=self.claim.patient, claim_number=original_number)
        second, _ = import_835(synthetic_response(line_ending="\n"), source_name="ambiguous.835", imported_by="test")
        self.assertIsNone(second.claim_results.get().claim_id)
        third, _ = import_835(synthetic_response(line_ending=""), source_name="confirmed.835", imported_by="test", batch=batch)
        self.assertEqual(third.claim_results.get().claim_id, self.claim.pk)
        self.assertNotEqual(third.claim_results.get().claim_id, replacement.pk)

    def test_batch_requires_original_number_not_renamed_current_number(self):
        batch = make_batch()
        BatchClaim.objects.create(batch=batch, claim_id=self.claim.pk, claim_number="ORIGINAL-CLM", position=1)
        with self.assertRaises(ValidationError):
            import_835(synthetic_response(), source_name="wrong-number.835", imported_by="test", batch=batch)
        self.assertFalse(RemittanceDocument.objects.exists())

    def test_group_identity_disambiguates_reused_transaction_controls(self):
        segments = synthetic_response().decode("ascii").split("~\r\n")[:-1]
        group_one = segments[1:-1]
        group_two = [s.replace("*1200*1*X*", "*1200*2*X*").replace("GE*1*1", "GE*1*2") for s in group_one]
        payload = ("~\r\n".join([segments[0], *group_one, *group_two, "IEA*2*000000001"]) + "~\r\n").encode("ascii")
        doc, _ = import_835(payload, source_name="two-groups.835", imported_by="test")
        self.assertEqual(doc.claim_results.count(), 2)
        self.assertEqual([r.details["group_control"] for r in doc.claim_results.all()], ["1", "2"])
        self.assertEqual([r.details["transaction_index"] for r in doc.claim_results.all()], [1, 2])

    def test_invalid_loop_boundary_duplicate_trace_and_excess_adjustments_fail(self):
        extras = [("LX*2", "CAS*CO*45*1.00"), ("TRN*1*DUPLICATE",),
                  ("CAS*CO*" + "*".join(["45", "1.00", "1"] * 7),)]
        for extra in extras:
            with self.subTest(extra=extra):
                with self.assertRaises(ValidationError):
                    parse_835(synthetic_response(extra=extra))

    def test_download_detects_tampered_archive(self):
        doc, _ = import_835(synthetic_response(), source_name="test.835", imported_by="test")
        RemittanceDocument.objects.filter(pk=doc.pk).update(content="corrupted outside application")
        self.client.force_login(self.staff)
        response = self.client.get(reverse("edi:remittance_download", args=[doc.pk]))
        self.assertEqual(response.status_code, 409)
        self.assertNotIn(b"corrupted outside application", response.content)
