import hashlib
import os
from pathlib import Path
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from edi.models import X12Document


class Command(BaseCommand):
    help = "Restore the exact bytes of an archived X12 document to a new file."

    def add_arguments(self, parser):
        parser.add_argument("--document", required=True, help="X12 document UUID")
        parser.add_argument("--out", required=True, help="new output file path")

    def handle(self, *args, **options):
        try:
            document_id = UUID(str(options["document"]))
        except (ValueError, TypeError, AttributeError) as exc:
            raise CommandError("--document must be a valid UUID") from exc
        try:
            document = X12Document.objects.get(pk=document_id)
        except X12Document.DoesNotExist as exc:
            raise CommandError("X12 document not found in the configured database") from exc

        try:
            payload = document.content.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise CommandError("archived document is not valid UTF-8") from exc
        if (len(payload) != document.byte_count
                or hashlib.sha256(payload).hexdigest() != document.sha256):
            raise CommandError("archived document failed its integrity check; no file written")

        path = Path(options["out"])
        created = False
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            if created:
                path.unlink(missing_ok=True)
            raise CommandError(
                "cannot create output file; check path, permissions and existing files"
            ) from exc

        self.stdout.write(f"restored {document.id} to {path} ({document.byte_count} bytes)")
