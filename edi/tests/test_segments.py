from decimal import Decimal
from django.test import SimpleTestCase, TestCase
from tools.make_test_claims import create as create_test_claims

from claims.models import Claim
from edi import builders, codes, context, formatters, validators
from edi.segments import Composite, Delimiters, HLCounter, Segment, parse, serialize


class SegmentPrimitives(SimpleTestCase):
    def test_trailing_empty_elements_are_dropped(self):
        self.assertEqual(Segment("NM1", "PW", "2", "", "", "").render(), "NM1*PW*2")

    def test_interior_empty_elements_are_kept(self):
        rendered = Segment("NM1", "85", "2", "NAME", "", "", "", "", "XX", "123").render()
        self.assertEqual(rendered, "NM1*85*2*NAME*****XX*123")

    def test_composite_trims_its_own_tail(self):
        self.assertEqual(Composite("HC", "99213", "", "").render(), "HC:99213")

    def test_composite_keeps_interior_gap(self):
        self.assertEqual(Composite("1", "", "3").render(), "1::3")

    def test_delimiters_are_stripped_from_data(self):
        rendered = Segment("NM1", "IL", "1", "O*BRIEN~X:Y^Z").render()
        self.assertNotIn("*BRIEN", rendered)
        self.assertEqual(rendered.count("*"), 3)
        self.assertNotIn("~", rendered)

    def test_serialize_refuses_a_segment_with_no_data(self):
        with self.assertRaises(ValueError) as caught:
            serialize([Segment("LX", "1"), Segment("N4", "", "", "")])
        self.assertIn("N4", str(caught.exception))

    def test_is_empty_flag(self):
        self.assertTrue(Segment("N4", "", "", "").is_empty)
        self.assertTrue(Segment("SV1", Composite("", "")).is_empty)
        self.assertFalse(Segment("N4", "", "NC", "").is_empty)

    def test_element_accessor_is_one_based(self):
        segment = Segment("CLM", "ABC", "100", "", "", Composite("11", "B", "1"))
        self.assertEqual(segment.element(1), "ABC")
        self.assertEqual(segment.element(5), "11:B:1")
        self.assertEqual(segment.element(9), "")

    def test_custom_delimiters(self):
        pipe = Delimiters(element="|", composite="^", segment="\n")
        segment = Segment("SV1", Composite("HC", "99213"), "125")
        self.assertEqual(segment.render(pipe), "SV1|HC^99213|125")

    def test_round_trip(self):
        original = [Segment("LX", "1"), Segment("SV1", Composite("HC", "99213"), "125")]
        self.assertEqual(
            [s.render() for s in parse(serialize(original))],
            [s.render() for s in original],
        )


class HLCounterTests(SimpleTestCase):
    def test_ids_start_at_one_and_increment(self):
        counter = HLCounter()
        self.assertEqual([counter.take(), counter.take(), counter.take()], [1, 2, 3])
        self.assertEqual(counter.count, 3)

    def test_parents_are_recorded(self):
        counter = HLCounter()
        root = counter.take()
        child = counter.take(root)
        self.assertEqual(counter.issued[child], root)


