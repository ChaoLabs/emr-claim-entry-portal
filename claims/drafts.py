"""Persist incomplete CMS-1500 controls, without creating clinical/EDI records."""
import json
import re
import uuid

from django import forms
from django.core import signing
from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone

from .forms import CMS1500CaptureForm, DiagnosisCaptureFormSet, ServiceLineCaptureFormSet
from .models import CaptureDraft


ROW_SETS = {"diagnoses": DiagnosisCaptureFormSet, "service_lines": ServiceLineCaptureFormSet}
SIGNER = signing.Signer(salt="claims.capture-form.v1")
REPEATED = {"diagnosis_refs", "modifier_codes"}


class ChangedDraft(Exception):
    pass


def owner_key(request, *, create=False):
    """Use the existing login when available; otherwise keep a random key in the
    Django session. The cookie holds only the session ID, never form contents.
    """
    if request.user.is_authenticated:
        return str(request.user.pk)
    key = request.session.get("capture_owner")
    if not key and create:
        key = uuid.uuid4().hex
        request.session["capture_owner"] = key
    return f"session:{key}" if key else None


def owner_fields(owner):
    if owner and owner.startswith("session:"):
        return {"owner_id": None, "session_owner": owner.removeprefix("session:")}
    # With no owner, this matches no rows (enforced by the DB check constraint).
    return {"owner_id": owner, "session_owner": ""}


def form_token(owner, draft_id):
    return SIGNER.sign_object([owner, str(draft_id)])


def read_identity(post, owner, url_id):
    """A new form has a stable, unguessable, owner-bound ID before its first write."""
    if len(post.getlist("draft_token")) != 1 or len(post.getlist("draft_version")) != 1:
        raise ValueError("Missing draft identity.")
    try:
        token_owner, key = SIGNER.unsign_object(post["draft_token"])
        key = uuid.UUID(key)
    except (signing.BadSignature, ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid draft identity.") from exc
    if owner is None or token_owner != owner or (url_id is not None and url_id != key):
        raise Http404
    version = post["draft_version"]
    if not re.fullmatch(r"[0-9]{1,10}", version):
        raise ValueError("Invalid draft version.")
    return key, int(version)


def snapshot(data):
    """Whitelist the entry controls. Preserve order, deletions, blanks and repeated values."""
    counts = {}
    out = {}
    for prefix, formset in ROW_SETS.items():
        raw = data.get(f"{prefix}-TOTAL_FORMS", "1")
        if not re.fullmatch(r"[0-9]{1,3}", raw) or not 1 <= int(raw) <= formset.absolute_max:
            raise ValueError("Too many or invalid form rows. Reload the form and try again.")
        counts[prefix] = int(raw)
        out[f"{prefix}-TOTAL_FORMS"] = [raw]

    for key, values in data.lists():
        repeated = False
        if key not in CMS1500CaptureForm.base_fields:
            match = re.fullmatch(r"(diagnoses|service_lines)-([0-9]{1,3})-(\w+)", key)
            if not match:
                continue
            prefix, index, field = match.groups()
            if field != "DELETE" and field not in ROW_SETS[prefix].form.base_fields:
                continue
            if int(index) >= counts[prefix]:
                raise ValueError("A claim row is outside the submitted form.")
            repeated = field in REPEATED
        if len(values) > (200 if repeated else 1) or any(len(v) > 4096 or "\x00" in v for v in values):
            raise ValueError("A claim field exceeds the form limits.")
        out[key] = list(values)
    if len(json.dumps(out, ensure_ascii=False).encode("utf-8")) > 512 * 1024:
        raise ValueError("This draft is too large. Reduce the form size and try again.")
    return out


def _initial(payload, fields, prefix=""):
    values = {}
    for name, field in fields.items():
        raw = payload.get(f"{prefix}{name}", [])
        if name in REPEATED:
            values[name] = raw
        elif isinstance(field, forms.BooleanField):
            values[name] = field.to_python(raw[-1]) if raw else False
        elif raw:
            values[name] = raw[-1]
    if prefix:
        values["DELETE"] = forms.BooleanField(required=False).to_python(
            (payload.get(f"{prefix}DELETE") or [""])[-1]
        )
    return values


def resumed_forms(payload):
    """Unbound forms show partial input without reference checks or required-field errors."""
    form = CMS1500CaptureForm(initial=_initial(payload, CMS1500CaptureForm.base_fields))
    rows = {
        prefix: [
            _initial(payload, formset.form.base_fields, f"{prefix}-{i}-")
            for i in range(int(payload[f"{prefix}-TOTAL_FORMS"][0]))
        ]
        for prefix, formset in ROW_SETS.items()
    }
    diagnoses = DiagnosisCaptureFormSet(initial=rows["diagnoses"], prefix="diagnoses")
    choices = [
        (str(i), " — ".join(filter(None, (row["diagnosis_code"], row.get("description")))))
        for i, row in enumerate(rows["diagnoses"]) if row.get("diagnosis_code") and not row["DELETE"]
    ]
    lines = ServiceLineCaptureFormSet(
        initial=rows["service_lines"], prefix="service_lines", form_kwargs={"diagnosis_choices": choices}
    )
    return form, diagnoses, lines


@transaction.atomic
def apply_action(owner, key, version, payload, make_claim=None):
    """Claim the version first, then write the entire submission in the same transaction.

    The first POST reserves the signed UUID by insert. Later POSTs use a conditional
    update; even on databases without row-level SELECT FOR UPDATE, stale tabs cannot
    overwrite a newer version or materialize two claims from the same form.
    """
    if version == 0:
        try:
            with transaction.atomic():
                CaptureDraft.objects.create(pk=key, **owner_fields(owner), payload=payload)
        except IntegrityError:
            if not CaptureDraft.objects.filter(pk=key, **owner_fields(owner)).exists():
                raise
            raise ChangedDraft from None
    else:
        changed = CaptureDraft.objects.filter(pk=key, **owner_fields(owner), version=version, claim=None).update(
            version=version + 1, payload=payload, updated_at=timezone.now(),
        )
        if not changed:
            raise ChangedDraft
    if make_claim is not None:
        claim = make_claim()
        # Keep ownership and the replay receipt, not two copies of the capture data.
        CaptureDraft.objects.filter(pk=key, **owner_fields(owner)).update(claim=claim, payload={})
        return claim
    return None
