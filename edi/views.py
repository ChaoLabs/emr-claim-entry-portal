from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from .forms import RemittanceUploadForm
from .models import RemittanceDocument
from .remittance import MAX_835_BYTES, import_835


def private_response(response):
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@staff_member_required
@require_GET
def remittance_list(request):
    page = Paginator(RemittanceDocument.objects.all(), 30).get_page(request.GET.get("page"))
    return private_response(render(request, "edi/remittance_list.html", {"page": page}))


@staff_member_required
@require_http_methods(["GET", "POST"])
def remittance_import(request):
    form = RemittanceUploadForm(request.POST if request.method == "POST" else None,
                                request.FILES if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["file"]
        try:
            document, created = import_835(upload.read(MAX_835_BYTES + 1), source_name=upload.name,
                imported_by=request.user.get_username(), batch=form.cleaned_data["batch"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "835 response imported." if created else "This exact response is already archived. The original record is shown.")
            return redirect("edi:remittance_detail", pk=document.pk)
    return private_response(render(request, "edi/remittance_import.html", {"form": form}))


@staff_member_required
@require_GET
def remittance_detail(request, pk):
    document = get_object_or_404(RemittanceDocument.objects.select_related("batch"), pk=pk)
    results = document.claim_results.select_related("claim")
    return private_response(render(request, "edi/remittance_detail.html", {
        "document": document, "results": results, "unmatched_count": results.filter(claim__isnull=True).count()}))


@staff_member_required
@require_GET
def remittance_download(request, pk):
    document = get_object_or_404(RemittanceDocument, pk=pk)
    try:
        payload = document.verify_integrity()
    except ValidationError:
        return private_response(HttpResponse("The archived file failed its integrity check. Contact the administrator.", status=409, content_type="text/plain"))
    response = HttpResponse(payload, content_type="application/octet-stream")
    response["Content-Disposition"] = f'attachment; filename="response-{document.pk}.835"'
    return private_response(response)
