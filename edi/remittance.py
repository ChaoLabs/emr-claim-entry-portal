"""Bounded 5010 835 reader. Archive first-class evidence; never infer adjudication.

This reads envelope controls, BPR/TRN, CLP, SVC, CAS, and REF*6R. It is not
an X12 implementation-guide validator. Uninterpreted segments remain in the
exact archive, and no bank details, patient names, or raw X12 are logged.
"""
import hashlib
import re
from decimal import Decimal
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.db import transaction

from claims.models import Claim
from .models import BatchClaim, RemittanceClaim, RemittanceDocument

MAX_835_BYTES = 2 * 1024 * 1024
MAX_SEGMENTS = 25000
AMOUNT = re.compile(r"^-?\d{1,15}(?:\.\d{1,2})?$")


def invalid(message):
    raise ValidationError(message)


def amount(value, label, optional=False):
    if optional and not value:
        return None
    if not AMOUNT.fullmatch(value):
        invalid(f"{label} must be a plain decimal amount with at most two decimal places.")
    return format(Decimal(value), ".2f")


def field(parts, index, label, maximum=255, required=True):
    value = parts[index] if len(parts) > index else ""
    if (required and not value) or len(value) > maximum:
        invalid(f"{label} is missing or too long.")
    return value


def adjustment(parts):
    if len(parts) < 4 or len(parts) > 20 or not parts[1] or len(parts[1]) > 2:
        invalid("CAS adjustment is incomplete.")
    rows = []
    remaining = parts[2:]
    for index in range(0, len(remaining), 3):
        triple = remaining[index:index + 3]
        if not any(triple):
            continue
        if len(triple) < 2 or not triple[0] or len(triple[0]) > 5:
            invalid("CAS reason and amount are required together.")
        quantity = triple[2] if len(triple) > 2 else ""
        if quantity and not re.fullmatch(r"-?\d{1,15}(?:\.\d{1,6})?", quantity):
            invalid("CAS quantity is not a decimal number.")
        rows.append({"group": parts[1], "reason": triple[0],
                     "amount": amount(triple[1], "CAS adjustment"), "quantity": quantity})
    return rows


