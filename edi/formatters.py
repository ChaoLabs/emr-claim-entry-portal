from decimal import Decimal
import re

ELEMENT = "*"
COMPOSITE = ":"
SEGMENT = "~"
REPETITION = "^"
RELEASE = ">"

DELIMITERS = (ELEMENT, COMPOSITE, SEGMENT, REPETITION, RELEASE)


def clean(text, max_length=None):
    if text is None:
        return ""
    out = str(text).strip().upper()
    for ch in DELIMITERS:
        out = out.replace(ch, " ")
    out = " ".join(out.split())
    return out[:max_length] if max_length else out


def diagnosis(value):
    """Wire format only: keep the original claim-time snapshot unchanged."""
    return clean(value).replace(".", "")


def digits(text):
    return "".join(ch for ch in str(text or "") if ch.isdigit())


def us_zip(value, extension=""):
    """Normalize a supported U.S. ZIP only after validating its entire value.

    This checks syntax, not whether USPS assigns the code to an address.
    Return None for missing or malformed values; never invent a ZIP+4 or
    remove letters to make an invalid value appear valid. A separate +4 field
    is accepted only with a five-digit base.
    """
    base = str(value or "").strip()
    extra = str(extension or "").strip()
    if extra:
        if re.fullmatch(r"[0-9]{5}", base) and re.fullmatch(r"[0-9]{4}", extra):
            return base + extra
        return None
    if re.fullmatch(r"(?:[0-9]{5}|[0-9]{9}|[0-9]{5}-[0-9]{4})", base):
        return base.replace("-", "")
    return None


def d8(value):
    return value.strftime("%Y%m%d") if value else ""


def rd8(start, end):
    if not start:
        return ""
    if not end or end == start:
        return ""
    return f"{d8(start)}-{d8(end)}"


def amount(value):
    if value is None:
        return ""
    q = Decimal(value).normalize()
    if q == q.to_integral_value():
        q = q.quantize(Decimal(1))
    return f"{q}"
