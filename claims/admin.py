from django.contrib import admin

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
)


class ClaimCoverageInline(admin.TabularInline):
    model = ClaimCoverage
    extra = 0


class ClaimProviderInline(admin.TabularInline):
    model = ClaimProvider
    extra = 0


class ClaimDiagnosisInline(admin.TabularInline):
    model = ClaimDiagnosis
    extra = 0


class ServiceLineInline(admin.TabularInline):
    model = ServiceLine
    extra = 0


class ClaimAuditEventInline(admin.TabularInline):
    model = ClaimAuditEvent
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(Claim)
class ClaimAdmin(admin.ModelAdmin):
    list_display = (
        "claim_number",
        "patient",
        "primary_payer",
        "status",
        "validation_status",
        "service_start_date",
        "created_at",
    )
    list_filter = ("status", "validation_status", "service_start_date", "created_at")
    search_fields = (
        "claim_number",
        "patient__first_name",
        "patient__last_name",
        "coverages__insurance_policy__payer__payer_name",
        "coverages__insurance_policy__member_id",
        "coverages__insurance_policy__group_number",
    )
    ordering = ("-created_at",)
    inlines = [
        ClaimCoverageInline,
        ClaimProviderInline,
        ClaimDiagnosisInline,
        ServiceLineInline,
        ClaimAuditEventInline,
    ]

    @admin.display(description="Primary Payer")
    def primary_payer(self, obj):
        coverage = (
            obj.coverages.select_related("insurance_policy__payer")
            .filter(payer_sequence=ClaimCoverage.PAYER_SEQUENCE_PRIMARY)
            .first()
        )
        if not coverage:
            return "-"
        return coverage.insurance_policy.payer.payer_name


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "date_of_birth", "sex", "city", "state")
    search_fields = ("first_name", "last_name", "city", "state", "zip_code")
    list_filter = ("sex", "state")
    ordering = ("last_name", "first_name")


@admin.register(InsuredParty)
class InsuredPartyAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "date_of_birth", "sex", "city", "state")
    search_fields = ("first_name", "last_name", "city", "state", "zip_code")
    list_filter = ("sex", "state")
    ordering = ("last_name", "first_name")


@admin.register(Payer)
class PayerAdmin(admin.ModelAdmin):
    list_display = (
        "payer_name",
        "payer_type",
        "payer_identifier",
        "city",
        "state",
        "medicare_administrative_contractor",
    )
    search_fields = (
        "payer_name",
        "payer_identifier",
        "medicare_administrative_contractor",
        "address_line_1",
        "address_line_2",
        "city",
        "state",
        "zip_code",
        "zip_code_extension",
    )
    list_filter = ("payer_type", "state")
    ordering = ("payer_name",)


@admin.register(InsurancePolicy)
class InsurancePolicyAdmin(admin.ModelAdmin):
    list_display = (
        "insured_party",
        "payer",
        "member_id",
        "group_number",
        "plan_name",
        "policy_type",
        "is_active",
    )
    search_fields = (
        "insured_party__first_name",
        "insured_party__last_name",
        "payer__payer_name",
        "member_id",
        "group_number",
        "plan_name",
    )
    list_filter = ("policy_type", "is_active", "payer")
    ordering = ("insured_party", "payer", "member_id")


@admin.register(ClaimCoverage)
class ClaimCoverageAdmin(admin.ModelAdmin):
    list_display = (
        "claim",
        "payer_sequence",
        "insurance_policy",
        "relationship_to_patient",
        "assignment_of_benefits",
        "release_of_information",
    )
    search_fields = (
        "claim__claim_number",
        "insurance_policy__payer__payer_name",
        "insurance_policy__member_id",
        "insurance_policy__group_number",
    )
    list_filter = ("payer_sequence", "assignment_of_benefits", "release_of_information")
    ordering = ("claim", "payer_sequence")


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    list_display = (
        "organization_name",
        "last_name",
        "first_name",
        "npi",
        "npi_reference",
        "taxonomy_code",
        "city",
        "state",
    )
    search_fields = (
        "organization_name",
        "first_name",
        "last_name",
        "npi",
        "npi_reference__provider_name",
        "taxonomy_code",
    )
    list_filter = ("state",)
    ordering = ("organization_name", "last_name", "first_name")


@admin.register(ClaimProvider)
class ClaimProviderAdmin(admin.ModelAdmin):
    list_display = ("claim", "provider_role", "provider")
    search_fields = ("claim__claim_number", "provider__organization_name", "provider__npi")
    list_filter = ("provider_role",)


@admin.register(ClaimDiagnosis)
class ClaimDiagnosisAdmin(admin.ModelAdmin):
    list_display = ("claim", "diagnosis_order", "diagnosis_code", "icd10_reference", "description")
    search_fields = (
        "claim__claim_number",
        "diagnosis_code",
        "icd10_reference__short_description",
        "description",
    )
    ordering = ("claim", "diagnosis_order")


@admin.register(ServiceLine)
class ServiceLineAdmin(admin.ModelAdmin):
    list_display = (
        "claim",
        "service_from_date",
        "service_to_date",
        "procedure_code",
        "procedure_reference",
        "rendering_provider",
        "charge_amount",
        "units",
    )
    search_fields = (
        "claim__claim_number",
        "procedure_code",
        "procedure_reference__short_description",
        "rendering_provider__organization_name",
        "rendering_provider__first_name",
        "rendering_provider__last_name",
    )
    ordering = ("claim", "service_from_date")


@admin.register(ClaimAuditEvent)
class ClaimAuditEventAdmin(admin.ModelAdmin):
    list_display = ("claim", "event_type", "changed_by", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("claim__claim_number", "event_type", "event_description", "changed_by")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)


@admin.register(ReferenceDataUpdate)
class ReferenceDataUpdateAdmin(admin.ModelAdmin):
    list_display = (
        "dataset_name",
        "source_name",
        "source_version",
        "status",
        "records_loaded",
        "completed_at",
    )
    list_filter = ("dataset_name", "status")
    search_fields = ("source_name", "source_version", "notes")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-completed_at", "-created_at")


@admin.register(NpiReference)
class NpiReferenceAdmin(admin.ModelAdmin):
    list_display = (
        "npi",
        "provider_name",
        "entity_type",
        "primary_taxonomy_code",
        "city",
        "state",
        "is_active",
        "source_last_updated_date",
    )
    list_filter = ("entity_type", "is_active", "state")
    search_fields = ("npi", "provider_name", "primary_taxonomy_code", "city", "state")
    ordering = ("provider_name", "npi")


@admin.register(Icd10Code)
class Icd10CodeAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "short_description",
        "effective_start_date",
        "effective_end_date",
        "is_active",
    )
    list_filter = ("is_active",)
    search_fields = ("code", "short_description", "long_description")
    ordering = ("code",)


@admin.register(ProcedureCode)
class ProcedureCodeAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "code_system",
        "short_description",
        "effective_start_date",
        "effective_end_date",
        "is_active",
    )
    list_filter = ("code_system", "is_active")
    search_fields = ("code", "short_description", "long_description")
    ordering = ("code_system", "code")
