from django.contrib import admin

from .models import (
    Claim,
    ClaimAuditEvent,
    ClaimDiagnosis,
    ClaimProvider,
    InsuredParty,
    Patient,
    Payer,
    Provider,
    ServiceLine,
)


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
        "payer",
        "status",
        "total_charge_amount",
        "service_start_date",
        "service_end_date",
        "created_at",
    )
    list_filter = ("status", "payer", "service_start_date", "created_at")
    search_fields = (
        "claim_number",
        "patient__first_name",
        "patient__last_name",
        "payer__payer_name",
    )
    date_hierarchy = "created_at"
    inlines = [
        ClaimProviderInline,
        ClaimDiagnosisInline,
        ServiceLineInline,
        ClaimAuditEventInline,
    ]


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "date_of_birth", "sex", "city", "state")
    search_fields = ("first_name", "last_name", "city", "state", "zip_code")
    list_filter = ("sex", "state")
    ordering = ("last_name", "first_name")


@admin.register(InsuredParty)
class InsuredPartyAdmin(admin.ModelAdmin):
    list_display = (
        "last_name",
        "first_name",
        "relationship_to_patient",
        "insured_id_number",
        "group_number",
    )
    search_fields = ("first_name", "last_name", "insured_id_number", "group_number")
    list_filter = ("relationship_to_patient", "state")
    ordering = ("last_name", "first_name")


@admin.register(Payer)
class PayerAdmin(admin.ModelAdmin):
    list_display = ("payer_name", "payer_type", "payer_identifier", "medicare_administrative_contractor")
    search_fields = ("payer_name", "payer_identifier", "medicare_administrative_contractor")
    list_filter = ("payer_type",)
    ordering = ("payer_name",)


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    list_display = ("display_name", "npi", "taxonomy_code", "city", "state")
    search_fields = (
        "organization_name",
        "first_name",
        "last_name",
        "npi",
        "taxonomy_code",
        "city",
        "state",
    )
    list_filter = ("state", "taxonomy_code")
    ordering = ("organization_name", "last_name", "first_name")

    @admin.display(description="Provider")
    def display_name(self, obj):
        return str(obj)


@admin.register(ClaimProvider)
class ClaimProviderAdmin(admin.ModelAdmin):
    list_display = ("claim", "provider_role", "provider")
    list_filter = ("provider_role",)
    search_fields = ("claim__claim_number", "provider__organization_name", "provider__npi")


@admin.register(ClaimDiagnosis)
class ClaimDiagnosisAdmin(admin.ModelAdmin):
    list_display = ("claim", "diagnosis_order", "diagnosis_code", "description")
    list_filter = ("diagnosis_code",)
    search_fields = ("claim__claim_number", "diagnosis_code", "description")
    ordering = ("claim", "diagnosis_order")


@admin.register(ServiceLine)
class ServiceLineAdmin(admin.ModelAdmin):
    list_display = (
        "claim",
        "procedure_code",
        "service_from_date",
        "service_to_date",
        "place_of_service",
        "charge_amount",
        "units",
    )
    list_filter = ("procedure_code", "place_of_service", "service_from_date")
    search_fields = ("claim__claim_number", "procedure_code", "place_of_service")


@admin.register(ClaimAuditEvent)
class ClaimAuditEventAdmin(admin.ModelAdmin):
    list_display = ("claim", "event_type", "changed_by", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("claim__claim_number", "event_type", "event_description", "changed_by")
    readonly_fields = ("created_at",)
