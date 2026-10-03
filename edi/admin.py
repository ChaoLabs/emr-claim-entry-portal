from django.contrib import admin

from .models import BatchClaim, ControlNumber, SubmissionBatch, TradingPartner


@admin.register(TradingPartner)
class TradingPartnerAdmin(admin.ModelAdmin):
    list_display = ("name", "usage_indicator", "is_active", "updated_at")
    list_filter = ("usage_indicator", "is_active")
    search_fields = ("name",)


class ReadOnlyAdmin(admin.ModelAdmin):
    """Generated records cannot be edited/deleted through the admin."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ControlNumber)
class ControlNumberAdmin(ReadOnlyAdmin):
    list_display = ("trading_partner", "level", "current_value")


@admin.register(SubmissionBatch)
class SubmissionBatchAdmin(ReadOnlyAdmin):
    list_display = ("id", "trading_partner", "status", "claim_count", "created_at")
    list_filter = ("status", "trading_partner")


@admin.register(BatchClaim)
class BatchClaimAdmin(ReadOnlyAdmin):
    list_display = ("batch", "position", "claim_id")
