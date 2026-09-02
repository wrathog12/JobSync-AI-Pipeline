"""Step 3 — raw document text to candidate L0/L1/L2 records.

The model reads; this module decides what is allowed to become memory. Everything
it produces is `PARSED_UNCONFIRMED`, and the confirmation pass (step 4) is the
only thing that can promote it.

Three checks run on the model's output, because all three catch failures that
would otherwise be invisible and permanent:

* **Quote verification.** Every achievement must actually appear in the source
  text. Bullets become L3 evidence chunks, and the grounding check treats those
  chunks as ground truth — so a paraphrased bullet turns a model sentence into a
  fact about the user's career, and then validates future claims against it.
  Silent, self-reinforcing, and fatal to the whole premise.
* **Date normalization.** `DateRange` treats `end=None` as "current", and
  `total_years_experience` counts a current role up to today. So an unparseable
  end date must not silently become an ongoing job — a 2015 internship would add
  eleven years of experience. Hence `is_current` is asked for separately.
* **Project attribution.** A project attributed to an employer the model did not
  also list gets demoted to personal rather than guessed at. Claiming a personal
  project as employer work is checkable, and the check happens in an interview.

Prompt shape: the rules are the system instruction and only the document goes in
the user turn. Aside from being the right split, it keeps the constant part
constant, which is the only caching we get at these sizes.
"""

from __future__ import annotations

import difflib
import re
from datetime import datetime, timezone

from ..llm.base import LLMCall, LLMClient
from ..schemas.common import Confidence, DateRange, Provenance, Source
from ..schemas.identity import Identity
from ..schemas.ingest import RawDocument
from ..schemas.ledger import (
    Achievement,
    Credential,
    Education,
    Employment,
    EmploymentType,
    Ledger,
    Project,
)
from ..schemas.profile import Links, Location, Profile
from ..schemas.structured import (
    CandidateEmployment,
    ExtractedDocument,
    StructureResult,
    StructureWarning,
    StructureWarningCode,
)

#: How much of an achievement must match the source to count as verbatim.
#:
#: Not 1.0: models silently drop a trailing period or fix an obvious typo, and
#: rejecting a whole bullet over a full stop would make the check noise that gets
#: switched off. 0.90 of the bullet's own length still fails a real paraphrase,
#: which reworks verbs and drops clauses.
QUOTE_MATCH_FLOOR = 0.90

#: Structuring needs far more room than a form answer: a dense two-page résumé is
#: twenty verbatim bullets plus the scaffolding. Truncation here loses records
#: silently — the JSON just ends — so the ceiling is generous.
STRUCTURE_MAX_OUTPUT_TOKENS = 8192

SYSTEM = """\
You extract structured facts from a job applicant's own résumé or CV. Your output \
is reviewed by that applicant before anything is saved, so the useful thing you \
can do is be exact and admit gaps.

Rules, in order of importance:

1. COPY, DO NOT WRITE. Achievement bullets must be copied character for \
character from the document. Do not rewrite, shorten, expand, fix grammar or \
spelling, merge two bullets, or split one. Strip only a leading bullet glyph. \
Everything downstream treats these as the applicant's own words and checks other \
text against them, so a rewritten bullet becomes a false record of their career.

2. NULL BEATS A GUESS. If the document does not state something, leave it null or \
empty. "Not stated" is a useful answer that we can act on; an invented value is \
not, and it is indistinguishable from a real one once saved. This applies \
especially to GPA, dates, and employment type.

3. NEVER TOUCH WORK AUTHORIZATION. Do not infer citizenship, visa status, or \
sponsorship needs from anything — not from where they worked, studied, or live. \
Set `mentions_work_authorization` if the document discusses it, and nothing else.

4. DATES. Use YYYY-MM. If only a year is given, give the year alone. Set \
`is_current` only when the document says the role is ongoing ("Present", \
"Current"); a missing end date is not the same fact.

5. AMBIGUOUS LAYOUT. This text was extracted from a PDF or Word file and the \
layout is gone. If you cannot tell which job a bullet or date belongs to, leave \
the association out rather than choosing the nearest one. A wrong association is \
worse than a missing one, because the applicant will not notice it.

6. PRESERVE ORDER AND GRANULARITY. Keep records in document order. Every distinct \
role gets its own entry, including two roles at the same employer.
"""

USER_TEMPLATE = """\
Extract this document.

<document>
{text}
</document>"""


