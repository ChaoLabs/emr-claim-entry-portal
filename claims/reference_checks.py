"""Advisory local-reference checks; absence from a subset is not an input error."""

from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db.models import Q, Value
from django.db.models.functions import Replace, Upper

from .code_validation import normalize_diagnosis, normalize_npi, normalize_procedure
from .models import Icd10Code, NpiReference, ProcedureCode


def find_diagnosis_reference(code):
    """Link an existing active reference in either ICD notation, without creating one."""
    normalized = normalize_diagnosis(code)
    return Icd10Code.objects.filter(
        Q(code__iexact=normalized) | Q(code__iexact=normalized.replace(".", "")),
        is_active=True,
    ).order_by("code").first()


def _dates(start, end, fallback):
    return {value for value in (start, end) if value is not None} or fallback


def reference_report(claim):
    """Describe current local matches, independently of capture and export eligibility.

    Reference tables can be incomplete or stale. No records are created or changed,
    and no unmatched value is replaced. A local match does not certify a code's
    billability, an NPI's credentials, or payer acceptance.
    """
    warnings = []
    entries = {"Diagnosis": defaultdict(set), "Procedure": defaultdict(set), "NPI": defaultdict(set)}
    normalizers = {
        "Diagnosis": normalize_diagnosis,
        "Procedure": normalize_procedure,
        "NPI": normalize_npi,
    }
    claim_dates = _dates(claim.service_start_date, claim.service_end_date, set())
    lines = list(claim.service_lines.select_related("rendering_provider").prefetch_related("diagnosis_links"))
    all_dates = set(claim_dates)
    diagnosis_dates = defaultdict(set)

    def add(kind, value, service_dates):
        if not value:
            return
        try:
            code = normalizers[kind](value)
        except ValidationError:
            warnings.append(f"{kind} {value}: its format needs correction before export.")
        else:
            entries[kind][code].update(service_dates)

    for line in lines:
        dates = _dates(line.service_from_date, line.service_to_date, claim_dates)
        all_dates.update(dates)
        add("Procedure", line.procedure_code, dates)
        if line.rendering_provider_id:
            add("NPI", line.rendering_provider.npi, dates)
        for link in line.diagnosis_links.all():
            diagnosis_dates[link.diagnosis_id].update(dates)

    for diagnosis in claim.diagnoses.all():
        add("Diagnosis", diagnosis.diagnosis_code, diagnosis_dates[diagnosis.pk] or all_dates)
    for association in claim.claim_providers.select_related("provider"):
        add("NPI", association.provider.npi, all_dates)

    # Batch queries also recognize case and dotted/undotted references imported by
    # an administrator. Neither a nullable FK nor its presence proves verification.
    references = {kind: defaultdict(list) for kind in entries}
    diagnosis_keys = [code.replace(".", "") for code in entries["Diagnosis"]]
    diagnosis_records = Icd10Code.objects.annotate(
        lookup_code=Upper(Replace("code", Value("."), Value("")))
    ).filter(lookup_code__in=diagnosis_keys)
    for reference in diagnosis_records:
        try:
            normalized = normalize_diagnosis(reference.code)
        except ValidationError:
            # A malformed imported row must not crash review or certify a code
            # merely because stripping its punctuation produces the same key.
            continue
        references["Diagnosis"][normalized].append(reference)
    procedure_records = ProcedureCode.objects.annotate(lookup_code=Upper("code")).filter(
        lookup_code__in=entries["Procedure"]
    )
    for reference in procedure_records:
        references["Procedure"][reference.code.upper()].append(reference)
    for reference in NpiReference.objects.filter(npi__in=entries["NPI"]):
        references["NPI"][reference.npi].append(reference)

    for kind, codes in entries.items():
        for code, dates in codes.items():
            matches = references[kind][code]
            label = f"{kind} {code}"
            if not matches:
                warnings.append(f"{label}: not verified against local reference data (not in this subset).")
                continue
            active = [record for record in matches if record.is_active]
            if not active:
                warnings.append(
                    f"{label}: the local reference is marked inactive; review its applicability to the service dates."
                )
                continue
            if not dates and any(_has_dates(record, kind) for record in active):
                warnings.append(
                    f"{label}: service dates are unavailable; review the dates recorded in the local reference."
                )
                continue
            if dates and not any(_covers_dates(record, dates, kind) for record in active):
                warnings.append(
                    f"{label}: service dates fall outside the dates recorded in the local reference; review the applicable version."
                )

    not_checked = not warnings and not any(entries.values())
    if not_checked:
        warnings.append("No supplied codes have been checked against local reference data.")
    warnings = list(dict.fromkeys(warnings))
    if warnings:
        message = (
            "Local reference review is incomplete. Missing or inactive local records "
            "do not prevent submission or generation; separate format and export errors must still be corrected. "
            + " ".join(warnings)
        )
    else:
        message = (
            "Supplied codes matched local reference records. A local match does not "
            "establish billability, provider credentials, or payer acceptance."
        )
    return {
        "reference_warnings": warnings,
        "reference_status_label": (
            "Not checked" if not_checked else "Reference review needed" if warnings else "Local references matched"
        ),
        "validation_status": "reference_pending" if warnings else "reference_validated",
        "validation_message": message,
    }


def _has_dates(reference, kind):
    if kind == "NPI":
        return bool(reference.enumeration_date or reference.deactivation_date)
    return bool(reference.effective_start_date or reference.effective_end_date)


def _covers_dates(reference, dates, kind):
    if kind == "NPI":
        return all(
            (not reference.enumeration_date or date >= reference.enumeration_date)
            and (not reference.deactivation_date or date < reference.deactivation_date)
            for date in dates
        )
    return all(
        (not reference.effective_start_date or date >= reference.effective_start_date)
        and (not reference.effective_end_date or date <= reference.effective_end_date)
        for date in dates
    )
