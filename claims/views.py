import uuid
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from edi import context as edi_context, validators as edi_validators

from .forms import CMS1500CaptureForm, DiagnosisCaptureFormSet, ServiceLineCaptureFormSet
from .models import (
    Claim,
    ClaimAuditEvent,
    ClaimCoverage,
    ClaimDiagnosis,
    ClaimProvider,
    Icd10Code,
    InsurancePolicy,
    InsuredParty,
    NpiReference,
    Patient,
    Payer,
    ProcedureCode,
    Provider,
    ReferenceDataUpdate,
    ServiceLine,
    ServiceLineDiagnosis,
    ServiceLineModifier,
)


def dashboard(request):
    claims = (
        Claim.objects.select_related("patient")
        .prefetch_related("coverages__insurance_policy__payer")
        .order_by("-created_at", "id")
    )
    query = request.GET.get("q", "").strip()[:150]
    status = request.GET.get("status", "")
    if query:
        claims = claims.filter(Q(claim_number__icontains=query) | Q(patient__first_name__icontains=query) | Q(patient__last_name__icontains=query))
    if status in dict(Claim.STATUS_CHOICES):
        claims = claims.filter(status=status)
    else:
        status = ""
    page = Paginator(claims, 15).get_page(request.GET.get("page"))

    context = {
        "recent_claims": page.object_list,
        "page": page,
        "query": query,
        "status": status,
        "status_choices": Claim.STATUS_CHOICES,
        "claim_count": Claim.objects.count(),
        "draft_count": Claim.objects.filter(status=Claim.STATUS_DRAFT).count(),
        "ready_for_review_count": Claim.objects.filter(status=Claim.STATUS_READY_FOR_REVIEW).count(),
        "reference_data": [
            _reference_summary(
                ReferenceDataUpdate.DATASET_NPPES,
                "NPPES / NPI",
                NpiReference.objects.filter(is_active=True).count(),
            ),
            _reference_summary(
                ReferenceDataUpdate.DATASET_ICD10,
                "ICD-10-CM",
                Icd10Code.objects.filter(is_active=True).count(),
            ),
            _reference_summary(
                ReferenceDataUpdate.DATASET_PROCEDURE,
                "CPT / HCPCS",
                ProcedureCode.objects.filter(is_active=True).count(),
            ),
        ],
    }
    return render(request, "claims/dashboard.html", context)


def _reference_summary(dataset_name, label, active_count):
    latest_update = (
        ReferenceDataUpdate.objects.filter(
            dataset_name=dataset_name,
            status=ReferenceDataUpdate.STATUS_COMPLETED,
        )
        .order_by("-completed_at", "-created_at")
        .first()
    )
    return {
        "label": label,
        "active_count": active_count,
        "latest_update": latest_update,
    }


def claim_detail(request, claim_id):
    claim = get_object_or_404(
        Claim.objects.select_related("patient")
        .prefetch_related(
            "coverages__insurance_policy__insured_party",
            "coverages__insurance_policy__payer",
            "claim_providers__provider__npi_reference",
            "diagnoses__icd10_reference",
            "service_lines__procedure_reference",
            "service_lines__rendering_provider",
            "service_lines__diagnosis_links__diagnosis",
            "service_lines__modifiers",
            "audit_events",
        ),
        id=claim_id,
    )
    return render(request, "claims/claim_detail.html", {
        "claim": claim,
        "edi_issues": edi_validators.validate(edi_context.build(claim)),
    })


