import uuid

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import CMS1500CaptureForm
from .models import (
    Claim,
    ClaimAuditEvent,
    ClaimCoverage,
    ClaimDiagnosis,
    ClaimProvider,
    InsurancePolicy,
    InsuredParty,
    Patient,
    Payer,
    Provider,
    ServiceLine,
)


def dashboard(request):
    recent_claims = (
        Claim.objects.select_related("patient")
        .prefetch_related("coverages__insurance_policy__payer")
        .order_by("-created_at")[:10]
    )

    context = {
        "recent_claims": recent_claims,
        "claim_count": Claim.objects.count(),
        "draft_count": Claim.objects.filter(status=Claim.STATUS_DRAFT).count(),
        "ready_for_review_count": Claim.objects.filter(status=Claim.STATUS_READY_FOR_REVIEW).count(),
    }
    return render(request, "claims/dashboard.html", context)


def claim_detail(request, claim_id):
    claim = get_object_or_404(
        Claim.objects.select_related("patient")
        .prefetch_related(
            "coverages__insurance_policy__insured_party",
            "coverages__insurance_policy__payer",
            "claim_providers__provider",
            "diagnoses",
            "service_lines",
            "audit_events",
        ),
        id=claim_id,
    )
    return render(request, "claims/claim_detail.html", {"claim": claim})

def capture_claim(request):
    if request.method == "POST":
        form = CMS1500CaptureForm(request.POST)
        if form.is_valid():
            claim = _save_capture_form(form.cleaned_data)
            messages.success(request, f"Claim {claim.claim_number or claim.id} was captured successfully.")
            return redirect("claims:claim_detail", claim_id=claim.id)
    else:
        form = CMS1500CaptureForm()

    return render(request, "claims/capture_claim.html", {"form": form})


@transaction.atomic
def _save_capture_form(data):
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
        )

    payer = Payer.objects.create(
        payer_name=data["payer_name"],
        payer_type=data["payer_type"],
        payer_identifier=data.get("payer_identifier", ""),
        medicare_administrative_contractor=data.get("medicare_administrative_contractor", ""),
    )

    billing_provider = Provider.objects.create(
        organization_name=data["billing_provider_name"],
        npi=data.get("billing_provider_npi", ""),
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

    claim = Claim.objects.create(
        claim_number=claim_number,
        patient=patient,
        status=Claim.STATUS_READY_FOR_REVIEW,
        validation_status="capture_complete",
        validation_message="Initial CMS-1500 capture completed through the web form.",
        service_start_date=data.get("service_start_date"),
        service_end_date=data.get("service_end_date"),
        total_charge_amount=data.get("charge_amount") or 0,
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

    if data.get("rendering_provider_first_name") or data.get("rendering_provider_last_name") or data.get("rendering_provider_npi"):
        rendering_provider = Provider.objects.create(
            first_name=data.get("rendering_provider_first_name", ""),
            last_name=data.get("rendering_provider_last_name", ""),
            npi=data.get("rendering_provider_npi", ""),
        )
        ClaimProvider.objects.create(
            claim=claim,
            provider=rendering_provider,
            provider_role=ClaimProvider.ROLE_RENDERING,
        )

    for index in range(1, 5):
        code = data.get(f"diagnosis_code_{index}")
        if code:
            ClaimDiagnosis.objects.create(
                claim=claim,
                diagnosis_code=code,
                diagnosis_order=index,
                description=data.get(f"diagnosis_description_{index}", ""),
            )

    ServiceLine.objects.create(
        claim=claim,
        service_from_date=data.get("service_line_from_date"),
        service_to_date=data.get("service_line_to_date"),
        place_of_service=data.get("place_of_service", ""),
        procedure_code=data["procedure_code"],
        modifier_1=data.get("modifier_1", ""),
        modifier_2=data.get("modifier_2", ""),
        modifier_3=data.get("modifier_3", ""),
        modifier_4=data.get("modifier_4", ""),
        diagnosis_pointer_1=data.get("diagnosis_pointer_1"),
        diagnosis_pointer_2=data.get("diagnosis_pointer_2"),
        diagnosis_pointer_3=data.get("diagnosis_pointer_3"),
        diagnosis_pointer_4=data.get("diagnosis_pointer_4"),
        charge_amount=data.get("charge_amount") or 0,
        units=data.get("units") or 1,
    )

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
