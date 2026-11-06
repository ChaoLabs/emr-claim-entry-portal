import re

from django import forms
from django.utils.html import format_html, format_html_join

from .models import (
    Claim,
    Icd10Code,
    NpiReference,
    PAYER_STATE_CODE_VALIDATOR,
    PAYER_ZIP_CODE_EXTENSION_VALIDATOR,
    PAYER_ZIP_CODE_VALIDATOR,
    ProcedureCode,
)


class RepeatedValueWidget(forms.Widget):
    """Repeated successful controls; values retain their submitted order."""
    def __init__(self, kind, choices=(), attrs=None):
        super().__init__(attrs)
        self.kind, self.choices = kind, list(choices)

    def value_from_datadict(self, data, files, name):
        return data.getlist(name) if hasattr(data, "getlist") else data.get(name, [])

    def render(self, name, value, attrs=None, renderer=None):
        values = value if isinstance(value, (list, tuple)) else ([value] if value else [])
        attrs = {**self.attrs, **(attrs or {})}
        element_id = attrs.get("id", name)
        rows = []
        for index, item in enumerate(values or [""]):
            item = str(item)
            row_id = f"{element_id}_{index}"
            if self.kind == "diagnosis":
                choices = [("", "Choose a diagnosis…"), *self.choices]
                if item and item not in {str(key) for key, _ in choices}:
                    choices.append((item, "Unavailable diagnosis — select again"))
                options = format_html_join("", '<option value="{}"{}>{}</option>', (
                    (key, format_html(' selected') if str(key) == item else "", label)
                    for key, label in choices
                ))
                control = format_html('<select name="{}" id="{}" data-diagnosis-select aria-label="Diagnosis {}">{}</select>', name, row_id, index + 1, options)
            else:
                control = format_html('<input name="{}" id="{}" value="{}" maxlength="2" placeholder="e.g. 25" autocomplete="off" aria-label="Modifier {}">', name, row_id, item, index + 1)
            rows.append(format_html('<div class="repeated-row" data-value-row>{}<button type="button" class="text-button" data-remove-value aria-label="Remove {} {}">Remove</button></div>', control, self.kind, index + 1))
        return format_html('<div class="repeated-field" id="{}" data-repeat="{}" data-field-name="{}"><div data-values>{}</div><button type="button" class="text-button" data-add-value>Add {}</button></div>', element_id, self.kind, name, format_html_join("", "{}", ((row,) for row in rows)), self.kind)


class OrderedValuesField(forms.Field):
    def to_python(self, value):
        if value is None:
            return []
        if not isinstance(value, (list, tuple)):
            raise forms.ValidationError("Submit each value separately.")
        if len(value) > 200:
            raise forms.ValidationError("This request contains too many values. Save a smaller claim.")
        return [str(item).strip() for item in value if str(item).strip()]


class DiagnosisCaptureForm(forms.Form):
    diagnosis_code = forms.CharField(label="Diagnosis code", max_length=20)
    description = forms.CharField(label="Description (optional)", max_length=255, required=False)

    def clean_diagnosis_code(self):
        code = self.cleaned_data["diagnosis_code"].strip().upper()
        if not Icd10Code.objects.filter(code=code, is_active=True).exists():
            raise forms.ValidationError("Diagnosis code was not found in the active ICD-10-CM reference data.")
        return code


class BaseDiagnosisFormSet(forms.BaseFormSet):
    def clean(self):
        super().clean()
        seen = set()
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            code = form.cleaned_data.get("diagnosis_code")
            if code and code in seen:
                form.add_error("diagnosis_code", "This diagnosis is already on the claim. Select it on multiple service lines instead.")
            seen.add(code)


DiagnosisCaptureFormSet = forms.formset_factory(
    DiagnosisCaptureForm, formset=BaseDiagnosisFormSet, extra=0,
    can_delete=True, min_num=1, validate_min=True, max_num=200, absolute_max=200, validate_max=True,
)


