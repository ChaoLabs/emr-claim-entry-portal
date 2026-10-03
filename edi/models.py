import random
import time
import uuid

from django.core.validators import RegexValidator
from django.db import OperationalError, models, transaction

ID_QUALIFIER_VALIDATOR = RegexValidator(
    regex=r"^[A-Za-z0-9]{2}$",
    message="Interchange ID qualifier must be two characters.",
)


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TradingPartner(TimeStamped):
    USAGE_TEST = "T"
    USAGE_PRODUCTION = "P"
    USAGE_CHOICES = [(USAGE_TEST, "Test"), (USAGE_PRODUCTION, "Production")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)

    isa_sender_qualifier = models.CharField(
        max_length=2, default="ZZ", validators=[ID_QUALIFIER_VALIDATOR]
    )
    isa_sender_id = models.CharField(max_length=15)
    isa_receiver_qualifier = models.CharField(
        max_length=2, default="ZZ", validators=[ID_QUALIFIER_VALIDATOR]
    )
    isa_receiver_id = models.CharField(max_length=15)
    usage_indicator = models.CharField(max_length=1, choices=USAGE_CHOICES, default=USAGE_TEST)

    gs_sender_code = models.CharField(max_length=15)
    gs_receiver_code = models.CharField(max_length=15)

    submitter_name = models.CharField(max_length=60)
    submitter_id = models.CharField(max_length=80)
    submitter_contact_name = models.CharField(max_length=60)
    submitter_contact_phone = models.CharField(max_length=20, blank=True)

    receiver_name = models.CharField(max_length=60)
    receiver_id = models.CharField(max_length=80)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_usage_indicator_display()})"


class ControlNumber(TimeStamped):
    LEVEL_INTERCHANGE = "interchange"
    LEVEL_GROUP = "group"
    LEVEL_TRANSACTION = "transaction"
    LEVEL_CHOICES = [
        (LEVEL_INTERCHANGE, "Interchange, ISA13"),
        (LEVEL_GROUP, "Functional group, GS06"),
        (LEVEL_TRANSACTION, "Transaction set, ST02"),
    ]

    MAX_VALUE = {
        LEVEL_INTERCHANGE: 999_999_999,
        LEVEL_GROUP: 999_999_999,
        LEVEL_TRANSACTION: 999_999_999,
    }

    trading_partner = models.ForeignKey(
        TradingPartner, on_delete=models.CASCADE, related_name="control_numbers"
    )
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES)
    current_value = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("trading_partner", "level")]
        ordering = ["trading_partner", "level"]

    def __str__(self):
        return f"{self.trading_partner.name} {self.level} at {self.current_value}"

    @classmethod
    def take(cls, trading_partner, level, attempts=8):
        if level not in cls.MAX_VALUE or attempts < 1:
            raise ValueError("invalid counter level or retry count")
        for attempt in range(attempts):
            try:
                with transaction.atomic():
                    counter, _ = cls.objects.select_for_update().get_or_create(
                        trading_partner=trading_partner, level=level
                    )
                    counter.current_value += 1
                    if counter.current_value > cls.MAX_VALUE[level]:
                        raise ValueError("control number exhausted; operator review is required")
                    counter.save(update_fields=["current_value", "updated_at"])
                    return counter.current_value
            except OperationalError:
                if attempt == attempts - 1:
                    raise
                time.sleep(0.05 * (2 ** attempt) + random.random() * 0.05)


class SubmissionBatch(TimeStamped):
    STATUS_GENERATED = "generated"
    STATUS_SENT = "sent"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_GENERATED, "Generated"),
        (STATUS_SENT, "Sent"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_REJECTED, "Rejected"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trading_partner = models.ForeignKey(
        TradingPartner, on_delete=models.PROTECT, related_name="batches"
    )
    file_name = models.CharField(max_length=255)
    isa_control_number = models.CharField(max_length=9)
    gs_control_number = models.CharField(max_length=9)
    st_control_number = models.CharField(max_length=9)
    claim_count = models.PositiveIntegerField(default=0)
    segment_count = models.PositiveIntegerField(default=0)
    total_charge_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_GENERATED)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.file_name} ({self.claim_count} claims)"


class BatchClaim(TimeStamped):
    batch = models.ForeignKey(SubmissionBatch, on_delete=models.CASCADE, related_name="claims")
    claim_id = models.UUIDField()
    claim_number = models.CharField(max_length=60)
    position = models.PositiveIntegerField()

    class Meta:
        unique_together = [("batch", "claim_id")]
        ordering = ["batch", "position"]
        indexes = [models.Index(fields=["claim_id"])]

    def __str__(self):
        return f"{self.claim_number} in {self.batch_id}"
