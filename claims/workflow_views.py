"""Staff-only, database-backed preparation; network transport remains a worker task."""
import hashlib
import re
import tempfile
from decimal import Decimal
from pathlib import Path

from django import forms
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from edi import builders, context, envelope, segments, validators
from edi.management.commands.generate_837p import Command as ExportCommand
from edi.models import ControlNumber, TradingPartner, X12Document
from .models import Claim, ClaimAuditEvent


class GenerateForm(forms.Form):
    partner = forms.ModelChoiceField(
        queryset=TradingPartner.objects.filter(is_active=True),
        label="Receiving partner", empty_label="Select a receiving partner",
    )


def archives_for(claim):
    return X12Document.objects.filter(batch__claims__claim_id=claim.pk).select_related(
        "batch__trading_partner"
    ).order_by("-created_at")


@never_cache
@staff_member_required
@require_http_methods(["GET", "POST"])
def submission(request, claim_id):
    claim = get_object_or_404(Claim, pk=claim_id)
    partners = TradingPartner.objects.filter(is_active=True)
    initial = {"partner": partners.first()} if partners.count() == 1 else {}
    form = GenerateForm(request.POST or None, initial=initial)
    ctx = context.build(claim)
    issues = validators.validate(ctx)
    if request.method == "POST" and form.is_valid():
        # Re-read under a row lock so generation always screens current DB data.
        with transaction.atomic():
            claim = Claim.objects.select_for_update().get(pk=claim.pk)
            ctx = context.build(claim)
            issues = validators.validate(ctx)
            if not issues:
                partner = form.cleaned_data["partner"]
                body, _ = builders.build_body([ctx])
                numbers = tuple(ControlNumber.take(partner, level) for level in (
                    ControlNumber.LEVEL_INTERCHANGE, ControlNumber.LEVEL_GROUP,
                    ControlNumber.LEVEL_TRANSACTION,
                ))
                moment = timezone.now()
                wire = envelope.wrap(body, partner, numbers, moment.strftime("%Y%m%d%H%M%S"), moment)
                text = segments.serialize(wire, line_breaks=True)
                # Vercel's temporary disk is sufficient: the permanent source of
                # truth is X12Document, and download reads that exact archive.
                with tempfile.TemporaryDirectory(prefix="emrts-837-") as folder:
                    filename = f"837p_{partner.usage_indicator}_{numbers[0]:09d}.edi"
                    archived = ExportCommand().write_batch(
                        partner, [ctx], str(Path(folder) / filename), numbers, wire, text,
                    )
                ClaimAuditEvent.objects.create(
                    claim=claim, event_type="x12_generated",
                    event_description=f"837P archived as {archived.pk}; not transmitted.",
                    changed_by=request.user.get_username(),
                )
                return redirect("workflow:document", document_id=archived.pk)
    return render(request, "claims/submission.html", {
        "claim": claim, "form": form, "issues": issues, "archives": archives_for(claim),
        "has_partners": partners.exists(), "billing_provider": ctx.billing,
        "billing_needs_review": any(issue.tag.startswith("2010AA") for issue in issues),
    })


def archived_payload(document):
    payload = document.content.encode("utf-8")
    if len(payload) != document.byte_count or hashlib.sha256(payload).hexdigest() != document.sha256:
        raise ValidationError("Archived file failed its integrity check.")
    return payload


