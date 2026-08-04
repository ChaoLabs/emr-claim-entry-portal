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


class InsurancePolicy(TimeStampedModel):
    POLICY_TYPE_MEDICARE = "medicare"
    POLICY_TYPE_MEDICAID = "medicaid"
    POLICY_TYPE_COMMERCIAL = "commercial"
    POLICY_TYPE_TRICARE = "tricare"
    POLICY_TYPE_OTHER = "other"

    POLICY_TYPE_CHOICES = [
        (POLICY_TYPE_MEDICARE, "Medicare"),
        (POLICY_TYPE_MEDICAID, "Medicaid"),
        (POLICY_TYPE_COMMERCIAL, "Commercial"),
        (POLICY_TYPE_TRICARE, "TRICARE"),
        (POLICY_TYPE_OTHER, "Other"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    insured_party = models.ForeignKey(
        InsuredParty,
        on_delete=models.PROTECT,
        related_name="insurance_policies",
    )
    payer = models.ForeignKey(
        Payer,
        on_delete=models.PROTECT,
        related_name="insurance_policies",
    )

    member_id = models.CharField(max_length=100, blank=True)
    group_number = models.CharField(max_length=100, blank=True)
    plan_name = models.CharField(max_length=255, blank=True)
    policy_type = models.CharField(max_length=50, choices=POLICY_TYPE_CHOICES, default=POLICY_TYPE_MEDICARE)

    effective_start_date = models.DateField(null=True, blank=True)
    effective_end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "insurance policies"
        ordering = ["insured_party", "payer", "member_id"]
        indexes = [
            models.Index(fields=["insured_party"]),
            models.Index(fields=["member_id"]),
            models.Index(fields=["policy_type"]),
            models.Index(fields=["is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["insured_party", "payer", "member_id", "group_number"],
                condition=(~models.Q(member_id="") | ~models.Q(group_number="")),
                name="unique_policy_when_member_or_group_present",
            ),
        ]

    def __str__(self):
        policy_label = self.member_id or self.group_number or "policy"
        return f"{self.insured_party} - {self.payer.payer_name} - {policy_label}"


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
            models.Index(fields=["service_start_date", "service_end_date"]),
        ]

    def __str__(self):
        return self.claim_number or f"Claim {self.id}"


class ClaimCoverage(TimeStampedModel):
    PAYER_SEQUENCE_PRIMARY = "primary"
    PAYER_SEQUENCE_SECONDARY = "secondary"
    PAYER_SEQUENCE_TERTIARY = "tertiary"
    PAYER_SEQUENCE_OTHER = "other"

    PAYER_SEQUENCE_CHOICES = [
        (PAYER_SEQUENCE_PRIMARY, "Primary"),
        (PAYER_SEQUENCE_SECONDARY, "Secondary"),
        (PAYER_SEQUENCE_TERTIARY, "Tertiary"),
        (PAYER_SEQUENCE_OTHER, "Other"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="coverages")
    insurance_policy = models.ForeignKey(
        InsurancePolicy,
        on_delete=models.PROTECT,
        related_name="claim_coverages",
    )

    payer_sequence = models.CharField(
        max_length=50,
        choices=PAYER_SEQUENCE_CHOICES,
        default=PAYER_SEQUENCE_PRIMARY,
    )
    relationship_to_patient = models.CharField(max_length=50, blank=True)
    assignment_of_benefits = models.BooleanField(default=True)
    release_of_information = models.BooleanField(default=True)
    prior_authorization_number = models.CharField(max_length=100, blank=True)
    other_payer_paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["claim", "payer_sequence"]
        indexes = [
            models.Index(fields=["claim"]),
            models.Index(fields=["insurance_policy"]),
            models.Index(fields=["payer_sequence"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["claim", "payer_sequence"],
                name="unique_claim_payer_sequence",
            ),
            models.UniqueConstraint(
                fields=["claim", "insurance_policy"],
                name="unique_claim_insurance_policy",
            ),
        ]

    def __str__(self):
        return f"{self.claim} - {self.payer_sequence} - {self.insurance_policy}"


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
