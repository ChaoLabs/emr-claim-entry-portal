"""Relationship validation for Django's bulk-writing many-to-many manager."""
from django.core.exceptions import ValidationError
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from .models import ClaimDiagnosis, ServiceLine, ServiceLineDiagnosis


@receiver(m2m_changed, sender=ServiceLineDiagnosis, dispatch_uid="claims.same_claim_diagnoses")
def validate_service_line_diagnoses(sender, instance, action, reverse, model, pk_set, using, **kwargs):
    if action != "pre_add" or not pk_set:
        return
    owner_model = ClaimDiagnosis if reverse else ServiceLine
    target_model = ServiceLine if reverse else ClaimDiagnosis
    # Read persisted ownership rather than trusting a potentially stale or edited
    # in-memory instance. RelatedManager.add() bypasses the through model's save().
    owner_claim = owner_model.objects.using(using).filter(pk=instance.pk).values_list("claim_id", flat=True).first()
    same_claim_count = target_model.objects.using(using).filter(pk__in=pk_set, claim_id=owner_claim).count()
    if owner_claim is None or same_claim_count != len(pk_set):
        raise ValidationError("Service lines and their diagnoses must belong to the same claim.")