def archive_summary(document):
    """Read the generated 837P itself, never today's mutable claim records.

    BatchClaim records contain identity/position snapshots, not full clinical
    detail. The exact archived file is therefore the source for the table.
    This small reader supports the 005010X222A1 subset produced here; it is not
    a general-purpose X12 validator or a second converter.
    """
    text = document.content
    if len(text) < 106 or not text.startswith("ISA"):
        raise ValueError("The archive is not a supported enveloped 837P.")
    separator, component, terminator = text[3], text[104], text[105]
    if len({separator, component, terminator}) != 3:
        raise ValueError("The archive uses unsupported separators.")
    raw_segments = [chunk.strip("\r\n").split(separator)
                    for chunk in text.split(terminator) if chunk.strip("\r\n")]
    if not raw_segments or raw_segments[-1][0] != "IEA":
        raise ValueError("The archive does not have a complete interchange.")

    def field(parts, number):
        return parts[number] if len(parts) > number else ""

    def name(parts):
        if field(parts, 2) == "2":
            return field(parts, 3)
        return " ".join(value for value in (field(parts, 4), field(parts, 5), field(parts, 3)) if value)

    def money(value):
        if not re.fullmatch(r"-?\d{1,15}(?:\.\d{1,2})?", value):
            raise ValueError("The archive contains an unsupported amount.")
        return format(Decimal(value), ".2f")

    def date(value):
        return f"{value[:4]}-{value[4:6]}-{value[6:]}" if re.fullmatch(r"\d{8}", value) else value

    isa = raw_segments[0]
    if len(isa) != 17:
        raise ValueError("The archive has an unsupported interchange header.")
    usage = field(isa, 15)
    result = {"envelope": {"sender_id": field(isa, 6).rstrip(),
        "receiver_id": field(isa, 8).rstrip(), "usage_indicator": usage,
        "usage_label": {"T": "Test", "P": "Production"}.get(usage, usage),
        "isa_control": field(isa, 13), "implementation": "", "receiver_name": ""},
        "claims": []}
    billing_name = billing_npi = subscriber_name = member_id = payer_name = payer_id = patient_name = ""
    current_claim = current_line = None
    transaction_control = ""
    for parts in raw_segments[1:]:
        tag = parts[0]
        if tag == "ST":
            if field(parts, 1) != "837" or field(parts, 3) != "005010X222A1":
                raise ValueError("The archive is not the supported 005010X222A1 transaction.")
            transaction_control = field(parts, 2)
            result["envelope"]["implementation"] = field(parts, 3)
            billing_name = billing_npi = subscriber_name = member_id = payer_name = payer_id = patient_name = ""
            current_claim = current_line = None
        elif tag == "HL":
            current_claim = current_line = None
            if field(parts, 3) == "20":
                billing_name = billing_npi = subscriber_name = member_id = payer_name = payer_id = patient_name = ""
            elif field(parts, 3) == "22":
                subscriber_name = member_id = payer_name = payer_id = patient_name = ""
            elif field(parts, 3) == "23":
                patient_name = ""
        elif tag == "NM1":
            role = field(parts, 1)
            if role == "85":
                billing_name, billing_npi = name(parts), field(parts, 9)
            elif role == "IL":
                subscriber_name, member_id = name(parts), field(parts, 9)
            elif role == "QC":
                patient_name = name(parts)
            elif role == "PR":
                payer_name, payer_id = name(parts), field(parts, 9)
            elif role == "40":
                result["envelope"]["receiver_name"] = name(parts)
        elif tag == "CLM":
            current_line = None
            current_claim = {"claim_number": field(parts, 1), "total_charge": money(field(parts, 2)),
                "place_of_service": field(parts, 5).split(component)[0],
                "billing_name": billing_name, "billing_npi": billing_npi,
                "subscriber_name": subscriber_name, "member_id": member_id,
                "payer_name": payer_name, "payer_id": payer_id,
                "patient_name": patient_name or subscriber_name,
                "transaction_control": transaction_control, "diagnoses": [], "lines": []}
            result["claims"].append(current_claim)
        elif tag == "HI" and current_claim is not None:
            for value in parts[1:]:
                pieces = value.split(component)
                if len(pieces) < 2 or pieces[0] not in {"ABK", "ABF"}:
                    raise ValueError("The archive contains diagnosis details outside this reader's supported subset.")
                current_claim["diagnoses"].append({"pointer": len(current_claim["diagnoses"]) + 1,
                    "code": pieces[1], "qualifier": pieces[0]})
        elif tag == "LX" and current_claim is not None:
            current_line = {"number": field(parts, 1), "procedure": "", "modifiers": [],
                "charge": "", "units": "", "place_of_service": current_claim["place_of_service"],
                "service_from": "", "service_to": "", "pointers": [], "diagnoses": []}
            current_claim["lines"].append(current_line)
        elif tag == "SV1":
            if current_line is None:
                raise ValueError("A service line in the archive has no line number.")
            procedure = field(parts, 1).split(component)
            if len(procedure) < 2 or len(procedure) > 6 or procedure[0] != "HC":
                raise ValueError("A procedure uses an unsupported representation.")
            pointers = field(parts, 7).split(component)
            if any(not pointer.isdigit() or int(pointer) < 1 for pointer in pointers):
                raise ValueError("A service line has an unsupported diagnosis pointer.")
            current_line.update(procedure=procedure[1], modifiers=procedure[2:],
                charge=money(field(parts, 2)), units=field(parts, 4),
                place_of_service=field(parts, 5) or current_claim["place_of_service"],
                pointers=[int(pointer) for pointer in pointers])
        elif tag == "DTP" and current_line is not None and field(parts, 1) == "472":
            if field(parts, 2) == "D8":
                current_line["service_from"] = current_line["service_to"] = date(field(parts, 3))
            elif field(parts, 2) == "RD8":
                dates = field(parts, 3).split("-")
                if len(dates) != 2:
                    raise ValueError("A service date range is unsupported.")
                current_line["service_from"], current_line["service_to"] = map(date, dates)
    if not result["claims"] or not result["envelope"]["implementation"]:
        raise ValueError("No supported claim records were found in the archive.")
    for claim in result["claims"]:
        diagnoses = {diagnosis["pointer"]: diagnosis for diagnosis in claim["diagnoses"]}
        for line in claim["lines"]:
            if not line["procedure"] or any(pointer not in diagnoses for pointer in line["pointers"]):
                raise ValueError("The archive has an unresolved service-line diagnosis.")
            line["diagnoses"] = [diagnoses[pointer] for pointer in line["pointers"]]
    return result


