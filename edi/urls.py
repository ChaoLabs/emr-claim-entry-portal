from django.urls import path
from . import views

app_name = "edi"
urlpatterns = [
    path("responses/", views.remittance_list, name="remittance_list"),
    path("responses/import/", views.remittance_import, name="remittance_import"),
    path("responses/<uuid:pk>/", views.remittance_detail, name="remittance_detail"),
    path("responses/<uuid:pk>/download/", views.remittance_download, name="remittance_download"),
]
