from django.urls import path

from . import views

app_name = "claims"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("claims/new/", views.capture_claim, name="capture_claim"),
    path("claims/drafts/<uuid:draft_id>/", views.capture_claim, name="resume_draft"),
    path("claims/<uuid:claim_id>/", views.claim_detail, name="claim_detail"),
]
