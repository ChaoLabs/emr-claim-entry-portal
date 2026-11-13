from django.test import TestCase

from . import tests as existing
from .capture_test_helpers import submit_new_claim
from .models import Claim, Icd10Code


class DynamicCaptureTests(TestCase):
    setUp = existing.ClaimCaptureWorkflowTests.setUp
    _capture_payload = existing.ClaimCaptureWorkflowTests._capture_payload
    _service_line_payload = existing.ClaimCaptureWorkflowTests._service_line_payload

    def test_more_than_four_diagnoses_and_modifiers_saved_in_order(self):
        payload = self._capture_payload()
        payload['diagnoses-TOTAL_FORMS'] = '6'
        for index in range(1, 6):
            code = f'Z{index:02}.0'
            Icd10Code.objects.create(code=code, short_description=f'Synthetic diagnosis {index}', is_active=True)
            payload[f'diagnoses-{index}-diagnosis_code'] = code
        payload['service_lines-0-diagnosis_refs'] = ['5', '0', '3', '1', '2', '4']
        payload['service_lines-0-modifier_codes'] = ['25', '59', 'KX', 'GT', '95', 'GA']
        response = submit_new_claim(self.client, payload)
        self.assertEqual(response.status_code, 302)
        claim = Claim.objects.get(claim_number=payload['claim_number'])
        line = claim.service_lines.get()
        self.assertEqual(list(claim.diagnoses.values_list('diagnosis_order', flat=True)), [1, 2, 3, 4, 5, 6])
        self.assertEqual(line.diagnosis_pointers, [6, 1, 4, 2, 3, 5])
        self.assertEqual(line.modifier_codes, ['25', '59', 'KX', 'GT', '95', 'GA'])

    def test_removed_diagnosis_does_not_reassign_a_service_link(self):
        payload = self._capture_payload()
        payload.update({'diagnoses-TOTAL_FORMS': '2', 'diagnoses-0-DELETE': 'on',
                        'diagnoses-1-diagnosis_code': 'M54.50'})
        response = submit_new_claim(self.client, payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'A selected diagnosis may have been removed')
        self.assertContains(response, 'Unavailable diagnosis')
        self.assertFalse(Claim.objects.filter(claim_number=payload['claim_number']).exists())
        payload['service_lines-0-diagnosis_refs'] = ['1']
        response = submit_new_claim(self.client, payload)
        self.assertEqual(response.status_code, 302)
        line = Claim.objects.get(claim_number=payload['claim_number']).service_lines.get()
        self.assertEqual(line.diagnosis_pointers, [1])
        self.assertEqual(line.diagnosis_links.get().diagnosis.diagnosis_code, 'M54.50')

    def test_same_diagnosis_supports_multiple_lines(self):
        payload = self._capture_payload()
        payload['service_lines-TOTAL_FORMS'] = '2'
        payload.update(self._service_line_payload(1))
        response = submit_new_claim(self.client, payload)
        self.assertEqual(response.status_code, 302)
        claim = Claim.objects.get(claim_number=payload['claim_number'])
        self.assertEqual(claim.diagnoses.count(), 1)
        self.assertEqual(claim.diagnoses.get().service_line_links.count(), 2)

    def test_duplicate_and_missing_links_rejected_without_partial_save(self):
        for refs in (['0', '0'], [], ['-1'], ['999']):
            with self.subTest(refs=refs):
                payload = self._capture_payload()
                payload['service_lines-0-diagnosis_refs'] = refs
                response = submit_new_claim(self.client, payload)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(Claim.objects.filter(claim_number=payload['claim_number']).exists())

    def test_invalid_duplicate_modifiers_preserve_other_values(self):
        payload = self._capture_payload()
        payload['service_lines-0-modifier_codes'] = ['25', 'bad']
        response = submit_new_claim(self.client, payload)
        self.assertContains(response, 'Each modifier must contain two letters or digits.')
        self.assertContains(response, 'value="25"')
        self.assertContains(response, 'value="bad"')
        self.assertFalse(Claim.objects.filter(claim_number=payload['claim_number']).exists())
        payload['service_lines-0-modifier_codes'] = ['25', '25']
        response = submit_new_claim(self.client, payload)
        self.assertContains(response, 'Enter each modifier only once')

    def test_duplicate_claim_diagnosis_is_rejected(self):
        payload = self._capture_payload()
        payload.update({'diagnoses-TOTAL_FORMS': '2', 'diagnoses-1-diagnosis_code': 'R51.9'})
        response = submit_new_claim(self.client, payload)
        self.assertContains(response, 'This diagnosis is already on the claim')
        self.assertFalse(Claim.objects.filter(claim_number=payload['claim_number']).exists())

    def test_management_form_tampering_rejected(self):
        payload = self._capture_payload()
        payload.pop('diagnoses-TOTAL_FORMS')
        response = submit_new_claim(self.client, payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Claim.objects.filter(claim_number=payload['claim_number']).exists())
