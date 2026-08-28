from django import forms

from .models import (
    Claim,
    Icd10Code,
    NpiReference,
    PAYER_STATE_CODE_VALIDATOR,
    PAYER_ZIP_CODE_EXTENSION_VALIDATOR,
    PAYER_ZIP_CODE_VALIDATOR,
    ProcedureCode,
)


class ServiceLineCaptureForm(forms.Form):
    """One repeatable CMS-1500 service line in the claim capture workflow."""

    service_line_from_date = forms.DateField(
        label="Service Line From Date",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    service_line_to_date = forms.DateField(
        label="Service Line To Date",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    place_of_service = forms.CharField(label="Place of Service", max_length=10, required=False)
    procedure_code = forms.CharField(
        label="Procedure Code / CPT / HCPCS",
        max_length=20,
        help_text="Validated against the active CPT / HCPCS reference subset.",
    )
    modifier_1 = forms.CharField(label="Modifier 1", max_length=10, required=False)
    modifier_2 = forms.CharField(label="Modifier 2", max_length=10, required=False)
    modifier_3 = forms.CharField(label="Modifier 3", max_length=10, required=False)
    modifier_4 = forms.CharField(label="Modifier 4", max_length=10, required=False)
    diagnosis_pointer_1 = forms.IntegerField(label="Diagnosis Pointer 1", required=False, min_value=1, max_value=4)
    diagnosis_pointer_2 = forms.IntegerField(label="Diagnosis Pointer 2", required=False, min_value=1, max_value=4)
    diagnosis_pointer_3 = forms.IntegerField(label="Diagnosis Pointer 3", required=False, min_value=1, max_value=4)
    diagnosis_pointer_4 = forms.IntegerField(label="Diagnosis Pointer 4", required=False, min_value=1, max_value=4)
    charge_amount = forms.DecimalField(label="Charge Amount", max_digits=12, decimal_places=2, min_value=0)
    units = forms.IntegerField(label="Units", min_value=1, initial=1)

    def __init__(self, *args, valid_diagnosis_orders=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.valid_diagnosis_orders = set(valid_diagnosis_orders or [])

    def clean(self):
        cleaned_data = super().clean()

        line_from_date = cleaned_data.get("service_line_from_date")
        line_to_date = cleaned_data.get("service_line_to_date")
        if line_from_date and line_to_date and line_to_date < line_from_date:
            raise forms.ValidationError("Service line end date cannot be before service line start date.")

        procedure_code = (cleaned_data.get("procedure_code") or "").strip().upper()
        cleaned_data["procedure_code"] = procedure_code
        if procedure_code and not ProcedureCode.objects.filter(code=procedure_code, is_active=True).exists():
            self.add_error(
                "procedure_code",
                "Procedure code was not found in the active CPT / HCPCS reference data.",
            )

        for index in range(1, 5):
            field_name = f"diagnosis_pointer_{index}"
            pointer = cleaned_data.get(field_name)
            if pointer and pointer not in self.valid_diagnosis_orders:
                self.add_error(
                    field_name,
                    "Diagnosis pointer must reference an entered diagnosis code.",
                )

        return cleaned_data


ServiceLineCaptureFormSet = forms.formset_factory(
    ServiceLineCaptureForm,
    extra=0,
    can_delete=True,
    min_num=1,
    validate_min=True,
)


class CMS1500CaptureForm(forms.Form):
    """Claim-level portion of the CMS-1500 capture workflow.

    Repeatable line-level information is handled by ``ServiceLineCaptureFormSet``.
    """

    # Patient information
    patient_first_name = forms.CharField(label="Patient First Name", max_length=100)
    patient_middle_name = forms.CharField(label="Patient Middle Name", max_length=100, required=False)
    patient_last_name = forms.CharField(label="Patient Last Name", max_length=100)
    patient_date_of_birth = forms.DateField(
        label="Patient Date of Birth",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    patient_sex = forms.ChoiceField(
        label="Patient Sex",
        required=False,
        choices=[
            ("", "---------"),
            ("female", "Female"),
            ("male", "Male"),
            ("other", "Other"),
            ("unknown", "Unknown"),
        ],
    )
    patient_address_line_1 = forms.CharField(label="Patient Address Line 1", max_length=255, required=False)
    patient_address_line_2 = forms.CharField(label="Patient Address Line 2", max_length=255, required=False)
    patient_city = forms.CharField(label="Patient City", max_length=100, required=False)
    patient_state = forms.CharField(label="Patient State", max_length=2, required=False)
    patient_zip_code = forms.CharField(label="Patient ZIP Code", max_length=20, required=False)
    patient_phone_number = forms.CharField(label="Patient Phone Number", max_length=30, required=False)

    # Insured / subscriber information
    insured_same_as_patient = forms.BooleanField(label="Insured is the patient", required=False)
    insured_first_name = forms.CharField(label="Insured First Name", max_length=100, required=False)
    insured_middle_name = forms.CharField(label="Insured Middle Name", max_length=100, required=False)
    insured_last_name = forms.CharField(label="Insured Last Name", max_length=100, required=False)
    insured_date_of_birth = forms.DateField(
        label="Insured Date of Birth",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    insured_sex = forms.ChoiceField(
        label="Insured Sex",
        required=False,
        choices=[
            ("", "---------"),
            ("female", "Female"),
            ("male", "Male"),
            ("other", "Other"),
            ("unknown", "Unknown"),
        ],
    )
    # Coverage / policy information
    relationship_to_patient = forms.CharField(label="Relationship to Patient", max_length=50, required=False)
    insured_id_number = forms.CharField(label="Member / Insured ID Number", max_length=100, required=False)
    group_number = forms.CharField(label="Group Number", max_length=100, required=False)
    plan_name = forms.CharField(label="Plan Name", max_length=255, required=False)
    policy_type = forms.ChoiceField(
        label="Policy Type",
        choices=[
            ("medicare", "Medicare"),
            ("medicaid", "Medicaid"),
            ("commercial", "Commercial"),
            ("tricare", "TRICARE"),
            ("other", "Other"),
        ],
        initial="medicare",
        required=False,
    )
    payer_sequence = forms.ChoiceField(
        label="Payer Sequence",
        choices=[
            ("primary", "Primary"),
            ("secondary", "Secondary"),
            ("tertiary", "Tertiary"),
            ("other", "Other"),
        ],
        initial="primary",
        required=False,
    )
    assignment_of_benefits = forms.BooleanField(label="Assignment of Benefits", required=False, initial=True)
    release_of_information = forms.BooleanField(label="Release of Information", required=False, initial=True)
    prior_authorization_number = forms.CharField(label="Prior Authorization Number", max_length=100, required=False)

    # Payer information
    payer_name = forms.CharField(label="Payer Name", max_length=255, initial="Medicare")
    payer_type = forms.ChoiceField(
        label="Payer Type",
        choices=[
            ("medicare", "Medicare"),
            ("medicaid", "Medicaid"),
            ("commercial", "Commercial"),
            ("other", "Other"),
        ],
        initial="medicare",
    )
    payer_identifier = forms.CharField(label="Payer Identifier", max_length=100, required=False)
    medicare_administrative_contractor = forms.CharField(
        label="Medicare Administrative Contractor",
        max_length=255,
        required=False,
    )
    payer_address_line_1 = forms.CharField(label="Payer Address Line 1", max_length=255)
    payer_address_line_2 = forms.CharField(
        label="Payer Address Line 2",
        max_length=255,
        required=False,
    )
    payer_city = forms.CharField(label="Payer City", max_length=100)
    payer_state = forms.CharField(
        label="Payer State",
        max_length=2,
        validators=[PAYER_STATE_CODE_VALIDATOR],
    )
    payer_zip_code = forms.CharField(
        label="Payer ZIP Code (5 digits)",
        min_length=5,
        max_length=5,
        validators=[PAYER_ZIP_CODE_VALIDATOR],
        widget=forms.TextInput(attrs={"inputmode": "numeric"}),
    )
    payer_zip_code_extension = forms.CharField(
        label="Payer ZIP+4 Extension (4 digits)",
        min_length=4,
        max_length=4,
        required=False,
        validators=[PAYER_ZIP_CODE_EXTENSION_VALIDATOR],
        widget=forms.TextInput(attrs={"inputmode": "numeric"}),
    )

    # Provider information
    billing_provider_name = forms.CharField(label="Billing Provider / Organization Name", max_length=255)
    billing_provider_npi = forms.CharField(
        label="Billing Provider NPI",
        max_length=20,
        required=False,
        help_text="If entered, the NPI must match an active NPI reference record.",
    )
    billing_provider_taxonomy_code = forms.CharField(
        label="Billing Provider Taxonomy Code",
        max_length=20,
        required=False,
    )
    billing_provider_tax_id = forms.CharField(label="Billing Provider Tax ID", max_length=50, required=False)
    billing_provider_address_line_1 = forms.CharField(
        label="Billing Provider Address Line 1",
        max_length=255,
        required=False,
    )
    billing_provider_city = forms.CharField(label="Billing Provider City", max_length=100, required=False)
    billing_provider_state = forms.CharField(label="Billing Provider State", max_length=2, required=False)
    billing_provider_zip_code = forms.CharField(label="Billing Provider ZIP Code", max_length=20, required=False)

    rendering_provider_first_name = forms.CharField(
        label="Rendering Provider First Name",
        max_length=100,
        required=False,
    )
    rendering_provider_last_name = forms.CharField(
        label="Rendering Provider Last Name",
        max_length=100,
        required=False,
    )
    rendering_provider_npi = forms.CharField(
        label="Rendering Provider NPI",
        max_length=20,
        required=False,
        help_text="If entered, the NPI must match an active NPI reference record.",
    )

    # Claim header
    claim_number = forms.CharField(label="Claim Number", max_length=100, required=False)
    service_start_date = forms.DateField(
        label="Service Start Date",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    service_end_date = forms.DateField(
        label="Service End Date",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    # Diagnosis information
    diagnosis_code_1 = forms.CharField(
        label="Diagnosis Code 1",
        max_length=20,
        help_text="Validated against the active ICD-10-CM reference subset.",
    )
    diagnosis_description_1 = forms.CharField(label="Diagnosis Description 1", max_length=255, required=False)
    diagnosis_code_2 = forms.CharField(label="Diagnosis Code 2", max_length=20, required=False)
    diagnosis_description_2 = forms.CharField(label="Diagnosis Description 2", max_length=255, required=False)
    diagnosis_code_3 = forms.CharField(label="Diagnosis Code 3", max_length=20, required=False)
    diagnosis_description_3 = forms.CharField(label="Diagnosis Description 3", max_length=255, required=False)
    diagnosis_code_4 = forms.CharField(label="Diagnosis Code 4", max_length=20, required=False)
    diagnosis_description_4 = forms.CharField(label="Diagnosis Description 4", max_length=255, required=False)

    def clean_claim_number(self):
        claim_number = self.cleaned_data["claim_number"].strip()
        if claim_number and Claim.objects.filter(claim_number=claim_number).exists():
            raise forms.ValidationError("A claim with this claim number already exists.")
        return claim_number

    def clean_payer_state(self):
        return self.cleaned_data["payer_state"].upper()

    def clean(self):
        cleaned_data = super().clean()

        insured_same_as_patient = cleaned_data.get("insured_same_as_patient")
        insured_first_name = cleaned_data.get("insured_first_name")
        insured_last_name = cleaned_data.get("insured_last_name")

        if not insured_same_as_patient and not (insured_first_name and insured_last_name):
            raise forms.ValidationError(
                "Enter insured first and last name, or select 'Insured is the patient'."
            )

        service_start_date = cleaned_data.get("service_start_date")
        service_end_date = cleaned_data.get("service_end_date")
        if service_start_date and service_end_date and service_end_date < service_start_date:
            raise forms.ValidationError("Service end date cannot be before service start date.")

        for field_name in ("billing_provider_npi", "rendering_provider_npi"):
            npi = (cleaned_data.get(field_name) or "").strip()
            cleaned_data[field_name] = npi
            if not npi:
                continue
            if len(npi) != 10 or not npi.isdigit():
                self.add_error(field_name, "NPI must contain exactly 10 digits.")
                continue
            if not NpiReference.objects.filter(npi=npi, is_active=True).exists():
                self.add_error(field_name, "NPI was not found in the active reference data.")

        for index in range(1, 5):
            field_name = f"diagnosis_code_{index}"
            code = (cleaned_data.get(field_name) or "").strip().upper()
            cleaned_data[field_name] = code
            if not code:
                continue
            if not Icd10Code.objects.filter(code=code, is_active=True).exists():
                self.add_error(field_name, "Diagnosis code was not found in the active ICD-10-CM reference data.")

        return cleaned_data