def parse_835(payload):
    if not isinstance(payload, bytes) or not payload or len(payload) > MAX_835_BYTES:
        invalid("Choose a nonempty 835 file no larger than 2 MB.")
    try:
        content = payload.decode("ascii")
    except UnicodeDecodeError:
        invalid("This viewer accepts ASCII X12 files only; the file was not imported.")
    if any((ord(c) < 32 and c not in "\r\n") or ord(c) == 127 for c in content):
        invalid("The file contains unsupported control characters.")
    if not content.startswith("ISA") or len(content) < 106:
        invalid("The file must start with a complete fixed-width ISA envelope.")
    sep, component, end = content[3], content[104], content[105]
    if len({sep, component, end}) != 3 or any(c.isalnum() or c.isspace() for c in (sep, component, end)):
        invalid("The X12 delimiters are invalid.")
    isa = content[:105].split(sep)
    widths = [3, 2, 10, 2, 10, 2, 15, 2, 15, 6, 4, 1, 5, 9, 1, 1, 1]
    if len(isa) != len(widths) or any(len(v) != n for v, n in zip(isa, widths)):
        invalid("The ISA envelope does not have the required fixed-width fields.")
    if isa[12] != "00501":
        invalid("This viewer supports 5010 835 envelopes only.")
    chunks = content.split(end)
    if chunks[-1].strip():
        invalid("The final X12 segment is not terminated.")
    segments = [chunk.strip("\r\n").split(sep) for chunk in chunks[:-1]]
    if not segments or len(segments) > MAX_SEGMENTS or any(not s[0] for s in segments):
        invalid("The file contains an empty segment or exceeds the viewer segment limit.")
    claims, transactions, group, current, current_claim, current_service = [], [], None, None, None, None
    group_count = 0
    group_controls = set()
    closed = False
    unshown = set()
    has_plb = False
    for number, parts in enumerate(segments):
        tag = parts[0]
        if number == 0:
            continue
        if closed:
            invalid("Only one complete interchange is supported per uploaded file.")
        if tag == "GS":
            if group or current or len(parts) < 9 or parts[1] != "HP" or parts[8] not in {"005010X221", "005010X221A1"}:
                invalid("Expected an HP 005010X221A1 payment/advice group.")
            if not parts[6] or parts[6] in group_controls:
                invalid("Group control numbers must be present and unique within the interchange.")
            group_controls.add(parts[6])
            group = {"control": parts[6], "count": 0, "transactions": set()}
            group_count += 1
        elif tag == "ST":
            if group is None or current or len(parts) < 3 or parts[1] != "835":
                invalid("Only 835 transaction sets can be imported here.")
            if not parts[2] or parts[2] in group["transactions"]:
                invalid("Transaction control numbers must be present and unique within a group.")
            if len(parts) > 3 and parts[3] not in {"005010X221", "005010X221A1"}:
                invalid("This viewer supports only the 5010 835 implementation.")
            group["transactions"].add(parts[2])
            current = {"control": parts[2], "group_control": group["control"],
                       "index": len(transactions) + 1, "start": number, "payment_amount": None,
                       "payment_method": "", "payment_date": "", "trace": "", "trace_seen": False}
            current_claim = current_service = None
        elif tag == "SE":
            if current is None or len(parts) != 3 or parts[2] != current["control"] or parts[1] != str(number - current["start"] + 1):
                invalid("A transaction is incomplete: SE count or control number does not match ST.")
            if current["payment_amount"] is None:
                invalid("The 835 transaction is missing its BPR payment information.")
            current.pop("start")
            current.pop("trace_seen")
            transactions.append(current)
            group["count"] += 1
            current = current_claim = current_service = None
        elif tag == "GE":
            if group is None or current or len(parts) != 3 or parts[2] != group["control"] or parts[1] != str(group["count"]) or not group["count"]:
                invalid("The GE group count or control number does not match.")
            group = None
        elif tag == "IEA":
            if group or current or len(parts) != 3 or parts[2] != isa[13] or parts[1] != str(group_count) or not group_count:
                invalid("The interchange is incomplete: IEA count or control number does not match.")
            closed = True
        elif current is None:
            invalid("A data segment appears outside an 835 transaction.")
        elif tag == "BPR":
            if current["payment_amount"] is not None:
                invalid("An 835 transaction contains duplicate BPR payment information.")
            current["payment_amount"] = amount(field(parts, 2, "BPR payment"), "BPR payment")
            current["payment_method"] = field(parts, 4, "BPR method", 3)
            current["payment_date"] = field(parts, 16, "BPR date", 8, False)
        elif tag == "TRN":
            if current["trace_seen"]:
                invalid("Duplicate TRN trace information requires sender review.")
            current["trace_seen"] = True
            current["trace"] = field(parts, 2, "TRN trace")
        elif tag == "LX":
            current_claim = current_service = None
        elif tag == "CLP":
            current_claim = {"claim_number": field(parts, 1, "CLP claim number"),
                "status_code": field(parts, 2, "CLP status", 2),
                "charge_amount": amount(field(parts, 3, "CLP charge"), "CLP charge"),
                "paid_amount": amount(field(parts, 4, "CLP payment"), "CLP payment"),
                "patient_responsibility": amount(field(parts, 5, "CLP patient responsibility", required=False), "CLP patient responsibility", True),
                "payer_control_number": field(parts, 7, "CLP payer control", required=False),
                "details": {"transaction_control": current["control"], "group_control": current["group_control"],
                            "transaction_index": current["index"], "adjustments": [], "services": [], "remarks": []}}
            claims.append(current_claim)
            current_service = None
            if len(claims) > 10000:
                invalid("This viewer accepts at most 10,000 claim results per file.")
        elif tag == "SVC":
            if current_claim is None:
                invalid("SVC service payment has no preceding claim.")
            current_service = {"procedure": field(parts, 1, "SVC procedure"),
                "charge": amount(field(parts, 2, "SVC charge"), "SVC charge"),
                "paid": amount(field(parts, 3, "SVC payment"), "SVC payment"),
                "line_reference": "", "adjustments": [], "remarks": []}
            current_claim["details"]["services"].append(current_service)
        elif tag == "CAS":
            if current_claim is None:
                invalid("CAS adjustment has no preceding claim.")
            target = current_service if current_service is not None else current_claim["details"]
            target["adjustments"].extend(adjustment(parts))
        elif tag == "REF" and len(parts) > 2 and parts[1] == "6R" and current_service is not None:
            current_service["line_reference"] = parts[2]
        elif tag == "LQ" and current_claim is not None:
            target = current_service if current_service is not None else current_claim["details"]
            target["remarks"].append(" / ".join(parts[1:]))
        elif tag == "PLB":
            has_plb = True
            current_service = current_claim = None
        else:
            unshown.add(tag)
    if not closed or current or group or not transactions:
        invalid("The file is incomplete; no records were imported.")
    notes = ["Summary only: original X12 contains additional payment, payer, payee and remark information. No clinical, financial balancing or payer acceptance validation is performed."]
    if has_plb:
        notes.append("Provider-level adjustments (PLB) are present. Review the original file; claim payments alone do not represent the net payment.")
    return content, {"transactions": transactions, "notes": notes,
                     "uninterpreted_segments": sorted(unshown), "claim_count": len(claims)}, claims


