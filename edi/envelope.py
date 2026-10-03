from datetime import datetime

from . import codes, formatters
from .segments import DEFAULT_DELIMITERS, Segment

VERSION = "005010X222A1"
ISA_VERSION = "00501"
FUNCTIONAL_IDENTIFIER = "HC"
RESPONSIBLE_AGENCY = "X"
HIERARCHICAL_STRUCTURE = "0019"
PURPOSE_ORIGINAL = "00"
TRANSACTION_TYPE_CHARGEABLE = "CH"
TRANSACTION_SET = "837"

ENTITY_SUBMITTER = "41"
ENTITY_RECEIVER = "40"
QUALIFIER_ETIN = "46"

ISA_WIDTHS = {
    1: 2, 2: 10, 3: 2, 4: 10, 5: 2, 6: 15, 7: 2, 8: 15,
    9: 6, 10: 4, 11: 1, 12: 5, 13: 9, 14: 1, 15: 1, 16: 1,
}
ST_CONTROL_WIDTH = 4


def _pad(value, width):
    return str(value or "")[:width].ljust(width)


def _zero(value, width, maximum=None):
    # ST02/SE02 allow 4–9 characters; never truncate a control number.
    maximum = maximum or width
    text = str(value)
    if not text.isascii() or not text.isdigit() or len(text) > maximum:
        raise ValueError("control number must fit its numeric X12 field")
    return text.zfill(width)


def isa(partner, control_number, moment, delimiters=DEFAULT_DELIMITERS, ack_requested="0"):
    return Segment(
        "ISA",
        _pad("00", ISA_WIDTHS[1]),
        _pad("", ISA_WIDTHS[2]),
        _pad("00", ISA_WIDTHS[3]),
        _pad("", ISA_WIDTHS[4]),
        _pad(partner.isa_sender_qualifier, ISA_WIDTHS[5]),
        _pad(partner.isa_sender_id, ISA_WIDTHS[6]),
        _pad(partner.isa_receiver_qualifier, ISA_WIDTHS[7]),
        _pad(partner.isa_receiver_id, ISA_WIDTHS[8]),
        moment.strftime("%y%m%d"),
        moment.strftime("%H%M"),
        delimiters.repetition,
        ISA_VERSION,
        _zero(control_number, ISA_WIDTHS[13]),
        ack_requested,
        partner.usage_indicator,
        delimiters.composite,
        raw=True,
    )


def iea(group_count, control_number):
    return Segment("IEA", str(group_count), _zero(control_number, ISA_WIDTHS[13]))


def gs(partner, control_number, moment):
    return Segment(
        "GS",
        FUNCTIONAL_IDENTIFIER,
        partner.gs_sender_code,
        partner.gs_receiver_code,
        moment.strftime("%Y%m%d"),
        moment.strftime("%H%M"),
        str(control_number),
        RESPONSIBLE_AGENCY,
        VERSION,
    )


def ge(transaction_count, control_number):
    return Segment("GE", str(transaction_count), str(control_number))


def st(control_number):
    return Segment("ST", TRANSACTION_SET, _zero(control_number, ST_CONTROL_WIDTH, 9), VERSION)


def se(segment_count, control_number):
    return Segment("SE", str(segment_count), _zero(control_number, ST_CONTROL_WIDTH, 9))


def bht(reference, moment):
    return Segment(
        "BHT",
        HIERARCHICAL_STRUCTURE,
        PURPOSE_ORIGINAL,
        reference,
        moment.strftime("%Y%m%d"),
        moment.strftime("%H%M"),
        TRANSACTION_TYPE_CHARGEABLE,
    )


def submitter_loop(partner):
    out = [Segment("NM1", ENTITY_SUBMITTER, codes.ENTITY_ORGANISATION, partner.submitter_name,
                   "", "", "", "", QUALIFIER_ETIN, partner.submitter_id)]
    if formatters.clean(partner.submitter_contact_name):
        elements = ["IC", partner.submitter_contact_name]
        if formatters.digits(partner.submitter_contact_phone):
            elements += ["TE", formatters.digits(partner.submitter_contact_phone)]
        out.append(Segment("PER", *elements))
    return out


def receiver_loop(partner):
    return [Segment("NM1", ENTITY_RECEIVER, codes.ENTITY_ORGANISATION, partner.receiver_name,
                    "", "", "", "", QUALIFIER_ETIN, partner.receiver_id)]


def transaction_set(body, partner, st_number, reference, moment):
    out = [st(st_number), bht(reference, moment)]
    out.extend(submitter_loop(partner))
    out.extend(receiver_loop(partner))
    out.extend(body)
    out.append(se(len(out) + 1, st_number))
    return out


def wrap(body, partner, control_numbers, reference, moment=None,
         delimiters=DEFAULT_DELIMITERS):
    moment = moment or datetime.now()
    isa_number, gs_number, st_number = control_numbers
    inner = transaction_set(body, partner, st_number, reference, moment)
    return (
        [isa(partner, isa_number, moment, delimiters), gs(partner, gs_number, moment)]
        + inner
        + [ge(1, gs_number), iea(1, isa_number)]
    )
