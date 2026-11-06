from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models.deletion import RestrictedError
from django.test import TestCase, TransactionTestCase

from .models import Claim, ClaimDiagnosis, Patient, ServiceLine, ServiceLineDiagnosis, ServiceLineModifier


class ServiceLineRelationshipTests(TestCase):
    def setUp(self):
        self.patient = Patient.objects.create(first_name="Synthetic", last_name="Patient")
        self.claim = Claim.objects.create(patient=self.patient, claim_number="LINK-TEST")
        self.line = ServiceLine.objects.create(claim=self.claim, procedure_code="99213")
        self.diagnoses = [ClaimDiagnosis.objects.create(claim=self.claim, diagnosis_code=f"TEST{i}", diagnosis_order=i) for i in range(1, 7)]

    def test_more_than_four_links_and_modifiers_have_explicit_order(self):
        for position, diagnosis in enumerate(reversed(self.diagnoses), 1):
            ServiceLineDiagnosis.objects.create(service_line=self.line, diagnosis=diagnosis, position=position)
            ServiceLineModifier.objects.create(service_line=self.line, code=f"M{position}", position=position)
        self.assertEqual(self.line.diagnosis_pointers, [6, 5, 4, 3, 2, 1])
        self.assertEqual(self.line.modifier_codes, ["M1", "M2", "M3", "M4", "M5", "M6"])
        other_line = ServiceLine.objects.create(claim=self.claim, procedure_code="99214")
        ServiceLineDiagnosis.objects.create(service_line=other_line, diagnosis=self.diagnoses[0], position=1)
        self.assertEqual(self.diagnoses[0].service_lines.count(), 2)

    def test_cross_claim_link_and_reparenting_are_blocked(self):
        other = Claim.objects.create(patient=self.patient, claim_number="OTHER-TEST")
        foreign = ClaimDiagnosis.objects.create(claim=other, diagnosis_order=1, diagnosis_code="TEST")
        with self.assertRaises(ValidationError):
            ServiceLineDiagnosis.objects.create(service_line=self.line, diagnosis=foreign, position=1)
        ServiceLineDiagnosis.objects.create(service_line=self.line, diagnosis=self.diagnoses[0], position=1)
        self.line.claim = other
        with self.assertRaises(ValidationError):
            self.line.save()
        self.diagnoses[0].claim = other
        with self.assertRaises(ValidationError):
            self.diagnoses[0].save()

    def test_m2m_add_and_reverse_add_reject_foreign_claim(self):
        other = Claim.objects.create(patient=self.patient, claim_number="M2M-OTHER")
        foreign = ClaimDiagnosis.objects.create(claim=other, diagnosis_order=1, diagnosis_code="FOREIGN")
        with self.assertRaises(ValidationError), transaction.atomic():
            self.line.diagnoses.add(foreign, through_defaults={"position": 1})
        with self.assertRaises(ValidationError), transaction.atomic():
            foreign.service_lines.add(self.line, through_defaults={"position": 1})
        self.line.diagnoses.add(self.diagnoses[0], through_defaults={"position": 1})
        second_line = ServiceLine.objects.create(claim=self.claim, procedure_code="99214")
        self.diagnoses[0].service_lines.add(second_line, through_defaults={"position": 1})
        self.assertEqual(self.line.diagnosis_pointers, [1])
        self.assertEqual(second_line.diagnosis_pointers, [1])
        self.assertEqual(foreign.service_lines.count(), 0)

    def test_m2m_set_is_atomic_and_uses_persisted_claim_ownership(self):
        self.line.diagnoses.add(self.diagnoses[0], through_defaults={"position": 1})
        other = Claim.objects.create(patient=self.patient, claim_number="M2M-SET-OTHER")
        foreign = ClaimDiagnosis.objects.create(claim=other, diagnosis_order=1, diagnosis_code="FOREIGN")
        self.line.claim = other  # An unsaved edit must not fool the relationship guard.
        with self.assertRaises(ValidationError), transaction.atomic():
            self.line.diagnoses.set([foreign], clear=True, through_defaults={"position": 1})
        self.assertEqual(self.line.diagnosis_pointers, [1])

    def test_linked_diagnosis_is_protected_but_whole_claim_can_be_deleted(self):
        ServiceLineDiagnosis.objects.create(service_line=self.line, diagnosis=self.diagnoses[0], position=1)
        with self.assertRaises(RestrictedError):
            self.diagnoses[0].delete()
        self.claim.delete()
        self.assertEqual(ServiceLineDiagnosis.objects.count(), 0)

    def test_duplicate_pointer_and_position_are_rejected(self):
        ServiceLineDiagnosis.objects.create(service_line=self.line, diagnosis=self.diagnoses[0], position=1)
        with self.assertRaises(ValidationError):
            ServiceLineDiagnosis.objects.create(service_line=self.line, diagnosis=self.diagnoses[0], position=2)
        with self.assertRaises(ValidationError):
            ServiceLineDiagnosis.objects.create(service_line=self.line, diagnosis=self.diagnoses[1], position=1)
        with self.assertRaises(ValidationError):
            ServiceLineModifier.objects.create(service_line=self.line, code="25", position=0)
        # Database constraints also guard writes that intentionally skip model validation.
        with self.assertRaises(IntegrityError), transaction.atomic():
            ServiceLineDiagnosis.objects.bulk_create([ServiceLineDiagnosis(service_line=self.line, diagnosis=self.diagnoses[0], position=2)])


