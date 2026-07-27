import uuid

from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Patient(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    sex = models.CharField(max_length=20, blank=True)

    address_line_1 = models.CharField(max_length=255, blank=True)
    address_line_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=2, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    phone_number = models.CharField(max_length=30, blank=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        indexes = [
            models.Index(fields=["last_name", "first_name"]),
            models.Index(fields=["date_of_birth"]),
        ]

    def __str__(self):
        return f"{self.last_name}, {self.first_name}"


class InsuredParty(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    sex = models.CharField(max_length=20, blank=True)

    relationship_to_patient = models.CharField(max_length=50, blank=True)
    insured_id_number = models.CharField(max_length=100, blank=True)
    group_number = models.CharField(max_length=100, blank=True)

    address_line_1 = models.CharField(max_length=255, blank=True)
    address_line_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=2, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)

    class Meta:
        verbose_name_plural = "insured parties"
        ordering = ["last_name", "first_name"]
        indexes = [
            models.Index(fields=["last_name", "first_name"]),
        ]

    def __str__(self):
        return f"{self.last_name}, {self.first_name}"


class Payer(TimeStampedModel):
    PAYER_TYPE_MEDICARE = "medicare"
    PAYER_TYPE_MEDICAID = "medicaid"
    PAYER_TYPE_COMMERCIAL = "commercial"
    PAYER_TYPE_OTHER = "other"

    PAYER_TYPE_CHOICES = [
        (PAYER_TYPE_MEDICARE, "Medicare"),
        (PAYER_TYPE_MEDICAID, "Medicaid"),
        (PAYER_TYPE_COMMERCIAL, "Commercial"),
        (PAYER_TYPE_OTHER, "Other"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    payer_name = models.CharField(max_length=255)
    payer_type = models.CharField(max_length=50, choices=PAYER_TYPE_CHOICES, default=PAYER_TYPE_MEDICARE)
    payer_identifier = models.CharField(max_length=100, blank=True)
    medicare_administrative_contractor = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["payer_name"]
        indexes = [
            models.Index(fields=["payer_identifier"]),
        ]

    def __str__(self):
        return self.payer_name


class Provider(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    organization_name = models.CharField(max_length=255, blank=True)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)

    npi = models.CharField(max_length=20, blank=True)
    taxonomy_code = models.CharField(max_length=20, blank=True)
    tax_id = models.CharField(max_length=50, blank=True)

    address_line_1 = models.CharField(max_length=255, blank=True)
    address_line_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=2, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    phone_number = models.CharField(max_length=30, blank=True)

    class Meta:
        ordering = ["organization_name", "last_name", "first_name"]
        indexes = [
            models.Index(fields=["npi"]),
            models.Index(fields=["taxonomy_code"]),
        ]

    def __str__(self):
        if self.organization_name:
            return self.organization_name
        return f"{self.last_name}, {self.first_name}".strip(", ")


class Claim(TimeStampedModel):
    STATUS_DRAFT = "draft"
    STATUS_READY_FOR_REVIEW = "ready_for_review"
    STATUS_VALIDATION_FAILED = "validation_failed"
    STATUS_READY_FOR_837P = "ready_for_837p"
    STATUS_SUBMITTED = "submitted"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_PAID = "paid"
    STATUS_DENIED = "denied"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_READY_FOR_REVIEW, "Ready for Review"),
        (STATUS_VALIDATION_FAILED, "Validation Failed"),
        (STATUS_READY_FOR_837P, "Ready for 837P"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_PAID, "Paid"),
        (STATUS_DENIED, "Denied"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    claim_number = models.CharField(max_length=100, unique=True, blank=True, null=True)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="claims")
    insured_party = models.ForeignKey(
        InsuredParty,
        on_delete=models.SET_NULL,
        related_name="claims",
        null=True,
        blank=True,
    )
    payer = models.ForeignKey(Payer, on_delete=models.PROTECT, related_name="claims")

    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    validation_status = models.CharField(max_length=50, blank=True)
    validation_message = models.TextField(blank=True)

    service_start_date = models.DateField(null=True, blank=True)
    service_end_date = models.DateField(null=True, blank=True)
    total_charge_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["patient"]),
            models.Index(fields=["payer"]),
            models.Index(fields=["service_start_date", "service_end_date"]),
        ]

    def __str__(self):
        return self.claim_number or f"Claim {self.id}"


class ClaimProvider(TimeStampedModel):
    ROLE_BILLING = "billing"
    ROLE_RENDERING = "rendering"
    ROLE_REFERRING = "referring"
    ROLE_FACILITY = "facility"

    ROLE_CHOICES = [
        (ROLE_BILLING, "Billing Provider"),
        (ROLE_RENDERING, "Rendering Provider"),
        (ROLE_REFERRING, "Referring Provider"),
        (ROLE_FACILITY, "Service Facility"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="claim_providers")
    provider = models.ForeignKey(Provider, on_delete=models.PROTECT, related_name="claim_providers")
    provider_role = models.CharField(max_length=50, choices=ROLE_CHOICES)

    class Meta:
        ordering = ["claim", "provider_role"]
        constraints = [
            models.UniqueConstraint(
                fields=["claim", "provider", "provider_role"],
                name="unique_claim_provider_role",
            )
        ]

    def __str__(self):
        return f"{self.claim} - {self.provider_role} - {self.provider}"


class ClaimDiagnosis(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="diagnoses")
    diagnosis_code = models.CharField(max_length=20)
    diagnosis_order = models.PositiveIntegerField()
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name_plural = "claim diagnoses"
        ordering = ["claim", "diagnosis_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["claim", "diagnosis_order"],
                name="unique_claim_diagnosis_order",
            )
        ]
        indexes = [
            models.Index(fields=["diagnosis_code"]),
        ]

    def __str__(self):
        return f"{self.claim} - {self.diagnosis_order}: {self.diagnosis_code}"


class ServiceLine(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="service_lines")

    service_from_date = models.DateField(null=True, blank=True)
    service_to_date = models.DateField(null=True, blank=True)
    place_of_service = models.CharField(max_length=10, blank=True)

    procedure_code = models.CharField(max_length=20)
    modifier_1 = models.CharField(max_length=10, blank=True)
    modifier_2 = models.CharField(max_length=10, blank=True)
    modifier_3 = models.CharField(max_length=10, blank=True)
    modifier_4 = models.CharField(max_length=10, blank=True)

    diagnosis_pointer_1 = models.PositiveIntegerField(null=True, blank=True)
    diagnosis_pointer_2 = models.PositiveIntegerField(null=True, blank=True)
    diagnosis_pointer_3 = models.PositiveIntegerField(null=True, blank=True)
    diagnosis_pointer_4 = models.PositiveIntegerField(null=True, blank=True)

    charge_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    units = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["claim", "service_from_date", "procedure_code"]
        indexes = [
            models.Index(fields=["claim"]),
            models.Index(fields=["procedure_code"]),
        ]

    def __str__(self):
        return f"{self.claim} - {self.procedure_code}"


class ClaimAuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="audit_events")
    event_type = models.CharField(max_length=100)
    event_description = models.TextField(blank=True)
    changed_by = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["claim"]),
            models.Index(fields=["event_type"]),
        ]

    def __str__(self):
        return f"{self.claim} - {self.event_type}"