class BodyInvariants(TestCase):
    @classmethod
    def setUpTestData(cls):
        create_test_claims()
        cls.claims = list(Claim.objects.all())
        cls.body, cls.counter = builders.build_from_claims(cls.claims)

    def hl_segments(self):
        return [s for s in self.body if s.segment_id == "HL"]

    def test_hl_ids_are_sequential_from_one(self):
        ids = [int(s.element(1)) for s in self.hl_segments()]
        self.assertEqual(ids, list(range(1, len(ids) + 1)))

    def test_every_hl_parent_exists_and_comes_first(self):
        seen = set()
        for segment in self.hl_segments():
            hl_id = int(segment.element(1))
            parent = segment.element(2)
            if parent:
                self.assertIn(int(parent), seen)
            seen.add(hl_id)

    def test_hl_child_flag_matches_reality(self):
        segments = self.hl_segments()
        parents = {int(s.element(2)) for s in segments if s.element(2)}
        for segment in segments:
            hl_id = int(segment.element(1))
            expected = "1" if hl_id in parents else "0"
            self.assertEqual(segment.element(4), expected, f"HL {hl_id}")

    def test_claim_total_equals_sum_of_service_lines(self):
        current = None
        running = Decimal("0")
        totals = []
        for segment in self.body:
            if segment.segment_id == "CLM":
                if current is not None:
                    totals.append((current, running))
                current = segment.element(2)
                running = Decimal("0")
            elif segment.segment_id == "SV1" and current is not None:
                running += Decimal(segment.element(2))
        if current is not None:
            totals.append((current, running))

        self.assertTrue(totals)
        for declared, summed in totals:
            self.assertEqual(Decimal(declared), summed)

    def test_diagnosis_pointers_have_a_matching_hi_position(self):
        available = 0
        for segment in self.body:
            if segment.segment_id == "HI":
                available = len(segment.elements)
            elif segment.segment_id == "SV1":
                pointers = segment.element(7)
                for pointer in filter(None, pointers.split(":")):
                    self.assertLessEqual(int(pointer), available)
                    self.assertGreaterEqual(int(pointer), 1)

    def test_first_diagnosis_uses_icd10_principal_qualifier(self):
        for segment in self.body:
            if segment.segment_id == "HI":
                self.assertTrue(segment.element(1).startswith(codes.DIAGNOSIS_PRINCIPAL))
                for position in range(2, len(segment.elements) + 1):
                    value = segment.element(position)
                    if value:
                        self.assertTrue(value.startswith(codes.DIAGNOSIS_OTHER))

    def test_no_segment_carries_a_raw_delimiter(self):
        for segment in self.body:
            rendered = segment.render()
            self.assertNotIn("~", rendered)
            for element in segment.elements:
                if isinstance(element, str):
                    self.assertNotIn("*", element)

    def test_no_segment_is_empty_apart_from_its_id(self):
        for segment in self.body:
            self.assertGreater(
                len(segment.render()), len(segment.segment_id),
                f"{segment.segment_id} rendered with no data",
            )

    def test_qualifier_segments_carry_a_value(self):
        for segment in self.body:
            if segment.segment_id in ("REF", "DTP", "PRV"):
                position = 2 if segment.segment_id == "REF" else 3
                self.assertTrue(
                    segment.element(position),
                    f"{segment.render()} has a qualifier but no value",
                )

    def test_nm1_never_ends_on_a_bare_identifier_qualifier(self):
        qualifiers = {codes.QUALIFIER_NPI, codes.QUALIFIER_MEMBER_ID,
                      codes.QUALIFIER_PAYER_ID, "II", "46", "34", "24"}
        for segment in self.body:
            if segment.segment_id != "NM1":
                continue
            if segment.element(8) in qualifiers:
                self.assertTrue(
                    segment.element(9),
                    f"{segment.render()} carries a qualifier with no identifier",
                )

    def test_clm05_carries_the_five_zero_ten_qualifier(self):
        for segment in self.body:
            if segment.segment_id == "CLM":
                parts = segment.element(5).split(":")
                self.assertEqual(len(parts), 3)
                self.assertEqual(parts[1], codes.FACILITY_CODE_QUALIFIER)
                self.assertEqual(parts[2], codes.CLAIM_FREQUENCY_ORIGINAL)

    def test_billing_npi_is_ten_digits(self):
        for segment in self.body:
            if segment.segment_id == "NM1" and segment.element(1) == "85":
                self.assertEqual(segment.element(8), codes.QUALIFIER_NPI)
                self.assertRegex(segment.element(9), r"^\d{10}$")


class ValidatorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        create_test_claims()
        cls.contexts = context.build_many(Claim.objects.all())

    def test_every_claim_produces_a_context(self):
        self.assertTrue(self.contexts)
        for ctx in self.contexts:
            self.assertIsNotNone(ctx.claim)

    def test_issue_carries_a_tag_separate_from_its_message(self):
        issue = validators.Issue("2010AA N403", "billing ZIP is short")
        self.assertEqual(issue.tag, "2010AA N403")
        self.assertEqual(str(issue), "[2010AA N403] billing ZIP is short")

    def test_line_issues_render_the_line_number(self):
        issue = validators.Issue("2400 SV101", "no procedure code", 3)
        self.assertIn("line 3", str(issue))

    def test_filter_accepts_a_tag_with_or_without_brackets(self):
        issues = [validators.Issue("2010BB N403", "empty"),
                  validators.Issue("2400 SV101", "empty")]
        self.assertEqual(len(validators.filter_issues(issues, ["2010BB"])), 1)
        self.assertEqual(len(validators.filter_issues(issues, ["[2010BB]"])), 1)

    def test_summarise_groups_by_tag(self):
        issues = [validators.Issue("A", "x"), validators.Issue("A", "y"),
                  validators.Issue("B", "z")]
        self.assertEqual(validators.summarise(issues), {"A": 2, "B": 1})

    def test_totals_check_catches_an_imbalance(self):
        ctx = self.contexts[0]
        original = ctx.claim.total_charge_amount
        ctx.claim.total_charge_amount = original + 1
        try:
            tags = [i.tag for i in validators.validate_totals(ctx)]
            self.assertIn("2300 CLM02", tags)
        finally:
            ctx.claim.total_charge_amount = original

    def test_a_context_and_a_builder_agree_on_the_relationship(self):
        for ctx in self.contexts:
            body, _ = builders.build_body([ctx])
            sbr = next((s for s in body if s.segment_id == "SBR"), None)
            if sbr is not None and ctx.patient_is_subscriber:
                self.assertEqual(sbr.element(2), codes.RELATIONSHIP_SELF)
