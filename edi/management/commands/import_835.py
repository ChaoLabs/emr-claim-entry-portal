from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from edi.models import SubmissionBatch
from edi.remittance import MAX_835_BYTES, import_835


class Command(BaseCommand):
    help = "Archive a received 835 and match CLP01 claim numbers. Does not contact an engine."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True)
        parser.add_argument("--batch", help="Optional confirmed submission batch UUID")
        parser.add_argument("--operator", default="command-line", help="Operator identity recorded with the import")

    def handle(self, *args, **options):
        path = Path(options["file"])
        try:
            with path.open("rb") as handle:
                payload = handle.read(MAX_835_BYTES + 1)
        except OSError as exc:
            raise CommandError("Cannot read the selected 835 file.") from exc
        batch = None
        if options["batch"]:
            try:
                batch = SubmissionBatch.objects.get(pk=options["batch"])
            except (SubmissionBatch.DoesNotExist, ValidationError, ValueError) as exc:
                raise CommandError("Submission batch does not exist or is not a valid UUID.") from exc
        try:
            document, created = import_835(payload, source_name=path.name,
                imported_by=options["operator"], batch=batch)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        unmatched = document.claim_results.filter(claim__isnull=True).count()
        self.stdout.write(f"{'Imported' if created else 'Already archived'} 835 {document.pk}; "
                          f"SHA256 {document.sha256}; {document.claim_results.count()} results; {unmatched} unmatched.")
