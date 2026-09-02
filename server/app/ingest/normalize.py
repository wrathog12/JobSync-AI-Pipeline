"""Text normalization. Deliberately conservative about what it throws away.

The structuring step downstream finds section boundaries using blank lines and
bullet markers, so this must NOT collapse the document into a wall of prose.
`re.sub(r"\\s+", " ", text)` is the obvious thing to write here and it destroys
exactly the signal the next step needs.

What we do fix: PDF text extraction artifacts that are noise in every case —
ligatures, soft hyphens, non-breaking spaces, and the dozen glyphs different
templates use for "bullet".
"""

from __future__ import annotations

import re
import unicodedata

#: Every glyph a résumé template might use for a list bullet. Normalized to
#: "- " so the structurer has one marker to look for instead of twelve.
BULLET_GLYPHS = "•·▪▫◦‣⁃∙●○■□❖➢➤*"

_BULLET_LINE = re.compile(rf"^[ \t]*[{re.escape(BULLET_GLYPHS)}]+[ \t]*")

#: Invisible characters that survive PDF extraction and break substring matching
#: — which matters, because the grounding check compares generated text against
#: evidence text literally.
_INVISIBLE = dict.fromkeys(
    map(
        ord,
        "­"  # soft hyphen
        "​‌‍"  # zero-width space / non-joiner / joiner
        "⁠"  # word joiner
        "﻿",  # BOM
    )
)

_SPACES = str.maketrans(
    {
        " ": " ",  # non-breaking space
        " ": " ",
        " ": " ",
        " ": " ",
        " ": " ",
        "\t": "    ",
    }
)

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})

#: An en/em dash between dates is semantic ("2019 – 2021"), so it becomes a
#: plain hyphen rather than being dropped.
_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "‒": "-"})

#: A word broken across a line by hyphenation. Only rejoined when the next line
#: starts lowercase, so "state-of-the-art" and "Full-Stack" survive intact.
_WRAP_HYPHEN = re.compile(r"(\w)-\n([a-z])")

_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)
_MANY_BLANKS = re.compile(r"\n{3,}")
_MANY_SPACES = re.compile(r" {3,}")

#: PyMuPDF emits U+FFFD when a glyph has no Unicode mapping — a symptom of a
#: broken embedded font, which means the extracted text is unreliable even
#: though it is non-empty.
REPLACEMENT_CHAR = "�"


def normalize(text: str) -> str:
    """Clean extraction artifacts while preserving line and bullet structure."""
    if not text:
        return ""

    # NFKC folds ligatures (ﬁ -> fi) and full-width forms. Done first so the
    # later passes see plain ASCII where possible.
    text = unicodedata.normalize("NFKC", text)

    text = text.translate(_INVISIBLE).translate(_SPACES).translate(_QUOTES).translate(_DASHES)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WRAP_HYPHEN.sub(r"\1\2", text)

    lines = [_BULLET_LINE.sub("- ", ln) if _BULLET_LINE.match(ln) else ln for ln in text.split("\n")]
    text = "\n".join(lines)

    # Multi-space runs are column padding from table-based layouts, not content.
    text = _MANY_SPACES.sub("  ", text)
    text = _TRAILING_WS.sub("", text)
    # Two blank lines is the most that ever means anything; more is just spacing.
    text = _MANY_BLANKS.sub("\n\n", text)

    return text.strip()


def garble_ratio(text: str) -> float:
    """Share of characters that indicate a broken font rather than real content.

    Counts unmapped glyphs and control characters. Accented letters and CJK are
    NOT garble — plenty of real résumés contain both.
    """
    if not text:
        return 0.0
    bad = sum(
        1
        for ch in text
        if ch == REPLACEMENT_CHAR
        or (unicodedata.category(ch) == "Cc" and ch not in "\n\t")
        or unicodedata.category(ch) == "Co"  # private-use area
    )
    return bad / len(text)


__all__ = ["BULLET_GLYPHS", "REPLACEMENT_CHAR", "normalize", "garble_ratio"]
