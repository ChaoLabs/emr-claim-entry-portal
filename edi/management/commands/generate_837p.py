import os
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from claims.models import Claim
from edi import builders, context, envelope, formatters, segments, validators
from edi.models import BatchClaim, ControlNumber, SubmissionBatch, TradingPartner


class Command(BaseCommand):
    help = "Generate an 837P interchange for claims that pass validation."

    def add_arguments(self, parser):
        parser.add_argument("--partner", help="trading partner name")
        parser.add_argument("--out", help="output file path")
        parser.add_argument("--status", default=Claim.STATUS_READY_FOR_REVIEW)
        parser.add_argument("--claim", action="append", default=[])
        parser.add_argument("--limit", type=int)
        parser.add_argument("--one-line", action="store_true")
        parser.add_argument("--ignore", action="append", default=[], metavar="TAG",
                            help="suppress issues whose tag starts with TAG, repeatable")
        parser.add_argument("--force", action="store_true",
                            help="include claims that failed validation")
        parser.add_argument("--dry-run", action="store_true",
                            help="print the interchange without consuming a control "
                                 "number or saving a batch")

    def handle(self, *args, **options):
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be positive")
        partner = self.resolve_partner(options.get("partner"))
        accepted, rejected, issues = self.screen(options)

        if not accepted:
            self.report_rejections(rejected, options)
            raise CommandError("no claim passed validation, nothing was generated")

        wire_numbers = [formatters.clean(c.claim.claim_number) for c in accepted]
        if not all(wire_numbers) or len(set(wire_numbers)) != len(wire_numbers):
            raise CommandError("claim numbers must be nonempty and unique after X12 formatting")
        body, counter = builders.build_body(accepted)
        moment = timezone.now()

        if options["dry_run"]:
            numbers = (1, 1, 1)
        else:
            numbers = (
                ControlNumber.take(partner, ControlNumber.LEVEL_INTERCHANGE),
                ControlNumber.take(partner, ControlNumber.LEVEL_GROUP),
                ControlNumber.take(partner, ControlNumber.LEVEL_TRANSACTION),
            )

        reference = moment.strftime("%Y%m%d%H%M%S")
        interchange = envelope.wrap(body, partner, numbers, reference, moment)
        text = segments.serialize(interchange, line_breaks=not options["one_line"])

        file_name = options.get("out") or (
            f"837p_{partner.usage_indicator}_{numbers[0]:09d}_{reference}.edi"
        )

        if options["dry_run"]:
            self.stdout.write(text)
        else:
            self.write_batch(partner, accepted, file_name, numbers, interchange, text)

        self.report(file_name, accepted, rejected, interchange, counter,
                    issues, options)

    def resolve_partner(self, name):
        partners = TradingPartner.objects.filter(is_active=True)
        if name:
            partner = partners.filter(name=name).first()
            if partner is None:
                raise CommandError(f"no active trading partner named {name}")
            return partner
        if partners.count() == 1:
            return partners.first()
        if not partners.exists():
            raise CommandError(
                "no active trading partner is configured. "
                "Run seed_trading_partner or create one in the admin"
            )
        names = ", ".join(partners.values_list("name", flat=True))
        raise CommandError(f"several partners are active, choose one with --partner: {names}")

    def screen(self, options):
        claims = (
            Claim.objects.select_related("patient")
            .prefetch_related(
                "coverages__insurance_policy__insured_party",
                "coverages__insurance_policy__payer",
                "claim_providers__provider",
                "diagnoses",
                "service_lines__rendering_provider",
            )
            .order_by("created_at")
        )
        if options["claim"]:
            missing = set(options["claim"]) - set(claims.filter(
                claim_number__in=options["claim"]
            ).values_list("claim_number", flat=True))
            if missing:
                raise CommandError("one or more requested claim numbers do not exist")
            claims = claims.filter(claim_number__in=options["claim"])
        elif options["status"]:
            claims = claims.filter(status=options["status"])
        if options["limit"]:
            claims = claims[: options["limit"]]

        accepted, rejected, everything = [], [], []
        for ctx in context.build_many(claims):
            if not ctx.is_usable:
                rejected.append((ctx.claim.claim_number,
                                 [validators.Issue("2300", r) for r in ctx.fatal]))
                continue
            found = validators.filter_issues(validators.validate(ctx), options["ignore"])
            everything.extend(found)
            if found and not options["force"]:
                rejected.append((ctx.claim.claim_number, found))
            else:
                accepted.append(ctx)
        return accepted, rejected, everything

    def write_batch(self, partner, accepted, file_name, numbers, interchange, text):
        # No overwrite, including symlinks. A transfer worker must NOT watch
        # this directory yet: durable ready-publication is a separate phase.
        path = Path(file_name)
        created = False
        try:
            with transaction.atomic():
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                created = True
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(text + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                self.record_batch(partner, accepted, path.name, numbers, interchange)
        except Exception as exc:
            if created:
                path.unlink(missing_ok=True)
            if isinstance(exc, OSError):
                raise CommandError("cannot create output file; check path, permissions and existing files") from exc
            raise

    @transaction.atomic
    def record_batch(self, partner, accepted, file_name, numbers, interchange):
        total = sum((c.claim.total_charge_amount or Decimal("0")) for c in accepted)
        batch = SubmissionBatch.objects.create(
            trading_partner=partner,
            file_name=file_name,
            isa_control_number=f"{numbers[0]:09d}",
            gs_control_number=str(numbers[1]),
            st_control_number=f"{numbers[2]:04d}",
            claim_count=len(accepted),
            segment_count=len(interchange),
            total_charge_amount=total,
        )
        # The builder groups by provider/subscriber, so its wire order can
        # differ from the input queryset order.
        by_number = {formatters.clean(c.claim.claim_number): c for c in accepted}
        wire_order = [by_number[s.element(1)] for s in interchange if s.segment_id == "CLM"]
        BatchClaim.objects.bulk_create([
            BatchClaim(batch=batch, claim_id=ctx.claim.id,
                       claim_number=ctx.claim.claim_number, position=position)
            for position, ctx in enumerate(wire_order, start=1)
        ])
        return batch

    def report_rejections(self, rejected, options):
        if not rejected:
            return
        self.stdout.write("")
        self.stdout.write("not generated:")
        for name, issues in rejected:
            self.stdout.write(name)
            for issue in issues:
                self.stdout.write(f"    {issue}")
        if not options["force"]:
            self.stdout.write("")
            self.stdout.write("--ignore/--force bypass prototype checks for investigation only; "
                              "this command never sends claims")

    def report(self, file_name, accepted, rejected, interchange, counter, issues, options):
        se_segment = next(s for s in interchange if s.segment_id == "SE")
        self.stdout.write("")
        if options["dry_run"]:
            self.stdout.write("dry run, no control number used and no batch saved")
        else:
            self.stdout.write(f"wrote {file_name}")
        self.stdout.write(f"included      {len(accepted)}")
        self.stdout.write(f"excluded      {len(rejected)}")
        self.stdout.write(f"segments      {len(interchange)}")
        self.stdout.write(f"se01          {se_segment.element(1)}")
        self.stdout.write(f"hl loops      {counter.count}")

        self.report_rejections(rejected, options)

        counts = validators.summarise(issues)
        if counts:
            self.stdout.write("")
            self.stdout.write("issues by element:")
            for tag, count in counts.items():
                self.stdout.write(f"{count:<4}{tag}")
