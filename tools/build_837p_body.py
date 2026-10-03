"""Build the 837P transaction body, Table 2 only.

Table 1 and the interchange envelope are not produced here. Use the
generate_837p management command for an enveloped prototype file.

Every claim is validated before any segment is built. A claim that fails is
reported and skipped unless --ignore/--force is used for investigation.
These checks do not establish payer acceptance or complete X12 compliance.

Usage:
    python tools/build_837p_body.py
    python tools/build_837p_body.py --claim CLM-DEMO-001
    python tools/build_837p_body.py --ignore '2010BB N4' --out body.txt
    python tools/build_837p_body.py --force
"""

import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "tools"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from claims.models import Claim
from edi import builders, context, segments, validators


def main():
    parser = argparse.ArgumentParser(description="Build the 837P transaction body.")
    parser.add_argument("--out")
    parser.add_argument("--status")
    parser.add_argument("--claim", action="append", default=[])
    parser.add_argument("--one-line", action="store_true")
    parser.add_argument("--ignore", action="append", default=[], metavar="TAG")
    parser.add_argument("--force", action="store_true",
                        help="build even for claims that failed validation")
    args = parser.parse_args()

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
    if args.status:
        claims = claims.filter(status=args.status)
    if args.claim:
        claims = claims.filter(claim_number__in=args.claim)

    accepted = []
    rejected = []
    all_issues = []
    for ctx in context.build_many(claims):
        if not ctx.is_usable:
            rejected.append((ctx.claim.claim_number,
                             [validators.Issue("2300", r) for r in ctx.fatal]))
            continue
        issues = validators.filter_issues(validators.validate(ctx), args.ignore)
        all_issues.extend(issues)
        if issues and not args.force:
            rejected.append((ctx.claim.claim_number, issues))
        else:
            accepted.append(ctx)

    body, counter = builders.build_body(accepted)
    text = segments.serialize(body, line_breaks=not args.one_line) if body else ""

    if text:
        if args.out:
            Path(args.out).write_text(text + "\n", encoding="utf-8")
        else:
            print(text)

    print("")
    if args.out and text:
        print(f"wrote {args.out}")
    print(f"accepted      {len(accepted)}")
    print(f"rejected      {len(rejected)}")
    print(f"segments      {len(body)}")
    print(f"hl loops      {counter.count}")
    print(f"service lines {sum(1 for s in body if s.segment_id == 'LX')}")

    if rejected:
        print("")
        print("not built:")
        for name, issues in rejected:
            print(f"{name}")
            for issue in issues:
                print(f"    {issue}")
        if not args.force:
            print("")
            print("use --ignore TAG to suppress a known open question, "
                  "or --force to build anyway")

    counts = validators.summarise(all_issues)
    if counts:
        print("")
        print("issues by element:")
        for tag, count in counts.items():
            print(f"{count:<4}{tag}")

    print("")
    print("table 1 and the envelope are not built here, "
          "use the generate_837p command for a complete file")


if __name__ == "__main__":
    main()