class ServiceLineMigrationTests(TransactionTestCase):
    old_target = [("claims", "0004_payer_mailing_address")]
    new_target = [("claims", "0005_service_line_relationships")]

    def setUp(self):
        executor = MigrationExecutor(connection)
        self.latest_targets = executor.loader.graph.leaf_nodes()
        executor.migrate(self.old_target)
        self.old_apps = executor.loader.project_state(self.old_target).apps
        PatientOld = self.old_apps.get_model("claims", "Patient")
        ClaimOld = self.old_apps.get_model("claims", "Claim")
        DiagnosisOld = self.old_apps.get_model("claims", "ClaimDiagnosis")
        patient = PatientOld.objects.create(first_name="Synthetic", last_name="Migration")
        self.claim = ClaimOld.objects.create(patient=patient, claim_number="MIGRATION-TEST")
        self.diag1 = DiagnosisOld.objects.create(claim=self.claim, diagnosis_order=1, diagnosis_code="M54.50")
        self.diag2 = DiagnosisOld.objects.create(claim=self.claim, diagnosis_order=2, diagnosis_code="R51.9")

    def tearDown(self):
        # Remove test data while still at its current historical schema, so a deliberately
        # malformed fixture cannot prevent restoring the test database schema.
        with connection.cursor() as cursor:
            tables = connection.introspection.table_names(cursor)
        with connection.constraint_checks_disabled():
            for name in ("claims_servicelinediagnosis", "claims_servicelinemodifier", "claims_serviceline"):
                if name in tables:
                    with connection.cursor() as cursor:
                        cursor.execute(f'DELETE FROM "{name}"')
        MigrationExecutor(connection).migrate(self.latest_targets)
        super().tearDown()

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def test_existing_slots_migrate_without_losing_order_and_reverse_exactly(self):
        OldLine = self.old_apps.get_model("claims", "ServiceLine")
        line = OldLine.objects.create(claim=self.claim, procedure_code="99213", diagnosis_pointer_1=2, diagnosis_pointer_3=1, modifier_2="25", modifier_4="GT")
        new_apps = self.migrate(self.new_target)
        Link = new_apps.get_model("claims", "ServiceLineDiagnosis")
        Modifier = new_apps.get_model("claims", "ServiceLineModifier")
        self.assertEqual(list(Link.objects.filter(service_line_id=line.pk).values_list("position", "diagnosis__diagnosis_order")), [(1, 2), (3, 1)])
        self.assertEqual(list(Modifier.objects.filter(service_line_id=line.pk).values_list("position", "code")), [(2, "25"), (4, "GT")])
        old_apps = self.migrate(self.old_target)
        restored = old_apps.get_model("claims", "ServiceLine").objects.get(pk=line.pk)
        self.assertEqual([getattr(restored, f"diagnosis_pointer_{i}") for i in range(1, 5)], [2, None, 1, None])
        self.assertEqual([getattr(restored, f"modifier_{i}") for i in range(1, 5)], ["", "25", "", "GT"])

    def test_invalid_legacy_pointer_stops_migration_without_data_loss(self):
        OldLine = self.old_apps.get_model("claims", "ServiceLine")
        line = OldLine.objects.create(claim=self.claim, procedure_code="99213", diagnosis_pointer_1=99)
        with self.assertRaisesRegex(RuntimeError, "Cannot migrate service line"):
            self.migrate(self.new_target)
        self.assertEqual(OldLine.objects.get(pk=line.pk).diagnosis_pointer_1, 99)

    def test_reverse_refuses_to_truncate_new_fifth_value(self):
        line = self.old_apps.get_model("claims", "ServiceLine").objects.create(claim=self.claim, procedure_code="99213")
        new_apps = self.migrate(self.new_target)
        Modifier = new_apps.get_model("claims", "ServiceLineModifier")
        Modifier.objects.create(service_line_id=line.pk, code="25", position=5)
        with self.assertRaisesRegex(RuntimeError, "beyond four slots"):
            self.migrate(self.old_target)
        self.assertEqual(Modifier.objects.get(service_line_id=line.pk).position, 5)
