from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from . import codes, formatters

BILLING_ZIP_DIGITS = 9
NPI_DIGITS = 10
PAYER_ZIP_DIGITS = (5, 9)


@dataclass(frozen=True)
class Issue:
    tag: str
    message: str
    line: Optional[int] = None

    def __str__(self):
        where = f" line {self.line}" if self.line else ""
        return f"[{self.tag}{where}] {self.message}"

    def matches(self, prefix):
        return self.tag.startswith(prefix.strip().strip("[]"))


def _payer_postal_code(payer):
    base = formatters.digits(payer.zip_code)
    extension = formatters.digits(getattr(payer, "zip_code_extension", ""))
    return f"{base}{extension}" if base else ""


def validate_billing_provider(billing):
    if billing is None:
        return [Issue("2010AA", "no billing provider on the claim")]

    out = []
    zip_code = formatters.digits(billing.zip_code)
    if len(zip_code) != BILLING_ZIP_DIGITS:
        out.append(Issue(
            "2010AA N403",
            f"billing ZIP '{billing.zip_code}' has {len(zip_code)} digits, "
            f"{BILLING_ZIP_DIGITS} required",
        ))

    npi = formatters.digits(billing.npi)
    if len(npi) != NPI_DIGITS:
        out.append(Issue("2010AA NM109", f"billing NPI '{billing.npi}' is not {NPI_DIGITS} digits"))

    if len(formatters.digits(billing.tax_id)) != 9:
        out.append(Issue("2010AA REF EI", "billing tax id must contain 9 digits"))

    if not formatters.clean(billing.address_line_1):
        out.append(Issue("2010AA N301", "billing street address is empty"))
    if not formatters.clean(billing.city):
        out.append(Issue("2010AA N401", "billing city is empty"))
    if not formatters.clean(billing.state):
        out.append(Issue("2010AA N402", "billing state is empty"))
    return out


def validate_payer(payer):
    out = []
    if not formatters.clean(payer.payer_identifier):
        out.append(Issue("2010BB NM109", "payer identifier is empty"))

    if not formatters.clean(payer.address_line_1):
        out.append(Issue("2010BB N301", "payer street address is empty"))
    if not formatters.clean(payer.city):
        out.append(Issue("2010BB N401", "payer city is empty"))
    if not formatters.clean(payer.state):
        out.append(Issue("2010BB N402", "payer state is empty"))

    postal = _payer_postal_code(payer)
    if not postal:
        out.append(Issue("2010BB N403", "payer ZIP is empty"))
    elif len(postal) not in PAYER_ZIP_DIGITS:
        out.append(Issue(
            "2010BB N403",
            f"payer ZIP '{postal}' has {len(postal)} digits, 5 or 9 required",
        ))
    return out


def validate_subscriber(context):
    out = []
    if not context.sbr02:
        out.append(Issue("2000B SBR02",
                         f"relationship to patient could not be mapped, {context.sbr02_source}"))
    if not formatters.clean(context.policy.member_id):
        out.append(Issue("2010BA NM109", "member id is empty, required in 5010"))
    if not context.insured.date_of_birth:
        out.append(Issue("2010BA DMG02", "subscriber date of birth is missing"))
    insured = context.insured
    if not all(formatters.clean(v) for v in (insured.address_line_1, insured.city, insured.state)):
        out.append(Issue("2010BA N3/N4", "subscriber street, city and state are required"))
    if len(formatters.digits(insured.zip_code)) not in (5, 9):
        out.append(Issue("2010BA N403", "subscriber ZIP must have 5 or 9 digits"))
    return out


def validate_diagnoses(context):
    out = []
    if not context.diagnoses:
        out.append(Issue("2300 HI", "the claim has no diagnosis code"))
    elif len(context.diagnoses) > 12:
        out.append(Issue("2300 HI", "this exporter supports at most 12 diagnoses"))

    seen = [formatters.diagnosis(dx.diagnosis_code) for dx in context.diagnoses]
    for code in sorted({c for c in seen if seen.count(c) > 1}):
        out.append(Issue("2300 HI", f"diagnosis code {code} appears more than once"))

    orders = sorted(context.diagnosis_orders)
    if orders and orders != list(range(1, len(orders) + 1)):
        out.append(Issue("2300 HI", f"diagnosis order is not 1..n, found {orders}"))
    return out


def validate_totals(context):
    declared = Decimal(context.claim.total_charge_amount or 0)
    summed = context.line_total
    if declared != summed:
        return [Issue(
            "2300 CLM02",
            f"claim total {formatters.amount(declared)} does not equal "
            f"the line total {formatters.amount(summed)}",
        )]
    return []


def validate_service_line(context, line, number):
    out = []
    if not formatters.clean(line.procedure_code):
        out.append(Issue("2400 SV101", "service line has no procedure code", number))

    if line.charge_amount is None:
        out.append(Issue("2400 SV102", "service line has no charge amount", number))
    elif line.charge_amount < 0:
        out.append(Issue("2400 SV102", "service line charge cannot be negative", number))
    if line.units is None or line.units <= 0:
        out.append(Issue("2400 SV104", "service line units must be positive", number))

    if not line.service_from_date:
        out.append(Issue("2400 DTP472", "service line has no service date", number))
    elif line.service_to_date and line.service_to_date < line.service_from_date:
        out.append(Issue("2400 DTP472", "service end date is before the start date", number))

    pointers = [line.diagnosis_pointer_1, line.diagnosis_pointer_2,
                line.diagnosis_pointer_3, line.diagnosis_pointer_4]
    if not any(pointers):
        out.append(Issue("2400 SV107", "service line has no diagnosis pointer", number))
    for index, pointer in enumerate(pointers, start=1):
        if pointer and pointer not in context.diagnosis_orders:
            out.append(Issue("2400 SV107", f"pointer {index} points at diagnosis {pointer}, "
                                           f"which the claim does not have", number))
    return out


def validate(context):
    if not context.is_usable:
        return [Issue("2300", reason) for reason in context.fatal]

    out = []
    number = formatters.clean(context.claim.claim_number)
    if not number or len(number) > 38:
        out.append(Issue("2300 CLM01", "claim number must be 1 to 38 characters"))
    out.extend(validate_billing_provider(context.billing))
    out.extend(validate_payer(context.payer))
    out.extend(validate_subscriber(context))
    out.extend(validate_diagnoses(context))
    out.extend(validate_totals(context))

    if not context.service_lines:
        out.append(Issue("2400", "the claim has no service line"))
    for number, line in enumerate(context.service_lines, start=1):
        out.extend(validate_service_line(context, line, number))
    return out


def filter_issues(issues, ignore=()):
    if not ignore:
        return list(issues)
    return [i for i in issues if not any(i.matches(prefix) for prefix in ignore)]


def summarise(issues):
    counts = {}
    for issue in issues:
        counts[issue.tag] = counts.get(issue.tag, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
