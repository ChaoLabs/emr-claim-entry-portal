from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from edi.management.commands.seed_trading_partner import ensure_demo_partner

from claims.models import (
    Claim,
    ClaimAuditEvent,
    ClaimCoverage,
    ClaimDiagnosis,
    ClaimProvider,
    Icd10Code,
    InsurancePolicy,
    InsuredParty,
    NpiReference,
    Patient,
    Payer,
    ProcedureCode,
    Provider,
    ReferenceDataUpdate,
    ServiceLine,
    ServiceLineDiagnosis,
)


class Command(BaseCommand):
    help = "Seed fictional CMS-1500 development claim data. Do not use real PHI."

    # These are fixed synthetic fixture values, not a lookup or a ZIP padding rule.
    DEMO_BILLING_ZIP = "27701-1234"
    DEMO_BILLING_EIN = "123456789"
    SEED_EVENT = "Fictional sample claim created by seed_sample_claims command."

    def _is_seeded_claim(self, claim):
        return claim.audit_events.filter(
            event_type="sample_created", event_description=self.SEED_EVENT,
            changed_by="system",
        ).exists()

    def _repair_legacy_billing_fixture(self, claim):
        """Upgrade only the untouched old demo record; never guess real values."""
        provider_ids = list(claim.claim_providers.filter(
            provider_role=ClaimProvider.ROLE_BILLING,
        ).values_list("provider_id", flat=True))
        if len(provider_ids) != 1:
            return False
        # Lock before reading sentinel values so a concurrent Admin update cannot
        # be overwritten based on a stale snapshot of the old fixture.
        provider = Provider.objects.select_for_update().get(pk=provider_ids[0])
        # Match the full identifying fixture, including BOTH legacy placeholders.
        # A partially corrected or otherwise edited provider is left untouched.
        expected = {
            "organization_name": "EMRTS Demo Clinic", "first_name": "", "last_name": "",
            "npi": "1234567893", "taxonomy_code": "207Q00000X",
            "tax_id": "DEMO-TAX-ID", "address_line_1": "200 Demo Provider Blvd",
            "address_line_2": "", "city": "Durham", "state": "NC", "zip_code": "27701",
            "phone_number": "555-0200",
        }
        if any(getattr(provider, field) != value for field, value in expected.items()):
            return False
        if (ClaimProvider.objects.filter(provider=provider).exclude(claim=claim).exists()
                or ServiceLine.objects.filter(rendering_provider=provider).exclude(claim=claim).exists()):
            return False
        # Updating this shared identity must not alter a record already used by
        # any other claim. Exact archived X12 documents are never rewritten.
        provider.zip_code = self.DEMO_BILLING_ZIP
        provider.tax_id = self.DEMO_BILLING_EIN
        provider.save(update_fields=["zip_code", "tax_id", "updated_at"])
        ClaimAuditEvent.objects.create(
            claim=claim, event_type="sample_export_prepared", changed_by="system",
            event_description=(
                "Replaced legacy sample billing ZIP and tax-ID placeholders with fixed "
                "fictional ZIP+4 and EIN fixture values for test 837P generation. "
                "These values are not verified provider data; existing X12 archives are unchanged."
            ),
        )
        return True

    @transaction.atomic
    def handle(self, *args, **options):
        existing_claim = Claim.objects.select_for_update().filter(claim_number="CLM-DEMO-001").first()
        if existing_claim and not self._is_seeded_claim(existing_claim):
            self.stdout.write(self.style.WARNING(
                "CLM-DEMO-001 has no matching sample provenance; no sample data was changed."
            ))
            return
        now = timezone.now()
        update_defaults = {
            "source_name": "EMRTS development reference subset",
            "source_url": "",
            "status": ReferenceDataUpdate.STATUS_COMPLETED,
            "started_at": now,
            "completed_at": now,
            "triggered_by": "seed_sample_claims",
            "notes": "Development-only subset for UI validation; not a production source download.",
        }

        npi_update, _ = ReferenceDataUpdate.objects.update_or_create(
            dataset_name=ReferenceDataUpdate.DATASET_NPPES,
            source_version="development-subset-2026",
            defaults={**update_defaults, "records_loaded": 2},
        )
        icd_update, _ = ReferenceDataUpdate.objects.update_or_create(
            dataset_name=ReferenceDataUpdate.DATASET_ICD10,
            source_version="development-subset-2026",
            defaults={**update_defaults, "records_loaded": 2},
        )
        procedure_update, _ = ReferenceDataUpdate.objects.update_or_create(
            dataset_name=ReferenceDataUpdate.DATASET_PROCEDURE,
            source_version="development-subset-2026",
            defaults={**update_defaults, "records_loaded": 1},
        )

        billing_npi, _ = NpiReference.objects.update_or_create(
            npi="1234567893",
            defaults={
                "entity_type": NpiReference.ENTITY_ORGANIZATION,
                "provider_name": "EMRTS Demo Clinic",
                "primary_taxonomy_code": "207Q00000X",
                "city": "Durham",
                "state": "NC",
                "zip_code": "27701",
                "is_active": True,
                "source_update": npi_update,
            },
        )
        rendering_npi, _ = NpiReference.objects.update_or_create(
            npi="1098765432",
            defaults={
                "entity_type": NpiReference.ENTITY_INDIVIDUAL,
                "provider_name": "Jordan Lee",
                "primary_taxonomy_code": "207Q00000X",
                "city": "Durham",
                "state": "NC",
                "zip_code": "27701",
                "is_active": True,
                "source_update": npi_update,
            },
        )

        low_back_pain, _ = Icd10Code.objects.update_or_create(
            code="M54.50",
            defaults={
                "short_description": "Low back pain, unspecified",
                "long_description": "Low back pain, unspecified.",
                "is_active": True,
                "source_update": icd_update,
            },
        )
        Icd10Code.objects.update_or_create(
            code="R51.9",
            defaults={
                "short_description": "Headache, unspecified",
                "long_description": "Headache, unspecified.",
                "is_active": True,
                "source_update": icd_update,
            },
        )

        office_visit, _ = ProcedureCode.objects.update_or_create(
            code="99213",
            defaults={
                "code_system": ProcedureCode.SYSTEM_CPT,
                "short_description": "Established patient office visit",
                "long_description": "Development description for an established patient office visit.",
                "is_active": True,
                "source_update": procedure_update,
            },
        )

        # get_or_create preserves an administrator's existing configuration,
        # including a disabled partner, and never resets interchange counters.
        ensure_demo_partner()
        if existing_claim:
            repaired = self._repair_legacy_billing_fixture(existing_claim)
            self.stdout.write(self.style.SUCCESS(
                "Prepared the legacy fictional sample for test 837P generation."
            ) if repaired else self.style.WARNING(
                "Sample claim CLM-DEMO-001 already exists; saved claim data was preserved."
            ))
            return

        patient = Patient.objects.create(
            first_name="Alex",
            last_name="Morgan",
            date_of_birth="1985-04-12",
            sex="unknown",
            address_line_1="100 Demo Patient Ave",
            city="Raleigh",
            state="NC",
            zip_code="27601",
            phone_number="555-0100",
        )

        insured = InsuredParty.objects.create(
            first_name="Alex",
            last_name="Morgan",
            date_of_birth="1985-04-12",
            sex="unknown",
            address_line_1="100 Demo Patient Ave",
            city="Raleigh",
            state="NC",
            zip_code="27601",
        )

        payer = Payer.objects.create(
            payer_name="Medicare",
            payer_type=Payer.PAYER_TYPE_MEDICARE,
            payer_identifier="CMS-DEMO",
            medicare_administrative_contractor="Demo MAC",
            address_line_1="7500 Demo Payer Drive",
            city="Baltimore",
            state="MD",
            zip_code="21244",
            zip_code_extension="1850",
        )

        billing_provider = Provider.objects.create(
            organization_name="EMRTS Demo Clinic",
            npi="1234567893",
            npi_reference=billing_npi,
            taxonomy_code="207Q00000X",
            tax_id=self.DEMO_BILLING_EIN,
            address_line_1="200 Demo Provider Blvd",
            city="Durham",
            state="NC",
            zip_code=self.DEMO_BILLING_ZIP,
            phone_number="555-0200",
        )

        rendering_provider = Provider.objects.create(
            first_name="Jordan",
            last_name="Lee",
            npi="1098765432",
            npi_reference=rendering_npi,
            taxonomy_code="207Q00000X",
            city="Durham",
            state="NC",
        )

        insurance_policy = InsurancePolicy.objects.create(
            insured_party=insured,
            payer=payer,
            member_id="DEMO-MBI-0001",
            group_number="DEMO-GROUP",
            plan_name="Demo Medicare Professional Coverage",
            policy_type=InsurancePolicy.POLICY_TYPE_MEDICARE,
            is_active=True,
        )

        claim = Claim.objects.create(
            claim_number="CLM-DEMO-001",
            patient=patient,
            status=Claim.STATUS_READY_FOR_REVIEW,
            validation_status="reference_validated",
            validation_message="Fictional sample claim linked to the active development reference subset.",
            service_start_date="2026-07-26",
            service_end_date="2026-07-26",
            total_charge_amount=Decimal("125.00"),
        )

        ClaimCoverage.objects.create(
            claim=claim,
            insurance_policy=insurance_policy,
            payer_sequence=ClaimCoverage.PAYER_SEQUENCE_PRIMARY,
            relationship_to_patient="self",
            assignment_of_benefits=True,
            release_of_information=True,
        )

        ClaimProvider.objects.create(
            claim=claim,
            provider=billing_provider,
            provider_role=ClaimProvider.ROLE_BILLING,
        )

        ClaimProvider.objects.create(
            claim=claim,
            provider=rendering_provider,
            provider_role=ClaimProvider.ROLE_RENDERING,
        )

        diagnosis = ClaimDiagnosis.objects.create(
            claim=claim,
            diagnosis_code="M54.50",
            icd10_reference=low_back_pain,
            diagnosis_order=1,
            description="Low back pain, unspecified",
        )

        line = ServiceLine.objects.create(
            claim=claim,
            service_from_date="2026-07-26",
            service_to_date="2026-07-26",
            place_of_service="11",
            procedure_code="99213",
            procedure_reference=office_visit,
            rendering_provider=rendering_provider,
            charge_amount=Decimal("125.00"),
            units=1,
        )

        ServiceLineDiagnosis.objects.create(service_line=line, diagnosis=diagnosis, position=1)

        ClaimAuditEvent.objects.create(
            claim=claim,
            event_type="sample_created",
            event_description=self.SEED_EVENT,
            changed_by="system",
        )

        self.stdout.write(self.style.SUCCESS("Created sample claim CLM-DEMO-001."))
