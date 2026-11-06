"""Claim register search, status filters and stable pagination."""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Claim, Patient


class DashboardRegisterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.patient = Patient.objects.create(first_name="Synthetic", last_name="Sample & Co")
        cls.other_patient = Patient.objects.create(first_name="Other", last_name="Example")
        cls.claims = [Claim.objects.create(patient=cls.patient, claim_number=f"REGISTER-{i:03d}",
                      status=Claim.STATUS_READY_FOR_REVIEW if i % 2 else Claim.STATUS_DRAFT)
                      for i in range(31)]
        cls.other_claim = Claim.objects.create(patient=cls.other_patient, claim_number="OTHER-CLAIM", status=Claim.STATUS_PAID)
        # Deliberately tied timestamps exercise the deterministic id tie-breaker.
        Claim.objects.filter(patient=cls.patient).update(created_at=timezone.now())
        cls.url = reverse("claims:dashboard")

    def test_patient_search_and_status_filter_combine_without_changing_overview_totals(self):
        response = self.client.get(self.url, {"q": "  sample & co  ", "status": Claim.STATUS_READY_FOR_REVIEW})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["query"], "sample & co")
        self.assertEqual(response.context["status"], Claim.STATUS_READY_FOR_REVIEW)
        self.assertEqual(response.context["page"].paginator.count, 15)
        self.assertTrue(all(claim.status == Claim.STATUS_READY_FOR_REVIEW for claim in response.context["recent_claims"]))
        self.assertEqual(response.context["claim_count"], 32)
        self.assertEqual(response.context["draft_count"], 16)
        self.assertEqual(response.context["ready_for_review_count"], 15)
        self.assertNotContains(response, self.other_claim.claim_number)

    def test_claim_number_search_is_case_insensitive(self):
        response = self.client.get(self.url, {"q": "register-004"})
        self.assertEqual(list(response.context["recent_claims"]), [self.claims[4]])
        self.assertEqual(response.context["page"].paginator.count, 1)

    def test_pagination_has_no_duplicates_and_retains_encoded_filters(self):
        expected = list(Claim.objects.filter(patient=self.patient).order_by("-created_at", "id"))
        collected = []
        for page in (1, 2, 3):
            response = self.client.get(self.url, {"q": "Sample & Co", "page": page})
            collected.extend(response.context["recent_claims"])
            self.assertEqual(len(response.context["recent_claims"]), 15 if page < 3 else 1)
            self.assertContains(response, "q=Sample%20%26%20Co")
        self.assertEqual(collected, expected)
        self.assertEqual(len({claim.pk for claim in collected}), 31)

    def test_invalid_status_and_page_are_handled_without_error(self):
        response = self.client.get(self.url, {"status": "not-a-real-status", "page": "not-a-number"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["status"], "")
        self.assertEqual(response.context["page"].number, 1)
        self.assertEqual(response.context["page"].paginator.count, 32)
        response = self.client.get(self.url, {"page": "9999"})
        self.assertEqual(response.context["page"].number, 3)

    def test_unmatched_query_shows_clear_filters_and_does_not_render_html(self):
        response = self.client.get(self.url, {"q": '<script>alert("sample")</script>'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No matching claims")
        self.assertContains(response, "Clear filters")
        self.assertNotContains(response, '<script>alert("sample")</script>')
        self.assertEqual(response.context["page"].paginator.count, 0)