def capture_claim(request):
    data = request.POST if request.method == "POST" else None
    form = CMS1500CaptureForm(data)
    diagnosis_formset = DiagnosisCaptureFormSet(data, prefix="diagnoses")
    diagnosis_choices = []
    if data is not None:
        diagnoses_valid = diagnosis_formset.is_valid()
        for index, diagnosis_form in enumerate(diagnosis_formset):
            cleaned = diagnosis_form.cleaned_data
            if cleaned.get("diagnosis_code") and not cleaned.get("DELETE"):
                code = cleaned["diagnosis_code"]
                reference = Icd10Code.objects.filter(code=code).first()
                description = cleaned.get("description") or (reference.short_description if reference else "")
                diagnosis_choices.append((str(index), f"{code} — {description}" if description else code))
    service_line_formset = ServiceLineCaptureFormSet(
        data, prefix="service_lines", form_kwargs={"diagnosis_choices": diagnosis_choices},
    )
    if data is not None:
        form_valid = form.is_valid()
        lines_valid = service_line_formset.is_valid()
        if form_valid and diagnoses_valid and lines_valid:
            diagnoses = [
                {**f.cleaned_data, "row_key": str(index)}
                for index, f in enumerate(diagnosis_formset)
                if f.cleaned_data and not f.cleaned_data.get("DELETE")
            ]
            lines = [f.cleaned_data for f in service_line_formset if f.cleaned_data and not f.cleaned_data.get("DELETE")]
            claim = _save_capture_form(form.cleaned_data, lines, diagnoses)
            messages.success(request, f"Claim {claim.claim_number or claim.id} was captured successfully.")
            return redirect("claims:claim_detail", claim_id=claim.id)
    return render(request, "claims/capture_claim.html", {
        "form": form, "diagnosis_formset": diagnosis_formset,
        "service_line_formset": service_line_formset,
        "capture_has_errors": data is not None,
    })


