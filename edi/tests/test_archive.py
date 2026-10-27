import hashlib

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse

from edi.models import SubmissionBatch, TradingPartner, X12Document


def make_batch():
    partner = TradingPartner.objects.create(
        name="Archive test partner",
        isa_sender_id="TESTSENDER",
        isa_receiver_id="TESTRECEIVER",
        gs_sender_code="TESTSENDER",
        gs_receiver_code="TESTRECEIVER",
        submitter_name="Fictional submitter",
        submitter_id="TESTSUBMITTER",
        submitter_contact_name="Test contact",
        receiver_name="Fictional receiver",
        receiver_id="TESTRECEIVER",
    )
    return SubmissionBatch.objects.create(
        trading_partner=partner,
        file_name="fictional-837p.edi",
        isa_control_number="000000001",
        gs_control_number="1",
        st_control_number="1",
    )


class X12DocumentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.batch = make_batch()

    def test_payload_preserves_padding_line_endings_and_utf8_bytes(self):
        content = "ISA*  TEST  ~\r\nNTE*ADD*Fictional café~\nIEA*1*000000001~\n"
        document = X12Document.archive(batch=self.batch, content=content)
        document.refresh_from_db()
        self.assertEqual(document.content, content)
        self.assertEqual(document.byte_count, len(content.encode("utf-8")))
        self.assertEqual(document.sha256, hashlib.sha256(content.encode("utf-8")).hexdigest())
        self.assertEqual(self.batch.x12_document, document)

    def test_same_payload_retry_returns_original_record(self):
        first = X12Document.archive(batch=self.batch, content="ST*837*1~SE*2*1~\n")
        retry = X12Document.archive(batch=self.batch, content=first.content)
        self.assertEqual(retry.pk, first.pk)
        self.assertEqual(retry.created_at, first.created_at)
        self.assertEqual(X12Document.objects.count(), 1)

    def test_different_payload_cannot_replace_archive(self):
        first = X12Document.archive(batch=self.batch, content="ST*837*1~SE*2*1~\n")
        with self.assertRaises(ValidationError):
            X12Document.archive(batch=self.batch, content=first.content.rstrip("\n"))
        first.refresh_from_db()
        self.assertEqual(first.content, "ST*837*1~SE*2*1~\n")
        self.assertEqual(X12Document.objects.count(), 1)

    def test_invalid_text_is_rejected_before_storage(self):
        for content in (None, b"ST*837~", "", "ST*\x00~", "\ud800"):
            with self.subTest(content=repr(content)):
                with self.assertRaises(ValidationError):
                    X12Document.archive(batch=self.batch, content=content)
        self.assertFalse(X12Document.objects.exists())

    def test_direct_creation_validates_and_derives_integrity_metadata(self):
        with self.assertRaises(ValidationError):
            X12Document.objects.create(batch=self.batch, content="ST*\x00~")
        document = X12Document.objects.create(
            batch=self.batch, content="ST*837~\n", sha256="incorrect", byte_count=999
        )
        self.assertEqual(document.byte_count, 8)
        self.assertEqual(document.sha256, hashlib.sha256(b"ST*837~\n").hexdigest())

    def test_database_allows_only_one_document_per_batch(self):
        X12Document.archive(batch=self.batch, content="ST*837~\n")
        with self.assertRaises(IntegrityError), transaction.atomic():
            X12Document.objects.create(batch=self.batch, content="ST*837*2~\n")

    def test_instance_save_cannot_rewrite_existing_document(self):
        document = X12Document.archive(batch=self.batch, content="ST*837~\n")
        document.content = "changed"
        with self.assertRaises(ValidationError):
            document.save()
        document.refresh_from_db()
        self.assertEqual(document.content, "ST*837~\n")

    def test_new_instance_with_existing_pk_cannot_replace_archive(self):
        document = X12Document.archive(batch=self.batch, content="ST*837~\n")
        replacement = X12Document(id=document.pk, batch=self.batch, content="changed")
        with self.assertRaises(ValidationError):
            replacement.save()
        document.refresh_from_db()
        self.assertEqual(document.content, "ST*837~\n")

    def test_batch_deletion_is_protected(self):
        document = X12Document.archive(batch=self.batch, content="ST*837~\n")
        with self.assertRaises(ProtectedError):
            self.batch.delete()
        self.assertTrue(SubmissionBatch.objects.filter(pk=self.batch.pk).exists())
        self.assertTrue(X12Document.objects.filter(pk=document.pk).exists())


class X12DocumentAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.document = X12Document.archive(batch=make_batch(), content="ST*837*SECRET_PAYLOAD~\n")
        cls.superuser = get_user_model().objects.create_superuser(
            username="archive-admin", password="fictional-tests-only"
        )
        cls.viewer = get_user_model().objects.create_user(
            username="archive-viewer", password="fictional-tests-only", is_staff=True
        )
        cls.viewer.user_permissions.add(
            Permission.objects.get(content_type__app_label="edi", codename="view_x12document")
        )
        cls.unprivileged = get_user_model().objects.create_user(
            username="archive-no-access", password="fictional-tests-only", is_staff=True
        )

    def test_authorized_viewer_can_read_content_but_list_only_has_metadata(self):
        self.client.force_login(self.viewer)
        detail = self.client.get(reverse("admin:edi_x12document_change", args=[self.document.pk]))
        self.assertContains(detail, "SECRET_PAYLOAD")
        listing = self.client.get(reverse("admin:edi_x12document_changelist"))
        self.assertContains(listing, self.document.sha256)
        self.assertNotContains(listing, "SECRET_PAYLOAD")
        model_admin = admin.site._registry[X12Document]
        self.assertNotIn("content", model_admin.list_display)
        self.assertNotIn("content", model_admin.search_fields)

    def test_even_superuser_cannot_add_edit_or_delete_in_admin(self):
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(reverse("admin:edi_x12document_add")).status_code, 403)
        detail_url = reverse("admin:edi_x12document_change", args=[self.document.pk])
        self.assertEqual(self.client.get(detail_url).status_code, 200)
        self.assertEqual(self.client.post(detail_url, {"content": "changed"}).status_code, 403)
        delete_url = reverse("admin:edi_x12document_delete", args=[self.document.pk])
        self.assertEqual(self.client.post(delete_url, {"post": "yes"}).status_code, 403)
        self.document.refresh_from_db()
        self.assertEqual(self.document.content, "ST*837*SECRET_PAYLOAD~\n")

    def test_staff_without_view_permission_cannot_read_archive(self):
        self.client.force_login(self.unprivileged)
        response = self.client.get(reverse("admin:edi_x12document_change", args=[self.document.pk]))
        self.assertEqual(response.status_code, 403)
