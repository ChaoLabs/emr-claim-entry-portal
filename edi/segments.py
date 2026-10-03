from dataclasses import dataclass, field

from . import formatters


@dataclass(frozen=True)
class Delimiters:
    element: str = formatters.ELEMENT
    composite: str = formatters.COMPOSITE
    segment: str = formatters.SEGMENT
    repetition: str = formatters.REPETITION
    release: str = formatters.RELEASE


DEFAULT_DELIMITERS = Delimiters()


def _trim(values):
    out = list(values)
    while out and out[-1] == "":
        out.pop()
    return out


class Composite:
    def __init__(self, *parts):
        self.parts = [formatters.clean(p) if p is not None else "" for p in parts]

    def render(self, delimiters=DEFAULT_DELIMITERS):
        return delimiters.composite.join(_trim(self.parts))

    def __bool__(self):
        return bool(_trim(self.parts))

    def __eq__(self, other):
        if isinstance(other, Composite):
            return _trim(self.parts) == _trim(other.parts)
        if isinstance(other, str):
            return self.render() == other
        return NotImplemented

    def __repr__(self):
        return f"Composite({self.render()!r})"


class Segment:
    def __init__(self, segment_id, *elements, raw=False):
        self.raw = raw
        self.segment_id = segment_id if raw else formatters.clean(segment_id)
        if raw:
            self.elements = ["" if e is None else str(e) for e in elements]
        else:
            self.elements = [
                e if isinstance(e, Composite) else formatters.clean(e) for e in elements
            ]

    def element(self, position):
        index = position - 1
        if index < 0 or index >= len(self.elements):
            return ""
        value = self.elements[index]
        return value.render() if isinstance(value, Composite) else value

    @property
    def is_empty(self):
        if self.raw:
            return not self.elements
        return not _trim(
            [e.render() if isinstance(e, Composite) else e for e in self.elements]
        )

    def render(self, delimiters=DEFAULT_DELIMITERS):
        if self.raw:
            return delimiters.element.join([self.segment_id] + self.elements)
        rendered = [
            e.render(delimiters) if isinstance(e, Composite) else e for e in self.elements
        ]
        parts = [self.segment_id] + _trim(rendered)
        return delimiters.element.join(parts)

    def __eq__(self, other):
        if isinstance(other, Segment):
            return self.render() == other.render()
        if isinstance(other, str):
            return self.render() == other
        return NotImplemented

    def __repr__(self):
        return f"Segment({self.render()!r})"


class HLCounter:
    def __init__(self):
        self._next = 1
        self.issued = {}

    def take(self, parent=None):
        current = self._next
        self._next += 1
        self.issued[current] = parent
        return current

    @property
    def count(self):
        return self._next - 1


def serialize(segments, delimiters=DEFAULT_DELIMITERS, line_breaks=False):
    for position, segment in enumerate(segments, start=1):
        if segment.is_empty:
            raise ValueError(
                f"segment {position} is {segment.segment_id} with no data. "
                f"Every X12 segment needs at least one element, so this is a builder bug"
            )
    body = [s.render(delimiters) + delimiters.segment for s in segments]
    return ("\n" if line_breaks else "").join(body)


def parse(text, delimiters=DEFAULT_DELIMITERS):
    out = []
    for raw in text.replace("\r", "").replace("\n", "").split(delimiters.segment):
        if not raw:
            continue
        parts = raw.split(delimiters.element)
        elements = [
            Composite(*p.split(delimiters.composite)) if delimiters.composite in p else p
            for p in parts[1:]
        ]
        out.append(Segment(parts[0], *elements))
    return out