def structure_document(doc: RawDocument, client: LLMClient) -> StructureResult:
    """One LLM call, then verification. Writes nothing anywhere."""
    if not doc.is_usable:
        raise ValueError(
            f"refusing to structure an unusable document: {'; '.join(doc.blocking_reasons())}"
        )

    call = LLMCall(
        prompt=USER_TEMPLATE.format(text=doc.text),
        system=SYSTEM,
        schema=ExtractedDocument,
        max_output_tokens=STRUCTURE_MAX_OUTPUT_TOKENS,
        temperature=0.0,
        label="structure",
    )
    res = client.generate(call)
    extracted = res.parsed
    assert isinstance(extracted, ExtractedDocument), "schema call must return a parsed model"

    result = build_result(extracted, doc)
    result.model = res.model
    result.prompt_tokens = res.usage.prompt_tokens
    result.output_tokens = res.usage.output_tokens
    result.thinking_tokens = res.usage.thinking_tokens
    result.ms = res.ms
    if res.truncated:
        result.warnings.insert(
            0,
            StructureWarning(
                code=StructureWarningCode.TRUNCATED,
                message=(
                    "The model ran out of room, so records near the end of the document "
                    "are probably missing. Check the tail of your résumé against this list."
                ),
            ),
        )
    return result


# ── assembly ───────────────────────────────────────────────────────────────────


def build_result(extracted: ExtractedDocument, doc: RawDocument) -> StructureResult:
    """Pure: model output + source text -> candidate records and warnings.

    Separated from the call so every verification rule below is testable without
    a network or a scripted client.
    """
    warnings: list[StructureWarning] = []
    prov = _provenance()
    seed = doc.doc_id.removeprefix("doc_")[:8]
    haystack = _norm(doc.text)

    employment = [
        _employment(job, i, seed, prov, haystack, warnings)
        for i, job in enumerate(extracted.employment)
    ]
    employer_ids = {job.employer.strip().casefold(): job.id for job in employment}

    education = []
    for i, ed in enumerate(extracted.education):
        rid = f"edu_{seed}_{i:02d}"
        education.append(
            Education(
                id=rid,
                provenance=prov,
                institution=ed.institution.strip(),
                degree=ed.degree.strip(),
                field_of_study=_clean(ed.field_of_study),
                dates=_date_range(ed.start, ed.end, False, rid, ed.institution, warnings),
                gpa=ed.gpa,
                honors=[h.strip() for h in ed.honors if h.strip()],
            )
        )

    projects = []
    for i, pr in enumerate(extracted.projects):
        rid = f"prj_{seed}_{i:02d}"
        employer_id = None
        if pr.employer and pr.employer.strip():
            employer_id = employer_ids.get(pr.employer.strip().casefold())
            if employer_id is None:
                # Do not fuzzy-match this. Attaching a project to the wrong
                # employer produces a claim the applicant would have to defend.
                warnings.append(
                    StructureWarning(
                        code=StructureWarningCode.UNKNOWN_PROJECT_EMPLOYER,
                        message=(
                            f"'{pr.name}' was attributed to '{pr.employer}', which is not "
                            f"one of the employers found in this document. It is recorded "
                            f"as personal work — set the employer yourself if that is wrong."
                        ),
                        record_id=rid,
                    )
                )
        projects.append(
            Project(
                id=rid,
                provenance=prov,
                name=pr.name.strip(),
                role=_clean(pr.role),
                summary=_clean(pr.summary),
                dates=_date_range(pr.start, pr.end, False, rid, pr.name, warnings),
                url=_clean(pr.url),
                employer_id=employer_id,
            )
        )

    credentials = [
        Credential(
            id=f"crd_{seed}_{i:02d}",
            provenance=prov,
            name=c.name.strip(),
            issuer=c.issuer.strip(),
            issued=_clean(c.issued),
            expires=_clean(c.expires),
            credential_id=_clean(c.credential_id),
        )
        for i, c in enumerate(extracted.credentials)
    ]

    ledger = Ledger(
        employment=employment,
        education=education,
        projects=projects,
        credentials=credentials,
    )

    identity = _identity(extracted, prov, warnings)
    profile = _profile(extracted, prov)

    if not employment:
        warnings.append(
            StructureWarning(
                code=StructureWarningCode.NO_EMPLOYMENT,
                message=(
                    "No jobs were found. If your résumé has them, the file's layout was "
                    "probably scrambled during extraction — check the extracted text."
                ),
            )
        )
    current = [job for job in employment if job.dates.is_current]
    if len(current) > 1:
        warnings.append(
            StructureWarning(
                code=StructureWarningCode.MULTIPLE_CURRENT,
                message=(
                    f"{len(current)} roles are marked as current: "
                    f"{', '.join(job.employer for job in current)}. That happens legitimately, "
                    f"but it also happens when an end date was missed."
                ),
            )
        )
    if extracted.mentions_work_authorization:
        warnings.append(
            StructureWarning(
                code=StructureWarningCode.AUTHORIZATION_MENTIONED,
                message=(
                    "Your document mentions work authorization or sponsorship. We do not "
                    "read that from a file — enter it yourself so it is exactly right, "
                    "since forms ask about it under penalty of perjury."
                ),
            )
        )

    return StructureResult(
        doc_id=doc.doc_id,
        identity=identity,
        profile=profile,
        ledger=ledger,
        skills=_dedupe([s.strip() for s in extracted.skills if s.strip()]),
        headline=_clean(extracted.headline),
        summary=_clean(extracted.summary),
        languages=_dedupe([lang.strip() for lang in extracted.languages if lang.strip()]),
        warnings=warnings,
    )


