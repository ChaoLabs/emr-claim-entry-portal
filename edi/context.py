from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from . import codes, formatters

ROLE_BILLING = "billing"
ROLE_RENDERING = "rendering"


@dataclass
class ClaimContext:
    claim: object
    coverage: object = None
    policy: object = None
    insured: object = None
    payer: object = None
    billing: object = None
    rendering: object = None
    sbr02: str = ""
    sbr02_source: str = ""
    place_of_service: str = ""
    place_varies: bool = False
    diagnoses: list = field(default_factory=list)
    service_lines: list = field(default_factory=list)
    fatal: list = field(default_factory=list)

    @property
    def is_usable(self):
        return not self.fatal

    @property
    def patient_is_subscriber(self):
        return self.sbr02 == codes.RELATIONSHIP_SELF

    @property
    def diagnosis_orders(self):
        return {d.diagnosis_order for d in self.diagnoses}

    @property
    def line_total(self):
        return sum((ln.charge_amount or Decimal("0")) for ln in self.service_lines)

    def diagnosis_pairs(self):
        out = []
        for index, dx in enumerate(self.diagnoses):
            qualifier = codes.DIAGNOSIS_PRINCIPAL if index == 0 else codes.DIAGNOSIS_OTHER
            out.append((qualifier, formatters.diagnosis(dx.diagnosis_code)))
        return out

    def line_place_of_service(self, line):
        value = line.place_of_service or ""
        return value if (self.place_varies and value != self.place_of_service) else ""


def _relationship(claim, insured, coverage):
    # An explicit relationship wins over a coincidental demographic match.
    stated = (coverage.relationship_to_patient or "").strip().lower()
    if stated:
        return codes.RELATIONSHIP.get(stated, ""), "stated relationship"
    patient = claim.patient
    same = (
        formatters.clean(patient.first_name) == formatters.clean(insured.first_name)
        and formatters.clean(patient.last_name) == formatters.clean(insured.last_name)
        and patient.date_of_birth == insured.date_of_birth
        and formatters.clean(patient.sex) == formatters.clean(insured.sex)
    )
    if same:
        return codes.RELATIONSHIP_SELF, "record comparison"

    return "", "not stated"


def _place_of_service(lines):
    values = [ln.place_of_service for ln in lines if ln.place_of_service]
    if not values:
        return "", False
    ranked = sorted(set(values), key=lambda v: (-values.count(v), v))
    return ranked[0], len(set(values)) > 1


def build(claim):
    context = ClaimContext(claim=claim)

    context.service_lines = list(claim.service_lines.all())
    context.diagnoses = list(claim.diagnoses.all().order_by("diagnosis_order"))

    coverages = list(claim.coverages.all())
    if not coverages:
        context.fatal.append("the claim has no coverage attached")
        return context
    # The imported converter has no 2320/2330 COB implementation. Do not
    # silently discard secondary coverage or select a policy alphabetically.
    if len(coverages) != 1 or coverages[0].payer_sequence != "primary":
        context.fatal.append("this prototype exports one primary coverage only; COB is not implemented")
        return context
    coverage = coverages[0]

    context.coverage = coverage
    context.policy = coverage.insurance_policy
    context.insured = context.policy.insured_party
    context.payer = context.policy.payer

    for claim_provider in claim.claim_providers.all():
        if claim_provider.provider_role == ROLE_BILLING:
            if context.billing is not None:
                context.fatal.append("the claim has more than one billing provider")
            context.billing = claim_provider.provider
        elif claim_provider.provider_role == ROLE_RENDERING:
            if context.rendering is not None:
                context.fatal.append("the claim has more than one claim-level rendering provider")
            context.rendering = claim_provider.provider

    if context.billing is None:
        context.fatal.append("the claim has no billing provider")

    context.sbr02, context.sbr02_source = _relationship(claim, context.insured, coverage)
    context.place_of_service, context.place_varies = _place_of_service(context.service_lines)
    return context


def build_many(claims):
    return [build(claim) for claim in claims]
