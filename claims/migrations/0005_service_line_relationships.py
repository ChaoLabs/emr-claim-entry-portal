from django.core.validators import MinValueValidator
from django.db import migrations, models
import django.db.models.deletion


def forward_relationships(apps, schema_editor):
    """Fail atomically rather than invent or discard a historical association."""
    alias = schema_editor.connection.alias
    Line = apps.get_model("claims", "ServiceLine")
    Diagnosis = apps.get_model("claims", "ClaimDiagnosis")
    Link = apps.get_model("claims", "ServiceLineDiagnosis")
    Modifier = apps.get_model("claims", "ServiceLineModifier")
    for line in Line.objects.using(alias).iterator():
        diagnoses = dict(Diagnosis.objects.using(alias).filter(claim_id=line.claim_id).values_list("diagnosis_order", "pk"))
        seen_pointers, seen_modifiers = set(), set()
        for position in range(1, 5):
            pointer = getattr(line, f"diagnosis_pointer_{position}")
            if pointer is not None:
                if pointer not in diagnoses or pointer in seen_pointers:
                    raise RuntimeError(
                        f"Cannot migrate service line {line.pk}: diagnosis pointer slot {position} "
                        "is missing from this claim or repeated. Correct the legacy record and rerun migrate."
                    )
                Link.objects.using(alias).create(service_line_id=line.pk, diagnosis_id=diagnoses[pointer], position=position)
                seen_pointers.add(pointer)
            code = getattr(line, f"modifier_{position}")
            if code:
                if code in seen_modifiers:
                    raise RuntimeError(
                        f"Cannot migrate service line {line.pk}: duplicate modifier in slot {position}. "
                        "Correct the legacy record and rerun migrate."
                    )
                Modifier.objects.using(alias).create(service_line_id=line.pk, code=code, position=position)
                seen_modifiers.add(code)


def backward_relationships(apps, schema_editor):
    """Restoring fixed slots is allowed only when every value can be preserved."""
    alias = schema_editor.connection.alias
    Line = apps.get_model("claims", "ServiceLine")
    Link = apps.get_model("claims", "ServiceLineDiagnosis")
    Modifier = apps.get_model("claims", "ServiceLineModifier")
    if Link.objects.using(alias).filter(position__gt=4).exists() or Modifier.objects.using(alias).filter(position__gt=4).exists():
        raise RuntimeError("Cannot reverse migration: a service line has values beyond four slots. Keep the normalized schema; no values have been truncated.")
    for line in Line.objects.using(alias).iterator():
        values = {f"diagnosis_pointer_{i}": None for i in range(1, 5)}
        values.update({f"modifier_{i}": "" for i in range(1, 5)})
        for link in Link.objects.using(alias).filter(service_line_id=line.pk).select_related("diagnosis"):
            if link.diagnosis.claim_id != line.claim_id:
                raise RuntimeError(f"Cannot reverse migration: service line {line.pk} has a cross-claim diagnosis.")
            values[f"diagnosis_pointer_{link.position}"] = link.diagnosis.diagnosis_order
        for modifier in Modifier.objects.using(alias).filter(service_line_id=line.pk):
            values[f"modifier_{modifier.position}"] = modifier.code
        Line.objects.using(alias).filter(pk=line.pk).update(**values)


class Migration(migrations.Migration):
    dependencies = [("claims", "0004_payer_mailing_address")]
    operations = [
        migrations.CreateModel(
            name="ServiceLineDiagnosis",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position", models.PositiveIntegerField(validators=[MinValueValidator(1)])),
                ("diagnosis", models.ForeignKey(on_delete=django.db.models.deletion.RESTRICT, related_name="service_line_links", to="claims.claimdiagnosis")),
                ("service_line", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="diagnosis_links", to="claims.serviceline")),
            ],
            options={
                "ordering": ["position"],
                "constraints": [
                    models.UniqueConstraint(fields=("service_line", "diagnosis"), name="unique_line_diagnosis"),
                    models.UniqueConstraint(fields=("service_line", "position"), name="unique_line_diagnosis_position"),
                    models.CheckConstraint(condition=models.Q(position__gte=1), name="line_diagnosis_position_positive"),
                ],
            },
        ),
        migrations.CreateModel(
            name="ServiceLineModifier",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=10)),
                ("position", models.PositiveIntegerField(validators=[MinValueValidator(1)])),
                ("service_line", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="modifiers", to="claims.serviceline")),
            ],
            options={
                "ordering": ["position"],
                "constraints": [
                    models.UniqueConstraint(fields=("service_line", "position"), name="unique_line_modifier_position"),
                    models.UniqueConstraint(fields=("service_line", "code"), name="unique_line_modifier_code"),
                    models.CheckConstraint(condition=models.Q(position__gte=1), name="line_modifier_position_positive"),
                ],
            },
        ),
        migrations.AddField(model_name="serviceline", name="diagnoses", field=models.ManyToManyField(blank=True, related_name="service_lines", through="claims.ServiceLineDiagnosis", to="claims.claimdiagnosis")),
        migrations.RunPython(forward_relationships, backward_relationships),
        *[migrations.RemoveField(model_name="serviceline", name=f"diagnosis_pointer_{i}") for i in range(1, 5)],
        *[migrations.RemoveField(model_name="serviceline", name=f"modifier_{i}") for i in range(1, 5)],
    ]