def _employment(
    job: CandidateEmployment,
    index: int,
    seed: str,
    prov: Provenance,
    haystack: str,
    warnings: list[StructureWarning],
) -> Employment:
    rid = f"emp_{seed}_{index:02d}"
    achievements: list[Achievement] = []
    for j, ach in enumerate(job.achievements):
        text = ach.text.strip()
        if not text:
            continue
        aid = f"ach_{seed}_{index:02d}_{j:02d}"
        if not _is_verbatim(text, haystack):
            warnings.append(
                StructureWarning(
                    code=StructureWarningCode.QUOTE_NOT_FOUND,
                    message=(
                        f"This bullet under {job.employer} does not appear in your "
                        f'document as written: "{_ellipsis(text)}". It was rewritten or '
                        f"invented, so do not approve it as-is."
                    ),
                    record_id=aid,
                )
            )
        achievements.append(
            Achievement(id=aid, text=text, metrics=_metrics(text), skill_ids=[])
        )

    return Employment(
        id=rid,
        provenance=prov,
        employer=job.employer.strip(),
        title=job.title.strip(),
        employment_type=job.employment_type or EmploymentType.FULL_TIME,
        dates=_date_range(job.start, job.end, job.is_current, rid, job.employer, warnings),
        location=_clean(job.location),
        summary=_clean(job.summary),
        achievements=achievements,
    )


def _identity(
    extracted: ExtractedDocument, prov: Provenance, warnings: list[StructureWarning]
) -> Identity | None:
    name = extracted.name
    if name is None or not name.legal_first.strip() or not name.legal_last.strip():
        warnings.append(
            StructureWarning(
                code=StructureWarningCode.NO_NAME,
                message=(
                    "No name was found. Every application form asks for one, so add it "
                    "before continuing."
                ),
            )
        )
        return None
    # `locked` stays False: L0 locks on confirmation, not on parse.
    return Identity(
        legal_first=name.legal_first.strip(),
        legal_middle=_clean(name.legal_middle),
        legal_last=name.legal_last.strip(),
        preferred_name=_clean(name.preferred_name),
        provenance=prov,
    )


def _profile(extracted: ExtractedDocument, prov: Provenance) -> Profile:
    c = extracted.contact
    other = {}
    for url in c.other_urls:
        url = url.strip()
        if url:
            other[_host(url)] = url
    return Profile(
        email=_clean(c.email),
        # Left exactly as written. E.164 needs a country, and guessing one from a
        # résumé's location is how a US number gets a +44 in front of it.
        phone_e164=_clean(c.phone),
        location=Location(
            city=_clean(c.city), region=_clean(c.region), country=_clean(c.country)
        ),
        links=Links(
            linkedin=_clean(c.linkedin),
            github=_clean(c.github),
            portfolio=_clean(c.portfolio),
            other=other,
        ),
        # `authorization` and `preferences` stay at their defaults. No parser
        # writes them; see schemas/structured.py.
        provenance=prov,
        confirmations={},
    )


def _provenance() -> Provenance:
    return Provenance(
        confidence=Confidence.PARSED_UNCONFIRMED,
        source=Source.PARSED_RESUME,
        confirmed_at=None,
        updated_at=datetime.now(timezone.utc),
    )


# ── dates ──────────────────────────────────────────────────────────────────────

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
#: Ways a document says "still here". Matched exactly rather than by substring, so
#: a real date is never swallowed by one of these.
_CURRENT_WORDS = frozenset(
    {"present", "current", "currently", "now", "ongoing", "to date", "till date", "date"}
)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_ISO_RE = re.compile(r"^\s*((?:19|20)\d{2})\s*[-/.]\s*(\d{1,2})\s*$")
_US_RE = re.compile(r"^\s*(\d{1,2})\s*[-/.]\s*((?:19|20)\d{2})\s*$")


