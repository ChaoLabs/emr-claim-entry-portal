from . import codes, context as ctx, formatters
from .segments import Composite, HLCounter, Segment


def _identifier(qualifier, value):
    cleaned = formatters.clean(value)
    return (qualifier, cleaned) if cleaned else ("", "")


def _address(street, street_2, city, state, postal):
    out = []
    if formatters.clean(street):
        out.append(Segment("N3", street, street_2))
    if any(formatters.clean(v) for v in (city, state, postal)):
        out.append(Segment("N4", city, state, postal))
    return out


def _person_or_org(provider):
    if (provider.organization_name or "").strip():
        return codes.ENTITY_ORGANISATION, provider.organization_name, ""
    return codes.ENTITY_PERSON, provider.last_name, provider.first_name


def payer_postal_code(payer):
    base = formatters.digits(payer.zip_code)
    extension = formatters.digits(getattr(payer, "zip_code_extension", ""))
    return f"{base}{extension}" if base else ""


def billing_provider_loop(provider, hl_id):
    out = [Segment("HL", str(hl_id), "", codes.HL_BILLING_PROVIDER, "1")]

    if (provider.taxonomy_code or "").strip():
        out.append(Segment("PRV", "BI", codes.QUALIFIER_TAXONOMY, provider.taxonomy_code))

    entity, last, first = _person_or_org(provider)
    out.append(Segment("NM1", "85", entity, last, first, "", "", "",
                       *_identifier(codes.QUALIFIER_NPI, formatters.digits(provider.npi))))
    out.extend(_address(provider.address_line_1, provider.address_line_2,
                        provider.city, provider.state,
                        formatters.digits(provider.zip_code)))
    tax_id = formatters.digits(provider.tax_id)
    if tax_id:
        out.append(Segment("REF", codes.QUALIFIER_EIN, tax_id))
    return out


def subscriber_loop(coverage, policy, insured, payer, sbr02, hl_id, parent_id, has_dependent):
    out = [Segment("HL", str(hl_id), str(parent_id), codes.HL_SUBSCRIBER,
                   "1" if has_dependent else "0")]

    out.append(Segment(
        "SBR",
        codes.PAYER_SEQUENCE.get(coverage.payer_sequence, ""),
        codes.RELATIONSHIP_SELF if sbr02 == codes.RELATIONSHIP_SELF else "",
        policy.group_number,
        "" if policy.group_number else policy.plan_name,
        "", "", "", "",
        codes.FILING_INDICATOR.get(payer.payer_type, "ZZ"),
    ))

    out.append(Segment("NM1", "IL", codes.ENTITY_PERSON, insured.last_name,
                       insured.first_name, insured.middle_name, "", "",
                       *_identifier(codes.QUALIFIER_MEMBER_ID, policy.member_id)))
    out.extend(_address(insured.address_line_1, insured.address_line_2,
                        insured.city, insured.state,
                        formatters.digits(insured.zip_code)))
    out.append(Segment("DMG", "D8", formatters.d8(insured.date_of_birth),
                       codes.SEX.get((insured.sex or "").lower(), "U")))

    out.append(Segment("NM1", "PR", codes.ENTITY_ORGANISATION, payer.payer_name,
                       "", "", "", "",
                       *_identifier(codes.QUALIFIER_PAYER_ID, payer.payer_identifier)))
    out.extend(_address(payer.address_line_1, payer.address_line_2,
                        payer.city, payer.state, payer_postal_code(payer)))
    return out


def patient_loop(patient, hl_id, parent_id, sbr02):
    out = [Segment("HL", str(hl_id), str(parent_id), codes.HL_DEPENDENT, "0")]
    out.append(Segment("PAT", sbr02))
    out.append(Segment("NM1", "QC", codes.ENTITY_PERSON, patient.last_name,
                       patient.first_name, patient.middle_name))
    out.extend(_address(patient.address_line_1, patient.address_line_2,
                        patient.city, patient.state,
                        formatters.digits(patient.zip_code)))
    out.append(Segment("DMG", "D8", formatters.d8(patient.date_of_birth),
                       codes.SEX.get((patient.sex or "").lower(), "U")))
    return out


