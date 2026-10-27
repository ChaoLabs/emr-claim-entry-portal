import io
import os
import stat
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from edi.models import SubmissionBatch, TradingPartner, X12Document


class RestoreX12Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_trading_partner", stdout=io.StringIO())
        batch = SubmissionBatch.objects.create(
            trading_partner=TradingPartner.objects.get(), file_name="test.edi",
            isa_control_number="000000001", gs_control_number="1", st_control_number="0001",
        )
        # Deliberately exercise trailing spaces, CRLF and UTF-8 byte counts.
        # Archival preserves input; it is not an X12 validator.
        cls.content = "ISA*TEST  ~\r\nNTE*ADD*测试~\r\nIEA*1*000000001~\r\n"
        cls.document = X12Document.archive(batch=batch, content=cls.content)

    def restore(self, path, document=None):
        output = io.StringIO()
        call_command("restore_x12", document=str(document or self.document.id),
                     out=str(path), stdout=output)
        return output.getvalue()

    def test_restore_preserves_exact_bytes_without_creating_another_document(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "restored.edi"
            output = self.restore(path)
            self.assertEqual(path.read_bytes(), self.content.encode("utf-8"))
            self.assertIn(str(self.document.id), output)
            self.assertNotIn("NTE*", output)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(X12Document.objects.count(), 1)

    def test_restore_refuses_existing_file_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "existing.edi"
            target.write_bytes(b"keep me")
            paths = [target]
            if os.name == "posix":
                link = Path(directory) / "link.edi"
                link.symlink_to(target)
                paths.append(link)
            for path in paths:
                with self.subTest(path=path), self.assertRaises(CommandError):
                    self.restore(path)
            self.assertEqual(target.read_bytes(), b"keep me")

    def test_missing_document_or_bad_uuid_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "restored.edi"
            for document_id in (str(uuid.uuid4()), "not-a-uuid"):
                with self.subTest(document_id=document_id), self.assertRaises(CommandError):
                    self.restore(path, document=document_id)
                self.assertFalse(path.exists())

    def test_integrity_failure_does_not_publish_corrupted_content(self):
        for updates in ({"content": "modified"}, {"byte_count": 1}, {"sha256": "0" * 64}):
            with self.subTest(updates=updates), tempfile.TemporaryDirectory() as directory:
                # Simulate privileged database modification outside the normal
                # archive API and model save guard.
                X12Document.objects.filter(pk=self.document.pk).update(
                    content=self.content, byte_count=self.document.byte_count,
                    sha256=self.document.sha256,
                )
                X12Document.objects.filter(pk=self.document.pk).update(**updates)
                path = Path(directory) / "restored.edi"
                with self.assertRaisesMessage(CommandError, "integrity check"):
                    self.restore(path)
                self.assertFalse(path.exists())

    def test_write_failure_removes_incomplete_output_but_preserves_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "restored.edi"
            with patch("edi.management.commands.restore_x12.os.fsync", side_effect=OSError("disk error")):
                with self.assertRaises(CommandError):
                    self.restore(path)
            self.assertFalse(path.exists())
        self.assertEqual(X12Document.objects.get().content, self.content)
