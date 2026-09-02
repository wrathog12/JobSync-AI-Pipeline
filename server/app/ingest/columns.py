"""Reading order for paged documents. The part of PDF ingest that actually breaks.

`page.get_text()` returns text in the order the *generator* wrote it, which for a
two-column résumé template means alternating between the sidebar and the body:

    EXPERIENCE                 <- body heading
    SKILLS                     <- sidebar heading
    Senior Engineer, Acme      <- body
    Python                     <- sidebar
    2019 - 2021                <- body
    Kubernetes                 <- sidebar

Every line is real, so nothing looks corrupt; the *adjacency* is fabricated.
Downstream that becomes "Kubernetes, 2019-2021" attached to the wrong employer,
and it is plausible enough that a human skims past it in the confirmation pass.

We recover the geometry instead: find the vertical gutter, then read each column
top-to-bottom.

**Granularity matters, and it is lines — not blocks.** MuPDF merges text sharing
a baseline across the whole page width into a single block, so for the page
above every block spans the gutter and block-level detection finds nothing.
Lines have tight bounding boxes that respect the columns. Verified against
PyMuPDF 1.28.

The cost of dropping to lines is that MuPDF's paragraph grouping is lost, and
the structuring step downstream needs blank lines to find section boundaries.
So paragraph breaks are re-derived from vertical gaps, which is the same signal
MuPDF was using.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

#: Lines whose vertical centres are within this many points share a visual line,
#: so they sort left-to-right rather than by exact y.
LINE_TOLERANCE_PT = 3.0

#: A gutter only counts if it lies in the middle of the page. A split at 10% of
#: the width is a margin artifact, not a layout.
GUTTER_MIN_FRAC = 0.28
GUTTER_MAX_FRAC = 0.72

#: A line must clear the gutter by this much to count as strictly one side.
#: Absorbs sub-point noise in extracted bounding boxes.
GUTTER_MARGIN_PT = 2.0

#: Full-width lines (the name header, a section rule) legitimately cross the
#: gutter. Past this share of the text, the page is one column with a
#: coincidental gap.
MAX_CROSSING_CHAR_FRAC = 0.35

#: Each side must hold a real share of the text. Without this, a right-aligned
#: date column ("Acme Corp ....... 2019-2021") reads as a second column.
MIN_SIDE_CHAR_FRAC = 0.15
MIN_SIDE_LINES = 3

#: ...but a char share alone is not enough: six dates against six job titles is
#: 17% of the text, which clears the floor. So a side must also be WIDE enough to
#: be a content column. A date gutter occupies ~10% of the page; a sidebar that
#: holds skills and contact details cannot.
MIN_SIDE_WIDTH_FRAC = 0.15

#: The other half of the same discrimination. A date column is *row-structured*:
#: every entry sits on the same baseline as the body line it annotates. Two real
#: columns have independent line rhythms, because they are laid out separately
#: and have different line counts. Past this share of paired baselines the page
#: is a table, and its rows are records we must not tear apart.
MAX_ROW_PAIRED_FRAC = 0.8

#: A vertical gap this much larger than the body leading is a paragraph break.
#: Scaled by line height so it holds at any font size.
PARAGRAPH_GAP_FACTOR = 0.6


@dataclass(frozen=True)
class TextLine:
    """One extracted line with its position on the page, in PDF points."""

    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def chars(self) -> int:
        return len(self.text.strip())

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def mid_y(self) -> float:
        return (self.y0 + self.y1) / 2


def find_gutter(lines: list[TextLine], page_width: float) -> float | None:
    """The x of the column divider, or None if the page is a single column.

    Scans candidate positions and picks the one crossed by the least text,
    preferring the centre when several are equally clean.
    """
    live = [ln for ln in lines if ln.chars]
    if len(live) < MIN_SIDE_LINES * 2 or page_width <= 0:
        return None

    total = sum(ln.chars for ln in live)
    if not total:
        return None

    lo, hi = page_width * GUTTER_MIN_FRAC, page_width * GUTTER_MAX_FRAC
    centre = page_width / 2

    # Candidates are actual line edges in range: a true gutter lies flush against
    # some line's right edge and another's left edge, so scanning edges finds it
    # exactly rather than approximately.
    candidates = sorted({ln.x1 for ln in live} | {ln.x0 for ln in live})
    candidates = [x for x in candidates if lo <= x <= hi]
    if not candidates:
        return None

    best: tuple[float, float, float] | None = None  # (crossing_frac, |x-centre|, x)
    for x in candidates:
        crossing = 0
        lcol: list[TextLine] = []
        rcol: list[TextLine] = []
        for ln in live:
            if ln.x1 <= x + GUTTER_MARGIN_PT:
                lcol.append(ln)
            elif ln.x0 >= x - GUTTER_MARGIN_PT:
                rcol.append(ln)
            else:
                crossing += ln.chars

        if len(lcol) < MIN_SIDE_LINES or len(rcol) < MIN_SIDE_LINES:
            continue
        if crossing / total > MAX_CROSSING_CHAR_FRAC:
            continue

        left = sum(ln.chars for ln in lcol)
        right = sum(ln.chars for ln in rcol)
        if left / total < MIN_SIDE_CHAR_FRAC or right / total < MIN_SIDE_CHAR_FRAC:
            continue
        if min(_width(lcol), _width(rcol)) / page_width < MIN_SIDE_WIDTH_FRAC:
            continue
        if _row_paired_frac(lcol, rcol) > MAX_ROW_PAIRED_FRAC:
            continue

        score = (crossing / total, abs(x - centre), x)
        if best is None or score < best:
            best = score

    return best[2] if best else None


def _width(lines: list[TextLine]) -> float:
    """Horizontal extent of a column — how much room its content actually takes."""
    return max(ln.x1 for ln in lines) - min(ln.x0 for ln in lines)


def _baselines(lines: list[TextLine]) -> set[int]:
    return {round(ln.mid_y / LINE_TOLERANCE_PT) for ln in lines}


def _row_paired_frac(lcol: list[TextLine], rcol: list[TextLine]) -> float:
    """Share of the narrower column's lines that sit on a line of the other.

    High means the two "columns" are really the two cells of each table row.
    """
    small, large = (rcol, lcol) if len(rcol) <= len(lcol) else (lcol, rcol)
    others = _baselines(large)
    paired = sum(1 for ln in small if round(ln.mid_y / LINE_TOLERANCE_PT) in others)
    return paired / len(small)


def _in_order(lines: list[TextLine]) -> list[TextLine]:
    """Top-to-bottom, then left-to-right among lines sharing a visual line."""
    return sorted(lines, key=lambda ln: (round(ln.mid_y / LINE_TOLERANCE_PT), ln.x0))


def _paragraph_threshold(lines: list[TextLine]) -> float:
    """Vertical gap above which a break is a paragraph break, not just leading.

    Derived from the page's own metrics: hardcoding points would misfire on any
    document that isn't 11pt.
    """
    ordered = _in_order(lines)
    gaps = [
        b.y0 - a.y1
        for a, b in zip(ordered, ordered[1:])
        if b.y0 > a.y1  # ignore same-line pairs, whose gap is negative
    ]
    heights = [ln.height for ln in lines if ln.height > 0]
    if not gaps or not heights:
        return float("inf")
    return statistics.median(gaps) + PARAGRAPH_GAP_FACTOR * statistics.median(heights)


def _emit(lines: list[TextLine], threshold: float) -> list[str]:
    """One column, top to bottom, with blank lines where paragraphs break."""
    out: list[str] = []
    prev: TextLine | None = None
    for ln in _in_order(lines):
        if prev is not None and (ln.y0 - prev.y1) > threshold:
            out.append("")
        out.append(ln.text.strip())
        prev = ln
    return out


def read_lines(lines: list[TextLine], page_width: float) -> tuple[str, bool]:
    """Lines -> text in human reading order. Returns (text, found_gutter)."""
    live = [ln for ln in lines if ln.chars]
    if not live:
        return "", False

    threshold = _paragraph_threshold(live)
    gutter = find_gutter(live, page_width)

    if gutter is None:
        return "\n".join(_emit(live, threshold)), False

    # A full-width line is a horizontal divider: everything queued above it
    # belongs before it, in both columns. So flush on encounter rather than
    # hoisting all crossing lines to the top — otherwise a mid-page "SKILLS"
    # banner migrates up into the contact header.
    out: list[str] = []
    left: list[TextLine] = []
    right: list[TextLine] = []

    def flush() -> None:
        for col in (left, right):
            if col:
                out.extend(_emit(col, threshold))
                # Column boundaries are hard breaks: the bottom of the sidebar
                # and the top of the body are not the same paragraph.
                out.append("")
                col.clear()

    for ln in _in_order(live):
        if ln.x1 <= gutter + GUTTER_MARGIN_PT:
            left.append(ln)
        elif ln.x0 >= gutter - GUTTER_MARGIN_PT:
            right.append(ln)
        else:
            flush()
            out.append(ln.text.strip())
            out.append("")
    flush()

    return "\n".join(out), True


__all__ = [
    "LINE_TOLERANCE_PT",
    "MAX_CROSSING_CHAR_FRAC",
    "MIN_SIDE_CHAR_FRAC",
    "MIN_SIDE_LINES",
    "MIN_SIDE_WIDTH_FRAC",
    "MAX_ROW_PAIRED_FRAC",
    "PARAGRAPH_GAP_FACTOR",
    "TextLine",
    "find_gutter",
    "read_lines",
]