def claim_loop(context):
    out = [Segment(
        "CLM",
        context.claim.claim_number,
        formatters.amount(context.claim.total_charge_amount),
        "", "",
        Composite(context.place_of_service, codes.FACILITY_CODE_QUALIFIER,
                  codes.CLAIM_FREQUENCY_ORIGINAL),
        "Y",
        "A",
        "Y" if context.coverage.assignment_of_benefits else "N",
        "Y" if context.coverage.release_of_information else "I",
    )]

    pairs = context.diagnosis_pairs()
    if pairs:
        out.append(Segment("HI", *[Composite(q, c) for q, c in pairs]))

    if formatters.clean(context.coverage.prior_authorization_number):
        out.append(Segment("REF", "G1", context.coverage.prior_authorization_number))

    rendering = context.rendering
    if rendering:
        entity, last, first = _person_or_org(rendering)
        out.append(Segment("NM1", "82", entity, last, first, "", "", "",
                           *_identifier(codes.QUALIFIER_NPI, formatters.digits(rendering.npi))))
        if formatters.clean(rendering.taxonomy_code):
            out.append(Segment("PRV", "PE", codes.QUALIFIER_TAXONOMY, rendering.taxonomy_code))
    return out


def service_line_loop(context, line, number):
    procedure = [codes.QUALIFIER_PROCEDURE, line.procedure_code]
    for modifier in (line.modifier_1, line.modifier_2, line.modifier_3, line.modifier_4):
        if modifier and modifier.strip():
            procedure.append(modifier)

    pointers = [line.diagnosis_pointer_1, line.diagnosis_pointer_2,
                line.diagnosis_pointer_3, line.diagnosis_pointer_4]

    out = [
        Segment("LX", str(number)),
        Segment(
            "SV1",
            Composite(*procedure),
            formatters.amount(line.charge_amount),
            codes.UNIT_BASIS_UNITS,
            str(line.units),
            context.line_place_of_service(line),
            "",
            Composite(*[str(p) for p in pointers if p]),
        ),
    ]

    span = formatters.rd8(line.service_from_date, line.service_to_date)
    if span:
        out.append(Segment("DTP", "472", "RD8", span))
    else:
        out.append(Segment("DTP", "472", "D8", formatters.d8(line.service_from_date)))

    renderer = line.rendering_provider
    if renderer and renderer != context.rendering:
        entity, last, first = _person_or_org(renderer)
        out.append(Segment("NM1", "82", entity, last, first, "", "", "",
                           *_identifier(codes.QUALIFIER_NPI, formatters.digits(renderer.npi))))
    return out


def claim_segments(context):
    out = claim_loop(context)
    for number, line in enumerate(context.service_lines, start=1):
        out.extend(service_line_loop(context, line, number))
    return out


def build_body(contexts, counter=None):
    counter = counter or HLCounter()
    usable = [c for c in contexts if c.is_usable]

    out = []
    by_billing = {}
    for context in usable:
        by_billing.setdefault(context.billing.id, []).append(context)

    for group in by_billing.values():
        billing_hl = counter.take()
        out.extend(billing_provider_loop(group[0].billing, billing_hl))

        by_subscriber = {}
        for context in group:
            key = (context.insured.id, context.payer.id, context.policy.id,
                   context.coverage.payer_sequence, context.patient_is_subscriber)
            by_subscriber.setdefault(key, []).append(context)

        for subscriber_group in by_subscriber.values():
            first = subscriber_group[0]
            dependents = [c for c in subscriber_group if not c.patient_is_subscriber]
            subscriber_hl = counter.take(billing_hl)
            out.extend(subscriber_loop(
                first.coverage, first.policy, first.insured, first.payer,
                first.sbr02, subscriber_hl, billing_hl, has_dependent=bool(dependents),
            ))

            for context in subscriber_group:
                if context.patient_is_subscriber:
                    out.extend(claim_segments(context))

            for context in dependents:
                patient_hl = counter.take(subscriber_hl)
                out.extend(patient_loop(context.claim.patient, patient_hl,
                                        subscriber_hl, context.sbr02))
                out.extend(claim_segments(context))

    return out, counter


def build_from_claims(claims, counter=None):
    return build_body(ctx.build_many(claims), counter)
