"""Export claim data to CSV using X12 837P element names as column headers.

Read only. Never writes to the claims tables.
One row per service line.

Every value and every check comes from the edi package, so the CSV and the
generated 837P cannot disagree.

Usage:
    python tools/export_claims_csv.py
    python tools/export_claims_csv.py --out out.csv --status ready_for_review
    python tools/export_claims_csv.py --only-ready --ignore '2010AA N403'
"""

import argparse
import csv
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
from edi import builders, codes, context, formatters, validators

COLUMNS = [
    "claim_id",
    "claim_status",
    "CLM01_claim_number",
    "CLM02_total_charge",
    "CLM05_1_place_of_service",
    "CLM05_2_qualifier",
    "CLM05_3_frequency",
    "CLM08_benefits_assignment",
    "CLM09_release_of_info",
    "2010AA_NM103_billing_name",
    "2010AA_NM109_billing_npi",
    "2010AA_N301_address",
    "2010AA_N401_city",
    "2010AA_N402_state",
    "2010AA_N403_zip",
    "2010AA_REF_EI_tax_id",
    "2000A_PRV03_taxonomy",
    "2000B_SBR01_payer_sequence",
    "2000B_SBR02_relationship",
    "SBR02_decided_by",
    "2000B_SBR03_group_number",
    "2000B_SBR09_filing_indicator",
    "2010BA_NM103_last_name",
    "2010BA_NM104_first_name",
    "2010BA_NM109_member_id",
    "2010BA_DMG02_birth_date",
    "2010BA_DMG03_sex",
    "2010BB_NM103_payer_name",
    "2010BB_NM109_payer_id",
    "2010BB_N301_address",
    "2010BB_N401_city",
    "2010BB_N402_state",
    "2010BB_N403_zip",
    "HI_01",
    "HI_02",
    "HI_03",
    "HI_04",
    "LX01_line_number",
    "2400_SV101_procedure",
    "2400_SV102_charge",
    "2400_SV103_unit",
    "2400_SV104_quantity",
    "2400_SV105_line_pos",
    "2400_SV107_diagnosis_pointers",
    "2400_DTP472_service_date",
    "2420A_NM103_rendering_last",
    "2420A_NM109_rendering_npi",
    "ready_for_837p",
    "issue_count",
    "issues",
]


def base_row(ctx):
    billing = ctx.billing
    hi = [f"{q}:{c}" for q, c in ctx.diagnosis_pairs()]

    return {
        "claim_id": str(ctx.claim.id),
        "claim_status": ctx.claim.status,
        "CLM01_claim_number": formatters.clean(ctx.claim.claim_number),
        "CLM02_total_charge": formatters.amount(ctx.claim.total_charge_amount),
        "CLM05_1_place_of_service": ctx.place_of_service,
        "CLM05_2_qualifier": codes.FACILITY_CODE_QUALIFIER,
        "CLM05_3_frequency": codes.CLAIM_FREQUENCY_ORIGINAL,
        "CLM08_benefits_assignment": "Y" if ctx.coverage.assignment_of_benefits else "N",
        "CLM09_release_of_info": "Y" if ctx.coverage.release_of_information else "I",
        "2010AA_NM103_billing_name": formatters.clean(
            billing.organization_name or billing.last_name) if billing else "",
        "2010AA_NM109_billing_npi": formatters.digits(billing.npi) if billing else "",
        "2010AA_N301_address": formatters.clean(billing.address_line_1) if billing else "",
        "2010AA_N401_city": formatters.clean(billing.city) if billing else "",
        "2010AA_N402_state": formatters.clean(billing.state) if billing else "",
        "2010AA_N403_zip": formatters.digits(billing.zip_code) if billing else "",
        "2010AA_REF_EI_tax_id": formatters.digits(billing.tax_id) if billing else "",
        "2000A_PRV03_taxonomy": formatters.clean(billing.taxonomy_code) if billing else "",
        "2000B_SBR01_payer_sequence": codes.PAYER_SEQUENCE.get(ctx.coverage.payer_sequence, ""),
        "2000B_SBR02_relationship": ctx.sbr02 if ctx.patient_is_subscriber else "",
        "SBR02_decided_by": ctx.sbr02_source,
        "2000B_SBR03_group_number": formatters.clean(ctx.policy.group_number),
        "2000B_SBR09_filing_indicator": codes.FILING_INDICATOR.get(ctx.payer.payer_type, "ZZ"),
        "2010BA_NM103_last_name": formatters.clean(ctx.insured.last_name),
        "2010BA_NM104_first_name": formatters.clean(ctx.insured.first_name),
        "2010BA_NM109_member_id": formatters.clean(ctx.policy.member_id),
        "2010BA_DMG02_birth_date": formatters.d8(ctx.insured.date_of_birth),
        "2010BA_DMG03_sex": codes.SEX.get((ctx.insured.sex or "").lower(), "U"),
        "2010BB_NM103_payer_name": formatters.clean(ctx.payer.payer_name),
        "2010BB_NM109_payer_id": formatters.clean(ctx.payer.payer_identifier),
        "2010BB_N301_address": formatters.clean(ctx.payer.address_line_1),
        "2010BB_N401_city": formatters.clean(ctx.payer.city),
        "2010BB_N402_state": formatters.clean(ctx.payer.state),
        "2010BB_N403_zip": builders.payer_postal_code(ctx.payer),
        "HI_01": hi[0] if len(hi) > 0 else "",
        "HI_02": hi[1] if len(hi) > 1 else "",
        "HI_03": hi[2] if len(hi) > 2 else "",
        "HI_04": hi[3] if len(hi) > 3 else "",
    }


