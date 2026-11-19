"""Code syntax, not membership in a complete or licensed reference dataset.

CMS ICD-10-CM structure and NPI check-digit rules; CPT shapes include
Category II/III, PLA and administrative MAAA, plus HCPCS Level II.
These checks do not establish issuance, billability, coverage or credentials.
"""
import re

from django.core.exceptions import ValidationError


def _ascii(value, message):
    value = str(value or "").strip()
    if not value.isascii():
        raise ValidationError(message)
    return value.upper()


def normalize_diagnosis(value):
    message = "Enter an ICD-10-CM code of 3–7 letters/digits, with an optional decimal after character 3 (for example, E11.9 or E119)."
    code = _ascii(value, message)
    if not re.fullmatch(r"[A-Z][0-9][A-Z0-9](?:\.?[A-Z0-9]{1,4})?", code):
        raise ValidationError(message)
    compact = code.replace(".", "")
    return compact[:3] + ("." + compact[3:] if len(compact) > 3 else "")


def normalize_procedure(value):
    message = "Enter a 5-character CPT / HCPCS code. Enter modifiers separately."
    code = _ascii(value, message)
    if not re.fullmatch(r"(?:[0-9]{5}|[0-9]{4}[FTUM]|[A-Z][0-9]{4})", code):
        raise ValidationError(message)
    return code


def normalize_npi(value):
    message = "NPI must contain exactly 10 ASCII digits."
    npi = _ascii(value, message)
    if not re.fullmatch(r"[0-9]{10}", npi):
        raise ValidationError(message)
    # CMS: calculate as if the health identifier prefix 80840 were present.
    total = 0
    for index, digit in enumerate(reversed("80840" + npi)):
        number = int(digit) * (2 if index % 2 else 1)
        total += number // 10 + number % 10
    if total % 10:
        raise ValidationError("NPI check digit is invalid. Check the 10-digit NPI with the provider.")
    return npi