@transaction.atomic
def _save_capture_form(data, service_line_data, diagnosis_data):
    patient = Patient.objects.create(
        first_name=data["patient_first_name"],
        middle_name=data.get("patient_middle_name", ""),
        last_name=data["patient_last_name"],
        date_of_birth=data.get("patient_date_of_birth"),
        sex=data.get("patient_sex", ""),
        address_line_1=data.get("patient_address_line_1", ""),
        address_line_2=data.get("patient_address_line_2", ""),
        city=data.get("patient_city", ""),
        state=data.get("patient_state", ""),
        zip_code=data.get("patient_zip_code", ""),
        phone_number=data.get("patient_phone_number", ""),
    )

    if data.get("insured_same_as_patient"):
        insured_party = InsuredParty.objects.create(
            first_name=patient.first_name,
            middle_name=patient.middle_name,
            last_name=patient.last_name,
            date_of_birth=patient.date_of_birth,
            sex=patient.sex,
            address_line_1=patient.address_line_1,
            address_line_2=patient.address_line_2,
            city=patient.city,
            state=patient.state,
            zip_code=patient.zip_code,
        )
    else:
        insured_party = InsuredParty.objects.create(
            first_name=data.get("insured_first_name", ""),
            middle_name=data.get("insured_middle_name", ""),
            last_name=data.get("insured_last_name", ""),
            date_of_birth=data.get("insured_date_of_birth"),
            sex=data.get("insured_sex", ""),
            address_line_1=data.get("insured_address_line_1", ""),
            address_line_2=data.get("insured_address_line_2", ""),
            city=data.get("insured_city", ""),
            state=data.get("insured_state", ""),
            zip_code=data.get("insured_zip_code", ""),
        )

    payer = Payer.objects.create(
        payer_name=data["payer_name"],
        payer_type=data["payer_type"],
        payer_identifier=data.get("payer_identifier", ""),
        medicare_administrative_contractor=data.get("medicare_administrative_contractor", ""),
        address_line_1=data["payer_address_line_1"],
        address_line_2=data.get("payer_address_line_2", ""),
        city=data["payer_city"],
        state=data["payer_state"],
        zip_code=data["payer_zip_code"],
        zip_code_extension=data.get("payer_zip_code_extension", ""),
    )

    billing_npi = data.get("billing_provider_npi", "")
    billing_provider = Provider.objects.create(
        organization_name=data["billing_provider_name"],
        npi=billing_npi,
        npi_reference=NpiReference.objects.filter(npi=billing_npi, is_active=True).first(),
        taxonomy_code=data.get("billing_provider_taxonomy_code", ""),
        tax_id=data.get("billing_provider_tax_id", ""),
        address_line_1=data.get("billing_provider_address_line_1", ""),
        city=data.get("billing_provider_city", ""),
        state=data.get("billing_provider_state", ""),
        zip_code=data.get("billing_provider_zip_code", ""),
    )

    claim_number = data.get("claim_number") or _generate_claim_number()

    insurance_policy = InsurancePolicy.objects.create(
        insured_party=insured_party,
        payer=payer,
        member_id=data.get("insured_id_number", ""),
        group_number=data.get("group_number", ""),
        plan_name=data.get("plan_name", ""),
        policy_type=data.get("policy_type") or data.get("payer_type") or InsurancePolicy.POLICY_TYPE_MEDICARE,
    )

    total_charge_amount = sum(
        (line.get("charge_amount") or Decimal("0.00") for line in service_line_data),
        Decimal("0.00"),
    )

    claim = Claim.objects.create(
        claim_number=claim_number,
        patient=patient,
        status=Claim.STATUS_READY_FOR_REVIEW,
        validation_status="reference_validated",
        validation_message=(
            "CMS-1500 capture completed. Supplied NPI, ICD-10-CM, and procedure codes "
            "matched active reference records."
        ),
        service_start_date=data.get("service_start_date"),
        service_end_date=data.get("service_end_date"),
        total_charge_amount=total_charge_amount,
    )

    ClaimCoverage.objects.create(
        claim=claim,
        insurance_policy=insurance_policy,
        payer_sequence=data.get("payer_sequence") or ClaimCoverage.PAYER_SEQUENCE_PRIMARY,
        relationship_to_patient=data.get("relationship_to_patient") or ("self" if data.get("insured_same_as_patient") else ""),
        assignment_of_benefits=data.get("assignment_of_benefits", False),
        release_of_information=data.get("release_of_information", False),
        prior_authorization_number=data.get("prior_authorization_number", ""),
    )

    ClaimProvider.objects.create(
        claim=claim,
        provider=billing_provider,
        provider_role=ClaimProvider.ROLE_BILLING,
    )

    rendering_provider = None
    if data.get("rendering_provider_first_name") or data.get("rendering_provider_last_name") or data.get("rendering_provider_npi"):
        rendering_npi = data.get("rendering_provider_npi", "")
        rendering_provider = Provider.objects.create(
            first_name=data.get("rendering_provider_first_name", ""),
            last_name=data.get("rendering_provider_last_name", ""),
            npi=rendering_npi,
            npi_reference=NpiReference.objects.filter(npi=rendering_npi, is_active=True).first(),
        )
        ClaimProvider.objects.create(
            claim=claim,
            provider=rendering_provider,
            provider_role=ClaimProvider.ROLE_RENDERING,
        )

    diagnoses_by_key = {}
    for index, diagnosis in enumerate(diagnosis_data, start=1):
        code = diagnosis["diagnosis_code"]
        reference = Icd10Code.objects.filter(code=code, is_active=True).first()
        diagnoses_by_key[diagnosis["row_key"]] = ClaimDiagnosis.objects.create(
            claim=claim, diagnosis_code=code, icd10_reference=reference,
            diagnosis_order=index,
            description=diagnosis.get("description") or (reference.short_description if reference else ""),
        )

    for line in service_line_data:
        procedure_code = line["procedure_code"]
        service_line = ServiceLine.objects.create(
            claim=claim,
            service_from_date=line.get("service_line_from_date"),
            service_to_date=line.get("service_line_to_date"),
            place_of_service=line.get("place_of_service", ""),
            procedure_code=procedure_code,
            procedure_reference=ProcedureCode.objects.filter(code=procedure_code, is_active=True).first(),
            rendering_provider=rendering_provider,
            charge_amount=line.get("charge_amount") or 0,
            units=line.get("units") or 1,
        )

        for position, row_key in enumerate(line["diagnosis_refs"], start=1):
            ServiceLineDiagnosis.objects.create(service_line=service_line, diagnosis=diagnoses_by_key[row_key], position=position)
        for position, code in enumerate(line["modifier_codes"], start=1):
            ServiceLineModifier.objects.create(service_line=service_line, code=code, position=position)

    ClaimAuditEvent.objects.create(
        claim=claim,
        event_type="capture_created",
        event_description="Claim was created from the CMS-1500 capture form.",
        changed_by="system",
    )

    return claim


def _generate_claim_number():
    date_part = timezone.now().strftime("%Y%m%d")
    random_part = uuid.uuid4().hex[:8].upper()
    return f"CLM-{date_part}-{random_part}"
