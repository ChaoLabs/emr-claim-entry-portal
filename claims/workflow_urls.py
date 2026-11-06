from django.urls import path

from . import workflow_views as views

app_name = "workflow"

urlpatterns = [
    path("x12/", views.archive, name="archive"),
    path("claims/<uuid:claim_id>/submission/", views.submission, name="submission"),
    path("x12/<uuid:document_id>/", views.document, name="document"),
    path("x12/<uuid:document_id>/download/", views.download, name="download"),
]
