from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from claims.models import (
    Claim,
    ClaimAuditEvent,
    ClaimDiagnosis,
    ClaimProvider,
    InsuredParty,
    Patient,
    Payer,
    Provider,
    ServiceLine,
)


class Command(BaseCommand):
    help = "Seed fictional CMS-1500 development claim data. Do not use real PHI."

    @transaction.atomic
    def handle(self, *args, **options):
        if Claim.objects.filter(claim_number="CLM-DEMO-001").exists():
            self.stdout.write(self.style.WARNING("Sample claim CLM-DEMO-001 already exists."))
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
            relationship_to_patient="self",
            insured_id_number="DEMO-MBI-0001",
            group_number="DEMO-GROUP",
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
        )

        billing_provider = Provider.objects.create(
            organization_name="EMRTS Demo Clinic",
            npi="1234567893",
            taxonomy_code="207Q00000X",
            tax_id="DEMO-TAX-ID",
            address_line_1="200 Demo Provider Blvd",
            city="Durham",
            state="NC",
            zip_code="27701",
            phone_number="555-0200",
        )

        rendering_provider = Provider.objects.create(
            first_name="Jordan",
            last_name="Lee",
            npi="1098765432",
            taxonomy_code="207Q00000X",
            city="Durham",
            state="NC",
        )

        claim = Claim.objects.create(
            claim_number="CLM-DEMO-001",
            patient=patient,
            insured_party=insured,
            payer=payer,
            status=Claim.STATUS_READY_FOR_REVIEW,
            validation_status="capture_complete",
            validation_message="Fictional sample claim created for development review.",
            service_start_date="2026-07-26",
            service_end_date="2026-07-26",
            total_charge_amount=Decimal("125.00"),
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

        ClaimDiagnosis.objects.create(
            claim=claim,
            diagnosis_code="M54.50",
            diagnosis_order=1,
            description="Low back pain, unspecified",
        )

        ServiceLine.objects.create(
            claim=claim,
            service_from_date="2026-07-26",
            service_to_date="2026-07-26",
            place_of_service="11",
            procedure_code="99213",
            diagnosis_pointer_1=1,
            charge_amount=Decimal("125.00"),
            units=1,
        )

        ClaimAuditEvent.objects.create(
            claim=claim,
            event_type="sample_created",
            event_description="Fictional sample claim created by seed_sample_claims command.",
            changed_by="system",
        )

        self.stdout.write(self.style.SUCCESS("Created sample claim CLM-DEMO-001."))