def _date_range(
    start: str | None,
    end: str | None,
    is_current: bool,
    record_id: str,
    label: str,
    warnings: list[StructureWarning],
) -> DateRange:
    """Normalize to YYYY-MM, and never let a parse failure mean "current"."""
    # A model that writes "Present" into `end` and leaves `is_current` false has
    # still told us the role is ongoing. Reading only the boolean would report a
    # perfectly clear date as unparseable.
    is_current = is_current or _looks_current(end)
    s = _month(start, record_id, label, warnings, is_end=False)
    e = None if is_current else _month(end, record_id, label, warnings, is_end=True)

    if not is_current and end and e is None:
        # The alternative is leaving end=None, which `DateRange.is_current` reads
        # as an ongoing role and `total_years_experience` then counts to today.
        warnings.append(
            StructureWarning(
                code=StructureWarningCode.DATE_UNPARSEABLE,
                message=(
                    f"Could not read the end date '{end}' for {label}, and it is not marked "
                    f"as current. Set it yourself — left empty it would count as ongoing "
                    f"and inflate your years of experience."
                ),
                record_id=record_id,
            )
        )
    if s and e and e < s:
        warnings.append(
            StructureWarning(
                code=StructureWarningCode.DATE_REVERSED,
                message=f"{label} ends ({e}) before it starts ({s}). One of the two is wrong.",
                record_id=record_id,
            )
        )
    return DateRange(start=s, end=e)


def _looks_current(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().strip(".").casefold() in _CURRENT_WORDS


def _month(
    raw: str | None,
    record_id: str,
    label: str,
    warnings: list[StructureWarning],
    *,
    is_end: bool,
) -> str | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text or _looks_current(text):
        return None

    if m := _ISO_RE.match(text):
        month = int(m.group(2))
        return f"{m.group(1)}-{month:02d}" if 1 <= month <= 12 else None
    if m := _US_RE.match(text):
        month = int(m.group(1))
        return f"{m.group(2)}-{month:02d}" if 1 <= month <= 12 else None

    year_m = _YEAR_RE.search(text)
    if not year_m:
        return None
    year = year_m.group(0)

    for word, num in _MONTHS.items():
        if re.search(rf"\b{word}\b", text, re.IGNORECASE):
            return f"{year}-{num:02d}"

    # A bare year. Snapping to January/December keeps duration arithmetic working
    # instead of silently contributing zero months, at the cost of being an
    # approximation — so say so rather than quietly rounding someone's tenure.
    warnings.append(
        StructureWarning(
            code=StructureWarningCode.DATE_IMPRECISE,
            message=(
                f"{label} gives only a year ({year}) for its "
                f"{'end' if is_end else 'start'} date, so it was read as "
                f"{year}-{'12' if is_end else '01'}. Adjust it if the month matters."
            ),
            record_id=record_id,
        )
    )
    return f"{year}-12" if is_end else f"{year}-01"


# ── quote verification ─────────────────────────────────────────────────────────

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _norm(text: str) -> str:
    """Fold everything that a faithful copy may still differ in.

    Whitespace, case, and punctuation all change legitimately between the PDF and
    a JSON string. Word content does not, which is what the check is actually
    about.
    """
    return _NON_ALNUM.sub(" ", text.casefold()).strip()


def _is_verbatim(quote: str, haystack: str) -> bool:
    """True if `quote` appears in the already-normalized `haystack`.

    Substring first, which handles the overwhelming majority. The fuzzy fallback
    exists for a dropped full stop or a corrected typo; it measures the longest
    common run as a fraction of the quote, so a paraphrase — which breaks the run
    into fragments — fails it.
    """
    needle = _norm(quote)
    if not needle:
        return False
    if needle in haystack:
        return True
    match = difflib.SequenceMatcher(None, needle, haystack, autojunk=False).find_longest_match(
        0, len(needle), 0, len(haystack)
    )
    return match.size / len(needle) >= QUOTE_MATCH_FLOOR


# ── small helpers ──────────────────────────────────────────────────────────────

_METRIC_RE = re.compile(
    r"(?:[$€£₹]\s?\d[\d,.]*\s?(?:[KMB]|thousand|million|billion)?\b"
    r"|\b\d[\d,.]*\s?%"
    r"|\b\d[\d,.]*\s?(?:[KMB]|x)\b)",
    re.IGNORECASE,
)


def _metrics(text: str) -> list[str]:
    """Figures pulled out for the retrieval layer to weight.

    Regex, not a model call: "40%" is not ambiguous, and one call per bullet to
    re-derive it would be the most expensive way to get a worse answer.
    """
    return _dedupe(m.group(0).strip() for m in _METRIC_RE.finditer(text))


def _clean(value: str | None) -> str | None:
    """Empty string and whitespace both mean "not stated", which is not the same
    as an empty value the user set on purpose."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _dedupe(items) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        if item and item.casefold() not in {k.casefold() for k in seen}:
            seen[item] = None
    return list(seen)


def _host(url: str) -> str:
    m = re.search(r"//([^/]+)", url) or re.match(r"([^/]+)", url)
    return (m.group(1) if m else url).removeprefix("www.")


def _ellipsis(text: str, limit: int = 80) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


__all__ = [
    "structure_document",
    "build_result",
    "SYSTEM",
    "USER_TEMPLATE",
    "QUOTE_MATCH_FLOOR",
    "STRUCTURE_MAX_OUTPUT_TOKENS",
]