@never_cache
@staff_member_required
@require_GET
def archive(request):
    documents = X12Document.objects.select_related("batch__trading_partner").order_by("-created_at")
    page = Paginator(documents, 50).get_page(request.GET.get("page"))
    return render(request, "claims/x12_archive.html", {"page": page, "documents": page.object_list})


@never_cache
@staff_member_required
@require_GET
def document(request, document_id):
    archived = get_object_or_404(X12Document.objects.select_related("batch__trading_partner"), pk=document_id)
    try:
        archived_payload(archived)
    except ValidationError:
        return HttpResponse("Archived file integrity check failed; contact the administrator.", status=409)
    summary = None
    summary_error = ""
    try:
        summary = archive_summary(archived)
    except ValueError:
        summary_error = "A readable summary is unavailable for this older archive. Its exact original X12 remains available below and for download."
    return render(request, "claims/x12_document.html", {
        "document": archived, "archive_summary": summary, "summary_error": summary_error,
    })


@never_cache
@staff_member_required
@require_GET
def download(request, document_id):
    archived = get_object_or_404(X12Document.objects.select_related("batch"), pk=document_id)
    try:
        payload = archived_payload(archived)
    except ValidationError:
        return HttpResponse("Archived file integrity check failed; contact the administrator.", status=409)
    # Keep the batch's original generated name while excluding directory parts
    # and control characters. Header encoding is Django's responsibility.
    filename = Path(archived.batch.file_name.replace("\\", "/")).name
    filename = "".join(char for char in filename if char.isprintable()).strip()
    if not filename or filename in {".", ".."}:
        filename = f"837p_{archived.pk}.edi"
    response = HttpResponse(payload, content_type="application/octet-stream")
    response["Content-Disposition"] = content_disposition_header(True, filename)
    response["X-Content-Type-Options"] = "nosniff"
    return response
