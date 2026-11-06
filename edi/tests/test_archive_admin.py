"""Admin archive usability and permission boundaries use real admin requests."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape

from edi.models import RemittanceDocument, X12Document
from edi.remittance import import_835
from edi.tests.test_archive import make_batch
from edi.tests.test_remittance import synthetic_response


class ArchiveAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = get_user_model().objects.create_superuser("archive-admin", "admin@example.invalid", "test-only-password")
        cls.viewer = get_user_model().objects.create_user("archive-viewer", password="test-only-password", is_staff=True)
        cls.unprivileged = get_user_model().objects.create_user("staff-without-permission", password="test-only-password", is_staff=True)
        cls.viewer.user_permissions.add(Permission.objects.get(codename="view_x12document"), Permission.objects.get(codename="view_remittancedocument"))
        cls.batch = make_batch()
        cls.payload = 'ISA*  FICTIONAL  ~\r\nNTE*ADD*</textarea><script>alert("demo")</script>~\n'
        cls.document = X12Document.archive(batch=cls.batch, content=cls.payload)
        cls.remittance, _ = import_835(synthetic_response(), source_name="synthetic-only.835", imported_by="test")

    def url(self, model, action, obj):
        return reverse(f"admin:edi_{model}_{action}", args=[obj.pk])

    def test_superuser_sees_original_and_clear_actions_without_edit_controls(self):
        self.client.force_login(self.superuser)
        response = self.client.get(self.url("x12document", "change", self.document))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Permanent 837P archive")
        self.assertContains(response, self.batch.file_name)
        self.assertContains(response, "Generated")
        self.assertContains(response, 'readonly aria-label="Original X12 content"')
        self.assertContains(response, escape(self.payload))
        self.assertContains(response, "View archived file")
        self.assertContains(response, "Download original")
        self.assertNotContains(response, '<script>alert("demo")</script>')
        self.assertNotContains(response, 'name="_save"')
        self.assertNotContains(response, 'class="deletelink"')

    def test_x12_download_preserves_bytes_and_reader_has_expected_content(self):
        self.client.force_login(self.viewer)
        download = self.client.get(self.url("x12document", "download_original", self.document))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, self.payload.encode("utf-8"))
        self.assertIn("attachment", download["Content-Disposition"])
        view = self.client.get(self.url("x12document", "view_original", self.document))
        self.assertEqual(view.status_code, 200)
        self.assertContains(view, escape(self.payload))

    def test_changelist_shows_metadata_without_raw_payload(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("admin:edi_x12document_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.batch.file_name)
        self.assertContains(response, "Submission status")
        self.assertNotContains(response, "FICTIONAL")
        self.assertNotContains(response, self.document.sha256)

    def test_admin_archive_routes_require_model_view_permission_not_just_staff(self):
        for model, obj in (("x12document", self.document), ("remittancedocument", self.remittance)):
            for action in ("change", "view_original", "download_original"):
                url = self.url(model, action, obj)
                self.client.logout()
                self.assertEqual(self.client.get(url).status_code, 302)
                self.client.force_login(self.unprivileged)
                self.assertEqual(self.client.get(url).status_code, 403)
                self.client.force_login(self.viewer)
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_even_superuser_cannot_edit_add_or_delete_archived_files(self):
        self.client.force_login(self.superuser)
        for model, obj in (("x12document", self.document), ("remittancedocument", self.remittance)):
            self.assertEqual(self.client.post(self.url(model, "change", obj), {"content": "tampered", "_save": "Save"}).status_code, 403)
            self.assertEqual(self.client.get(reverse(f"admin:edi_{model}_add")).status_code, 403)
            self.assertEqual(self.client.post(self.url(model, "delete", obj), {"post": "yes"}).status_code, 403)
        self.document.refresh_from_db()
        self.assertEqual(self.document.content, self.payload)

    def test_returned_835_admin_exposes_exact_download_and_readable_view(self):
        self.client.force_login(self.superuser)
        response = self.client.get(self.url("remittancedocument", "change", self.remittance))
        self.assertContains(response, "Returned 835 archive")
        self.assertContains(response, "synthetic-only.835")
        response = self.client.get(self.url("remittancedocument", "download_original", self.remittance))
        self.assertEqual(response.content, synthetic_response())
        response = self.client.get(self.url("remittancedocument", "view_original", self.remittance))
        self.assertContains(response, "Returned claim results")

    def test_admin_download_retains_integrity_failure(self):
        self.client.force_login(self.superuser)
        X12Document.objects.filter(pk=self.document.pk).update(content="tampered outside application")
        RemittanceDocument.objects.filter(pk=self.remittance.pk).update(content="tampered outside application")
        self.assertEqual(self.client.get(self.url("x12document", "download_original", self.document)).status_code, 409)
        self.assertEqual(self.client.get(self.url("remittancedocument", "download_original", self.remittance)).status_code, 409)
