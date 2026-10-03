from decimal import Decimal

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
