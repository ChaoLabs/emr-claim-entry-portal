from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase

from claims.models import ClaimCoverage, InsurancePolicy, InsuredParty, Patient, Payer, Provider
from edi import builders, formatters, validators


class PostalValidationTests(SimpleTestCase):
    """ZIP requirements depend on the address's role, not the whole claim."""

    def billing(self, zip_code="27701-1234", tax_id="12-3456789"):
        return Provider(
            organization_name="Fictional Clinic", npi="1234567893",
            zip_code=zip_code, tax_id=tax_id,
            address_line_1="200 Demo Provider Blvd", city="Durham", state="NC",
        )

    def payer(self, zip_code="21244", extension=""):
        return Payer(
            payer_name="Fictional Payer", payer_identifier="DEMO",
            address_line_1="7500 Demo Payer Drive", city="Baltimore", state="MD",
            zip_code=zip_code, zip_code_extension=extension,
        )

    def person_context(self, zip_code="27601", *, is_subscriber=False):
        person = InsuredParty(
            first_name="Alex", last_name="Morgan", date_of_birth=date(1985, 4, 12),
            address_line_1="100 Demo Patient Ave", city="Raleigh", state="NC",
            zip_code=zip_code,
        )
        return SimpleNamespace(
            insured=person, claim=SimpleNamespace(patient=person),
            patient_is_subscriber=is_subscriber, sbr02="18" if is_subscriber else "19",
            sbr02_source="test", policy=SimpleNamespace(member_id="DEMO-MEMBER"),
        )

    def test_normalizer_preserves_five_digit_zip_and_leading_zero(self):
        for entered, expected in (
            ("02108", "02108"), ("021081234", "021081234"),
            ("02108-1234", "021081234"), (" 02108-1234 ", "021081234"),
        ):
            with self.subTest(entered=entered):
                self.assertEqual(formatters.us_zip(entered), expected)

    def test_normalizer_rejects_malformed_values_instead_of_stripping_or_padding(self):
        for entered in (None, "", "1234", "123456", "12345678", "1234567890",
                        "NC27701", "27701A1234", "27701 1234", "277-011234",
                        "２７７０１", "27701-１２３４", "27701\n1234"):
            with self.subTest(entered=entered):
                self.assertIsNone(formatters.us_zip(entered))

    def test_normalizer_validates_separate_extension_without_guessing(self):
        self.assertEqual(formatters.us_zip("02108", "1234"), "021081234")
        self.assertEqual(formatters.us_zip("02108", ""), "02108")
        for base, extra in (("", "1234"), ("02108", "123"), ("02108", "12A4"),
                            ("02108", "１２３４"), ("021081234", "1234"),
                            ("02108-1234", "1234"), ("NC02108", "1234")):
            with self.subTest(base=base, extra=extra):
                self.assertIsNone(formatters.us_zip(base, extra))

    def test_billing_requires_zip_plus_four(self):
        billing = self.billing("27701")
        issues = validators.validate_billing_provider(billing)
        self.assertEqual([issue.tag for issue in issues], ["2010AA N403"])
        self.assertIn("5-digit ZIP can be saved", issues[0].message)
        self.assertIn("verified", issues[0].message)
        self.assertEqual(billing.zip_code, "27701")

    def test_billing_accepts_full_zip_with_or_without_hyphen(self):
        for postal in ("277011234", "27701-1234", " 02108-1234 "):
            with self.subTest(postal=postal):
                self.assertEqual(validators.validate_billing_provider(self.billing(postal)), [])

    def test_billing_does_not_sanitize_bad_characters_into_valid_zip(self):
        for postal in ("27701A1234", "２７７０１１２３４", "27701-123", ""):
            with self.subTest(postal=postal):
                self.assertIn("2010AA N403", [i.tag for i in validators.validate_billing_provider(self.billing(postal))])

    def test_billing_ein_is_required_and_has_explicit_ein_format(self):
        for ein in ("123456789", "12-3456789"):
            with self.subTest(ein=ein):
                self.assertEqual(validators.validate_billing_provider(self.billing(tax_id=ein)), [])
        for ein in ("", "DEMO-TAX-ID", "12A3456789", "１２３４５６７８９", "123-45-6789"):
            with self.subTest(ein=ein):
                issues = validators.validate_billing_provider(self.billing(tax_id=ein))
                self.assertEqual([i.tag for i in issues], ["2010AA REF EI"])
                self.assertIn("EIN", issues[0].message)

    def test_payer_zip_plus_four_is_optional(self):
        for base, extra in (("21244", ""), ("21244", "1850"),
                            ("212441850", ""), ("21244-1850", "")):
            with self.subTest(base=base, extra=extra):
                self.assertEqual(validators.validate_payer(self.payer(base, extra)), [])

    def test_payer_bad_base_or_extension_is_rejected(self):
        for base, extra in (("", "1850"), ("21244A", ""), ("21244", "18A0"),
                            ("212441850", "1850"), ("21244", "１８５０")):
            with self.subTest(base=base, extra=extra):
                self.assertEqual([i.tag for i in validators.validate_payer(self.payer(base, extra))], ["2010BB N403"])

    def test_subscriber_and_dependent_patient_accept_five_digit_zip(self):
        for postal in ("27601", "276011234", "27601-1234"):
            with self.subTest(postal=postal):
                ctx = self.person_context(postal)
                self.assertEqual(validators.validate_subscriber(ctx), [])
                self.assertEqual(validators.validate_patient(ctx), [])

    def test_subscriber_and_dependent_patient_reject_malformed_zip(self):
        for postal in ("", "2760", "NC27601", "27601A1234", "２７６０１"):
            with self.subTest(postal=postal):
                ctx = self.person_context(postal)
                self.assertEqual([i.tag for i in validators.validate_subscriber(ctx)], ["2010BA N403"])
                self.assertEqual([i.tag for i in validators.validate_patient(ctx)], ["2010CA N403"])

    def test_dependent_patient_address_is_checked_only_when_emitted(self):
        ctx = self.person_context()
        ctx.claim.patient.address_line_1 = ""
        self.assertEqual([i.tag for i in validators.validate_patient(ctx)], ["2010CA N3/N4"])
        ctx.patient_is_subscriber = True
        self.assertEqual(validators.validate_patient(ctx), [])

    def test_export_normalizes_billing_zip_and_ein_but_does_not_extend_other_zips(self):
        billing = self.billing("02108-1234")
        self.assertEqual(validators.validate_billing_provider(billing), [])
        wire = builders.billing_provider_loop(billing, 1)
        self.assertEqual(next(s for s in wire if s.segment_id == "N4").element(3), "021081234")
        self.assertEqual(next(s for s in wire if s.segment_id == "REF").element(2), "123456789")
        # Original entered values remain available; only the wire loses dashes.
        self.assertEqual(billing.zip_code, "02108-1234")
        self.assertEqual(billing.tax_id, "12-3456789")

        insured = self.person_context("02108").insured
        wire = builders.subscriber_loop(
            ClaimCoverage(payer_sequence="primary"), InsurancePolicy(member_id="DEMO"),
            insured, self.payer("21244"), "18", 2, 1, False,
        )
        self.assertEqual([s.element(3) for s in wire if s.segment_id == "N4"], ["02108", "21244"])
        patient = Patient(first_name="Fictional", last_name="Dependent", zip_code="02108",
                          address_line_1="1 Demo Road", city="Boston", state="MA")
        wire = builders.patient_loop(patient, 3, 2, "19")
        self.assertEqual(next(s for s in wire if s.segment_id == "N4").element(3), "02108")