@transaction.atomic
def import_835(payload, *, source_name, imported_by, batch=None):
    content, summary, claim_rows = parse_835(payload)
    digest = hashlib.sha256(payload).hexdigest()
    existing = RemittanceDocument.objects.filter(sha256=digest).first()
    if existing:
        existing.verify_integrity()
        if existing.content != content or (batch and existing.batch_id != batch.pk):
            invalid("This response is already archived with different submission metadata.")
        return existing, False
    numbers = {row["claim_number"] for row in claim_rows}
    # Exported CLM01 values are historical identifiers. Never attach a response
    # to a different current claim merely because someone reused an old number.
    identities = {number: set() for number in numbers}
    snapshots = BatchClaim.objects.filter(claim_number__in=numbers)
    if batch:
        snapshots = snapshots.filter(batch=batch)
    for number, claim_id in snapshots.values_list("claim_number", "claim_id"):
        identities[number].add(claim_id)
    current_matches = list(Claim.objects.filter(claim_number__in=numbers))
    if not batch:
        for claim in current_matches:
            identities[claim.claim_number].add(claim.pk)
    all_ids = set().union(*identities.values()) if identities else set()
    live_claims = Claim.objects.in_bulk(all_ids)
    candidates = {number: live_claims[next(iter(ids))] for number, ids in identities.items()
                  if len(ids) == 1 and next(iter(ids)) in live_claims}
    if batch and (not claim_rows or any(row["claim_number"] not in candidates for row in claim_rows)):
        invalid("Every returned claim number must uniquely match its original submission batch snapshot.")
    # get_or_create makes concurrent retry uploads converge on the unique digest.
    doc, created = RemittanceDocument.objects.get_or_create(sha256=digest, defaults={
        "content": content, "byte_count": len(payload),
        "source_name": PurePosixPath(str(source_name).replace("\\", "/")).name[:255],
        "imported_by": str(imported_by)[:150], "batch": batch, "summary": summary})
    if not created:
        doc.verify_integrity()
        if doc.content != content or (batch and doc.batch_id != batch.pk):
            invalid("This response is already archived with different submission metadata.")
        return doc, False
    for position, row in enumerate(claim_rows, 1):
        RemittanceClaim.objects.create(document=doc, position=position,
            claim=candidates.get(row["claim_number"]), **row)
    return doc, True