def build_rows(ctx, issues):
    claim_level = [i for i in issues if i.line is None]
    base = base_row(ctx)

    rows = []
    for number, line in enumerate(ctx.service_lines, start=1):
        segments = builders.service_line_loop(ctx, line, number)
        sv1 = next(s for s in segments if s.segment_id == "SV1")
        dtp = next(s for s in segments if s.segment_id == "DTP")
        renderer = line.rendering_provider or ctx.rendering

        row = dict(base)
        row.update({
            "LX01_line_number": number,
            "2400_SV101_procedure": sv1.element(1),
            "2400_SV102_charge": sv1.element(2),
            "2400_SV103_unit": sv1.element(3),
            "2400_SV104_quantity": sv1.element(4),
            "2400_SV105_line_pos": sv1.element(5),
            "2400_SV107_diagnosis_pointers": sv1.element(7),
            "2400_DTP472_service_date": dtp.element(3),
            "2420A_NM103_rendering_last": formatters.clean(
                renderer.last_name or renderer.organization_name) if renderer else "",
            "2420A_NM109_rendering_npi": formatters.digits(renderer.npi) if renderer else "",
        })

        line_issues = claim_level + [i for i in issues if i.line == number]
        row["ready_for_837p"] = "N" if line_issues else "Y"
        row["issue_count"] = len(line_issues)
        row["issues"] = " | ".join(str(i) for i in line_issues)
        rows.append(row)

    return rows


def main():
    parser = argparse.ArgumentParser(
        description="Export claims to CSV using X12 837P column names."
    )
    parser.add_argument("--out", default="claims_837p_export.csv")
    parser.add_argument("--status")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--only-ready", action="store_true")
    parser.add_argument("--ignore", action="append", default=[], metavar="TAG",
                        help="suppress issues whose tag starts with TAG, repeatable")
    args = parser.parse_args()

    if args.ignore:
        print("suppressing issues starting with: " + ", ".join(args.ignore))

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
    if args.limit:
        claims = claims[: args.limit]

    all_rows = []
    all_issues = []
    skipped = []
    for ctx in context.build_many(claims):
        if not ctx.is_usable:
            skipped.append((ctx.claim.claim_number, ctx.fatal))
            continue
        issues = validators.filter_issues(validators.validate(ctx), args.ignore)
        all_issues.extend(issues)
        all_rows.extend(build_rows(ctx, issues))

    if args.only_ready:
        all_rows = [r for r in all_rows if r["ready_for_837p"] == "Y"]

    out_path = Path(args.out)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)

    claim_ids = {r["claim_id"] for r in all_rows}
    not_ready = {r["claim_id"] for r in all_rows if r["ready_for_837p"] == "N"}

    print(f"wrote {out_path}")
    print(f"claims        {len(claim_ids)}")
    print(f"service lines {len(all_rows)}")
    print(f"ready         {len(claim_ids - not_ready)}")
    print(f"not ready     {len(not_ready)}")
    for name, reasons in skipped:
        print(f"skipped {name}: {'; '.join(reasons)}")

    counts = validators.summarise(all_issues)
    if counts:
        print("")
        print("issues by element:")
        for tag, count in counts.items():
            print(f"{count:<4}{tag}")


if __name__ == "__main__":
    main()