class ServiceLineCaptureForm(forms.Form):
    """One service line, with ordered references to this request's diagnosis rows."""
    service_line_from_date = forms.DateField(label="From date", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    service_line_to_date = forms.DateField(label="To date", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    place_of_service = forms.CharField(label="Place of service", max_length=10, required=False)
    procedure_code = forms.CharField(label="Procedure code / CPT / HCPCS", max_length=20)
    diagnosis_refs = OrderedValuesField(label="Related diagnoses", widget=RepeatedValueWidget("diagnosis"))
    modifier_codes = OrderedValuesField(label="Modifiers (optional)", required=False, widget=RepeatedValueWidget("modifier"))
    charge_amount = forms.DecimalField(label="Charge amount", max_digits=12, decimal_places=2, min_value=0)
    units = forms.IntegerField(label="Units", min_value=1, initial=1)

    def __init__(self, *args, diagnosis_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.valid_diagnosis_refs = {str(key) for key, _ in diagnosis_choices}
        self.fields["diagnosis_refs"].widget.choices = list(diagnosis_choices)

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("service_line_from_date"), cleaned.get("service_line_to_date")
        if start and end and end < start:
            self.add_error("service_line_to_date", "Service line end date cannot be before service line start date.")
        code = (cleaned.get("procedure_code") or "").strip().upper()
        cleaned["procedure_code"] = code
        if code and not ProcedureCode.objects.filter(code=code, is_active=True).exists():
            self.add_error("procedure_code", "Procedure code was not found in the active CPT / HCPCS reference data.")
        refs = cleaned.get("diagnosis_refs", [])
        if any(ref not in self.valid_diagnosis_refs for ref in refs):
            self.add_error("diagnosis_refs", "Select a diagnosis entered on this claim. A selected diagnosis may have been removed or needs correction.")
        elif len(refs) != len(set(refs)):
            self.add_error("diagnosis_refs", "Select each diagnosis only once for this service line.")
        modifiers = [value.upper() for value in cleaned.get("modifier_codes", [])]
        cleaned["modifier_codes"] = modifiers
        if any(not re.fullmatch(r"[A-Z0-9]{2}", value) for value in modifiers):
            self.add_error("modifier_codes", "Each modifier must contain two letters or digits.")
        elif len(modifiers) != len(set(modifiers)):
            self.add_error("modifier_codes", "Enter each modifier only once for this service line.")
        return cleaned


ServiceLineCaptureFormSet = forms.formset_factory(
    ServiceLineCaptureForm, extra=0, can_delete=True, min_num=1, validate_min=True,
    max_num=200, absolute_max=200, validate_max=True,
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
    insured_address_line_1 = forms.CharField(label="Subscriber Address Line 1", max_length=255, required=False)
    insured_address_line_2 = forms.CharField(label="Subscriber Address Line 2", max_length=255, required=False)
    insured_city = forms.CharField(label="Subscriber City", max_length=100, required=False)
    insured_state = forms.CharField(label="Subscriber State", max_length=2, required=False)
    insured_zip_code = forms.CharField(
        label="Subscriber ZIP Code", max_length=20, required=False,
        help_text="5 digits or ZIP+4, for example 27701 or 27701-1234.",
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
    claim_number = forms.CharField(label="Claim Number", max_length=60, required=False)
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

        if not insured_same_as_patient:
            for field_name in ("insured_date_of_birth", "insured_address_line_1", "insured_city", "insured_state", "insured_zip_code"):
                if not cleaned_data.get(field_name):
                    self.add_error(field_name, "Required when the subscriber is someone other than the patient.")
            state = cleaned_data.get("insured_state", "").upper()
            if state and not re.fullmatch(r"[A-Z]{2}", state):
                self.add_error("insured_state", "State must be a two-letter code.")
            elif state:
                cleaned_data["insured_state"] = state
            postal = cleaned_data.get("insured_zip_code", "")
            if postal and not re.fullmatch(r"(?:[0-9]{5}|[0-9]{9}|[0-9]{5}-[0-9]{4})", postal):
                self.add_error("insured_zip_code", "Enter a 5-digit ZIP or a 9-digit ZIP+4.")

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

        return cleaned_data
