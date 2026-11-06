from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.urls import path, reverse
from django.utils.html import format_html

from .models import (
    BatchClaim, ControlNumber, RemittanceClaim, RemittanceDocument,
    SubmissionBatch, TradingPartner, X12Document,
)


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


class ArchiveActionsAdmin(ReadOnlyAdmin):
    """Archive links preserve the same object-view permission as the admin page."""

    def get_urls(self):
        opts = self.model._meta
        return [
            path("<uuid:object_id>/view-original/", self.admin_site.admin_view(self.view_original),
                 name=f"{opts.app_label}_{opts.model_name}_view_original"),
            path("<uuid:object_id>/download-original/", self.admin_site.admin_view(self.download_original),
                 name=f"{opts.app_label}_{opts.model_name}_download_original"),
        ] + super().get_urls()

    def checked_archive(self, request, object_id):
        obj = self.get_object(request, str(object_id))
        # Perform permission check before delegating to a portal view. Do not
        # grant a staff user archive access merely by knowing an object UUID.
        if obj is None or not self.has_view_permission(request, obj):
            raise PermissionDenied
        return obj

    @admin.display(description="Open original file")
    def archive_actions(self, obj):
        opts = self.model._meta
        view_url = reverse(f"admin:{opts.app_label}_{opts.model_name}_view_original", args=[obj.pk])
        download_url = reverse(f"admin:{opts.app_label}_{opts.model_name}_download_original", args=[obj.pk])
        return format_html(
            '<div style="display:flex;flex-wrap:wrap;gap:10px">'
            '<a href="{}" style="background:#247d90;color:#fff;border-radius:6px;padding:10px 14px;text-decoration:none">View archived file</a>'
            '<a href="{}" style="border:1px solid #b7d9e1;color:#247d90;border-radius:6px;padding:10px 14px;text-decoration:none">Download original</a>'
            '</div>', view_url, download_url,
        )

    @admin.display(description="Original X12 content")
    def original_content(self, obj):
        return format_html(
            '<textarea readonly aria-label="Original X12 content" rows="14" '
            'spellcheck="false" style="box-sizing:border-box;width:100%;max-width:1100px;'
            'font-family:ui-monospace,SFMono-Regular,Consolas,monospace;line-height:1.6;'
            'background:#f5f9fa;color:#263943;border:1px solid #d2e0e5;border-radius:8px;'
            'padding:16px;resize:vertical">{}</textarea>'
            '<p style="color:#526572;line-height:1.6;margin-top:10px">'
            'Read-only copy retained at generation or import. Download the original to preserve exact file bytes and line endings.</p>',
            obj.content,
        )


@admin.register(X12Document)
class X12DocumentAdmin(ArchiveActionsAdmin):
    list_display = ("file_name", "submission_status", "created_at", "byte_count")
    list_select_related = ("batch",)
    list_filter = ("batch__status", "created_at")
    date_hierarchy = "created_at"
    search_fields = ("batch__file_name", "sha256")
    readonly_fields = (
        "id", "batch", "content", "original_content", "archive_actions", "file_name",
        "submission_status", "sha256", "byte_count", "created_at",
    )
    fieldsets = (
        ("Permanent 837P archive", {
            "description": "This is the original file generated for the submission. It is retained independently of downloaded or transferred copies.",
            "fields": ("file_name", "submission_status", "created_at", "archive_actions", "original_content"),
        }),
        ("Archive details", {
            "classes": ("collapse",),
            "fields": ("id", "batch", "byte_count", "sha256"),
        }),
    )

    @admin.display(description="File", ordering="batch__file_name")
    def file_name(self, obj):
        return obj.batch.file_name

    @admin.display(description="Submission status", ordering="batch__status")
    def submission_status(self, obj):
        return obj.batch.get_status_display()

    def view_original(self, request, object_id):
        self.checked_archive(request, object_id)
        from claims.workflow_views import document
        return document(request, document_id=object_id)

    def download_original(self, request, object_id):
        self.checked_archive(request, object_id)
        from claims.workflow_views import download
        return download(request, document_id=object_id)


@admin.register(RemittanceDocument)
class RemittanceDocumentAdmin(ArchiveActionsAdmin):
    list_display = ("source_name", "imported_at", "imported_by", "byte_count")
    list_select_related = ("batch",)
    date_hierarchy = "imported_at"
    search_fields = ("source_name", "sha256")
    readonly_fields = (
        "id", "content", "original_content", "archive_actions", "sha256", "byte_count",
        "source_name", "imported_by", "imported_at", "batch", "summary",
    )
    fieldsets = (
        ("Returned 835 archive", {
            "description": "The exact returned file is preserved. Viewing a response does not confirm payment settlement.",
            "fields": ("source_name", "imported_at", "imported_by", "archive_actions", "original_content"),
        }),
        ("Archive details", {
            "classes": ("collapse",),
            "fields": ("id", "batch", "byte_count", "sha256", "summary"),
        }),
    )

    def view_original(self, request, object_id):
        self.checked_archive(request, object_id)
        from .views import remittance_detail
        return remittance_detail(request, pk=object_id)

    def download_original(self, request, object_id):
        self.checked_archive(request, object_id)
        from .views import remittance_download
        return remittance_download(request, pk=object_id)


@admin.register(RemittanceClaim)
class RemittanceClaimAdmin(ReadOnlyAdmin):
    list_display = ("document", "position", "status_code", "paid_amount")
    readonly_fields = ("document", "position", "claim", "claim_number", "status_code", "payer_control_number", "charge_amount", "paid_amount", "patient_responsibility", "details")
