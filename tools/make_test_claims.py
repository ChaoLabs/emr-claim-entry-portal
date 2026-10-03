"""Create fictional test claims for the CSV exporter.

All names and identifiers are invented. Do not run against real data.

Usage:
    python tools/make_test_claims.py
    python tools/make_test_claims.py --remove
"""

import argparse
import datetime
import os
import sys
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

if __name__ == "__main__":
    django.setup()

from django.db import transaction

from claims.models import (
    Claim, ClaimCoverage, ClaimDiagnosis, ClaimProvider,
    InsurancePolicy, InsuredParty, Patient, Payer, Provider, ServiceLine,
)

TEST_NUMBERS = ["CLM-TEST-002", "CLM-TEST-003"]


@transaction.atomic
def create():
    patient = Patient.objects.create(
        first_name="Wei", last_name="Chen", date_of_birth=datetime.date(2015, 3, 9),
        sex="male", address_line_1="88 Test Avenue", city="Durham",
        state="NC", zip_code="27701",
    )
    insured = InsuredParty.objects.create(
        first_name="Ling", last_name="Chen",
        date_of_birth=datetime.date(1985, 7, 1), sex="female",
        address_line_1="88 Test Avenue", city="Durham", state="NC", zip_code="27701",
    )
    payer = Payer.objects.create(
        payer_name="Blue Shield Demo", payer_type="commercial",
        payer_identifier="",
        address_line_1="120 Demo Payer Plaza", address_line_2="Suite 300",
        city="Chapel Hill", state="NC",
        zip_code="27514", zip_code_extension="2201",
    )
    policy = InsurancePolicy.objects.create(
        insured_party=insured, payer=payer, member_id="BSD-77812",
        group_number="GRP-9", plan_name="Demo PPO", policy_type="commercial",
    )
    billing = Provider.objects.create(
        organization_name="Second Demo Clinic", npi="1098765432",
        taxonomy_code="207Q00000X", tax_id="561234567",
        address_line_1="9 Clinic Road", city="Cary", state="NC",
        zip_code="275111234",
    )
    rendering = Provider.objects.create(first_name="Ana", last_name="Ruiz", npi="1234567893")

    claim = Claim.objects.create(
        claim_number="CLM-TEST-002", patient=patient,
        status=Claim.STATUS_READY_FOR_REVIEW,
        service_start_date=datetime.date(2026, 7, 1),
        service_end_date=datetime.date(2026, 7, 3),
        total_charge_amount=Decimal("430.75"),
    )
    ClaimCoverage.objects.create(
        claim=claim, insurance_policy=policy, payer_sequence="primary",
        relationship_to_patient="child",
        assignment_of_benefits=True, release_of_information=True,
    )
    ClaimProvider.objects.create(claim=claim, provider=billing,
                                 provider_role=ClaimProvider.ROLE_BILLING)
    ClaimProvider.objects.create(claim=claim, provider=rendering,
                                 provider_role=ClaimProvider.ROLE_RENDERING)

    for order, (code, desc) in enumerate(
        [("M54.50", "Low back pain"), ("R51.9", "Headache"),
         ("M25.561", "Knee pain"), ("J06.9", "Upper respiratory infection")], start=1):
        ClaimDiagnosis.objects.create(claim=claim, diagnosis_code=code,
                                      diagnosis_order=order, description=desc)

    lines = [
        ("11", "99213", ("25", ""), (1, 2, None), Decimal("125.00")),
        ("11", "99214", ("", ""), (1, None, None), Decimal("205.75")),
        ("21", "99215", ("25", "59"), (1, 2, 3), Decimal("100.00")),
    ]
    for pos, proc, mods, ptrs, charge in lines:
        ServiceLine.objects.create(
            claim=claim, service_from_date=datetime.date(2026, 7, 1),
            service_to_date=datetime.date(2026, 7, 1), place_of_service=pos,
            procedure_code=proc, rendering_provider=rendering,
            modifier_1=mods[0], modifier_2=mods[1],
            diagnosis_pointer_1=ptrs[0], diagnosis_pointer_2=ptrs[1],
            diagnosis_pointer_3=ptrs[2], charge_amount=charge, units=1,
        )

    patient3 = Patient.objects.create(
        first_name="Rosa", last_name="Diaz", date_of_birth=datetime.date(1978, 11, 2),
        sex="female", address_line_1="4 Quiet Lane", city="Raleigh",
        state="NC", zip_code="276015512",
    )
    insured3 = InsuredParty.objects.create(
        first_name="Rosa", last_name="Diaz",
        date_of_birth=datetime.date(1978, 11, 2), sex="female",
        address_line_1="4 Quiet Lane", city="Raleigh", state="NC", zip_code="276015512",
    )
    payer3 = Payer.objects.create(
        payer_name="Medicare Demo", payer_type="medicare", payer_identifier="CMS-DEMO",
        address_line_1="7500 Demo Payer Drive",
        city="Baltimore", state="MD",
        zip_code="21244", zip_code_extension="1850",
    )
    policy3 = InsurancePolicy.objects.create(
        insured_party=insured3, payer=payer3, member_id="MED-33019",
        plan_name="Demo Medicare", policy_type="medicare",
    )
    claim3 = Claim.objects.create(
        claim_number="CLM-TEST-003", patient=patient3,
        status=Claim.STATUS_READY_FOR_REVIEW,
        service_start_date=datetime.date(2026, 7, 5),
        service_end_date=datetime.date(2026, 7, 5),
        total_charge_amount=Decimal("88.40"),
    )
    ClaimCoverage.objects.create(
        claim=claim3, insurance_policy=policy3, payer_sequence="primary",
        relationship_to_patient="self",
        assignment_of_benefits=True, release_of_information=True,
    )
    ClaimProvider.objects.create(claim=claim3, provider=billing,
                                 provider_role=ClaimProvider.ROLE_BILLING)
    ClaimDiagnosis.objects.create(claim=claim3, diagnosis_code="M54.50",
                                  diagnosis_order=1, description="Low back pain")
    ServiceLine.objects.create(
        claim=claim3, service_from_date=datetime.date(2026, 7, 5),
        service_to_date=datetime.date(2026, 7, 5), place_of_service="11",
        procedure_code="99213", diagnosis_pointer_1=1,
        charge_amount=Decimal("88.40"), units=1,
    )

    print("created:")
    print("CLM-TEST-002  patient is not the subscriber, 4 diagnoses, 3 lines, mixed POS")
    print("CLM-TEST-003  a clean claim, should pass every check")


@transaction.atomic
def remove():
    removed = 0
    for number in TEST_NUMBERS:
        claim = Claim.objects.filter(claim_number=number).first()
        if not claim:
            continue
        patient = claim.patient
        policies = [c.insurance_policy for c in claim.coverages.all()]
        providers = [cp.provider for cp in claim.claim_providers.all()]
        claim.delete()
        for policy in policies:
            if policy.claim_coverages.exists():
                continue
            insured, payer = policy.insured_party, policy.payer
            policy.delete()
            if not insured.insurance_policies.exists():
                insured.delete()
            if not payer.insurance_policies.exists():
                payer.delete()
        for provider in providers:
            if not provider.claim_providers.exists() and not provider.rendered_service_lines.exists():
                provider.delete()
        if not patient.claims.exists():
            patient.delete()
        removed += 1
    print(f"removed {removed} test claim(s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Create or remove fictional test claims.")
    ap.add_argument("--remove", action="store_true", help="delete the test claims again")
    args = ap.parse_args()
    remove() if args.remove else create()
