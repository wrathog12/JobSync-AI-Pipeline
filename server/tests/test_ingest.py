"""Ingest tests. Fixtures are generated, not committed.

A checked-in binary résumé PDF is a fixture nobody can read in a diff and nobody
dares change. Building the PDFs here with PyMuPDF means the *layout under test*
is visible in the test itself — and the two-column case is written with the
content stream deliberately interleaved, which is what real templates do and
what naive extraction gets wrong.
"""

from __future__ import annotations

import pytest

from app.ingest import extract, extract_pasted, normalize, sniff
from app.ingest.columns import TextLine, find_gutter, read_lines
from app.ingest.normalize import garble_ratio
from app.schemas.ingest import DocumentKind, Layout, WarningCode

pymupdf = pytest.importorskip("pymupdf")
docx = pytest.importorskip("docx")


# ── fixture builders ───────────────────────────────────────────────────────────

PAGE_W, PAGE_H = 612.0, 792.0

#: A conventional single-column résumé, written top to bottom.
SINGLE_COLUMN = [
    "ALEX MORGAN",
    "alex.morgan@example.com | +1 555 0142 | Seattle, WA",
    "",
    "EXPERIENCE",
    "Senior Platform Engineer, Acme Corp",
    "2019 - 2021",
    "- Led the migration of 40 services to Kubernetes, cutting deploy time 70%.",
    "- Owned the on-call rotation for the payments platform.",
    "",
    "Backend Engineer, Globex",
    "2016 - 2019",
    "- Built the billing reconciliation pipeline in Python and PostgreSQL.",
    "",
    "EDUCATION",
    "BS Computer Science, University of Washington, 2016",
    "",
    "SKILLS",
    "Python, Go, Kubernetes, Terraform, PostgreSQL",
]

#: The body of a two-column résumé (left column).
BODY = [
    "EXPERIENCE",
    "Senior Platform Engineer, Acme Corp",
    "2019 - 2021",
    "Led the migration of 40 services",
    "to Kubernetes, cutting deploys 70%.",
    "Backend Engineer, Globex",
    "2016 - 2019",
    "Built the billing reconciliation",
    "pipeline in Python and PostgreSQL.",
]

#: The sidebar of the same résumé (right column).
#:
#: Written to look like a real one: wide enough to be a content column, and with
#: its own line count so it does NOT share baselines with the body. A narrow,
#: row-aligned right-hand strip is a date column, which is a different thing and
#: is tested separately below.
SIDEBAR = [
    "TECHNICAL SKILLS",
    "Python, Go, and Bash",
    "Kubernetes and Terraform",
    "PostgreSQL and Redis",
    "AWS and GCP",
    "CONTACT",
    "alex.morgan@example.com",
    "+1 555 0142",
    "Seattle, Washington",
]


def make_pdf(pages: list[list[tuple[float, float, str]]]) -> bytes:
    """Write positioned text. Order of the list IS the content-stream order."""
    doc = pymupdf.open()
    for items in pages:
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        for x, y, text in items:
            page.insert_text((x, y), text, fontsize=11)
    return doc.tobytes()


def single_column_pdf() -> bytes:
    items = [(56.0, 90.0 + i * 20.0, ln) for i, ln in enumerate(SINGLE_COLUMN) if ln]
    return make_pdf([items])


def two_column_pdf() -> bytes:
    """Interleaved on purpose: sidebar line, body line, sidebar line, ...

    This is the failure mode. `page.get_text()` on this file returns the columns
    zipped together, so any test that only checks "did we get text" passes while
    the meaning is destroyed.
    """
    items: list[tuple[float, float, str]] = [(56.0, 70.0, "ALEX MORGAN")]
    # Independent leading per column — 22pt vs 27pt — so the two columns do not
    # share baselines, which is how genuinely separate text frames behave.
    for i, (body, side) in enumerate(zip(BODY, SIDEBAR)):
        items.append((56.0, 110.0 + i * 22.0, body))
        items.append((380.0, 105.0 + i * 27.0, side))
    return make_pdf([items])


def scanned_pdf() -> bytes:
    """A page with no text layer — what a phone photo of a résumé produces."""
    doc = pymupdf.open()
    doc.new_page(width=PAGE_W, height=PAGE_H)
    return doc.tobytes()


def docx_bytes(paragraphs: list[str], table: list[list[str]] | None = None) -> bytes:
    from io import BytesIO

    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    if table:
        t = document.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, cell in enumerate(row):
                t.cell(r, c).text = cell
    buf = BytesIO()
    document.save(buf)
    return buf.getvalue()


# ── format sniffing ────────────────────────────────────────────────────────────


def test_sniff_ignores_the_extension():
    """Users rename files. A .docx called resume.pdf must still read as a docx."""
    assert sniff(two_column_pdf(), "resume.docx") is DocumentKind.PDF
    assert sniff(docx_bytes(["hello"]), "resume.pdf") is DocumentKind.DOCX
    assert sniff(b"just some text", "resume.pdf") is DocumentKind.TEXT


def test_sniff_rejects_other_ooxml():
    """A .pptx is also a zip. Without the document.xml check it reaches python-docx."""
    import zipfile
    from io import BytesIO

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ppt/presentation.xml", "<p/>")
    assert sniff(buf.getvalue(), "deck.pptx") is None


def test_unsupported_type_blocks_with_advice():
    doc = extract(b"\x89PNG\r\n\x1a\n\x00\x00\x00", "resume.png")
    assert not doc.is_usable
    assert doc.warnings[0].code is WarningCode.UNSUPPORTED_TYPE
    assert "paste" in doc.warnings[0].message.lower()


# ── the two-column bug ─────────────────────────────────────────────────────────


def test_naive_extraction_really_does_interleave():
    """Pins the premise. If this ever fails, the column code is solving nothing."""
    data = two_column_pdf()
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        naive = doc[0].get_text()
    lines = [ln for ln in naive.splitlines() if ln.strip()]

    body_at = [lines.index(b) for b in BODY]
    side_at = [lines.index(s) for s in SIDEBAR]
    # The two runs overlap: sidebar entries land between body entries.
    assert min(side_at) < max(body_at) and min(body_at) < max(side_at), (
        f"expected interleaving, got body={body_at} sidebar={side_at}"
    )


def test_two_column_pdf_reads_each_column_in_order():
    doc = extract(two_column_pdf(), "resume.pdf")
    assert doc.is_usable
    assert doc.layout is Layout.MULTI_COLUMN

    lines = [ln for ln in doc.text.splitlines() if ln.strip()]

    # The body must be contiguous: no sidebar entry between a title and its dates.
    i = lines.index("Senior Platform Engineer, Acme Corp")
    assert lines[i + 1] == "2019 - 2021", f"body was interrupted: {lines[i : i + 3]}"

    # And each column must appear as an unbroken run.
    body_positions = [lines.index(b) for b in BODY]
    assert body_positions == sorted(body_positions)
    assert max(body_positions) < min(lines.index(s) for s in SIDEBAR)


def test_multi_column_warns_but_does_not_block():
    """We fixed the order; we did not prove it. The user still has to look."""
    doc = extract(two_column_pdf(), "resume.pdf")
    codes = {w.code for w in doc.warnings}
    assert WarningCode.MULTI_COLUMN in codes
    assert doc.is_usable
    assert doc.advisories()


def test_full_width_header_stays_above_both_columns():
    doc = extract(two_column_pdf(), "resume.pdf")
    lines = [ln for ln in doc.text.splitlines() if ln.strip()]
    assert lines[0] == "ALEX MORGAN"


# ── single column must not be mistaken for two ─────────────────────────────────


def test_single_column_is_not_split():
    doc = extract(single_column_pdf(), "resume.pdf")
    assert doc.layout is Layout.SINGLE_COLUMN
    assert WarningCode.MULTI_COLUMN not in {w.code for w in doc.warnings}

    lines = [ln for ln in doc.text.splitlines() if ln.strip()]
    assert lines == [ln for ln in SINGLE_COLUMN if ln], "reading order changed"


def test_right_aligned_dates_are_not_a_second_column():
    """The classic false positive: 'Acme Corp .......... 2019-2021'.

    Two visual columns, but the right one is a handful of characters. Splitting
    here would hoist every date away from its employer.
    """
    items: list[tuple[float, float, str]] = []
    rows = [
        ("Senior Platform Engineer, Acme Corp", "2019 - 2021"),
        ("Led the Kubernetes migration effort", "40 svcs"),
        ("Backend Engineer, Globex Industries", "2016 - 2019"),
        ("Built billing reconciliation in Go", "12 jobs"),
        ("BS Computer Science, U. Washington", "2016"),
        ("Certified Kubernetes Administrator", "2020"),
    ]
    for i, (left, right) in enumerate(rows):
        y = 100.0 + i * 22.0
        items.append((56.0, y, left))
        items.append((450.0, y, right))

    doc = extract(make_pdf([items]), "resume.pdf")
    assert doc.layout is Layout.SINGLE_COLUMN, "a date column is not a layout column"
    lines = [ln for ln in doc.text.splitlines() if ln.strip()]
    i = lines.index("Senior Platform Engineer, Acme Corp")
    assert lines[i + 1] == "2019 - 2021", "the date left its employer"


def test_find_gutter_returns_none_when_one_side_is_tiny():
    lines = [TextLine(x0=50, y0=y, x1=400, y1=y + 12, text="a long line of body text here")
             for y in range(100, 300, 20)]
    lines += [TextLine(x0=500, y0=y, x1=520, y1=y + 12, text="'19") for y in range(100, 160, 20)]
    assert find_gutter(lines, PAGE_W) is None


def test_read_lines_on_empty_input():
    assert read_lines([], PAGE_W) == ("", False)


# ── paragraph structure survives ───────────────────────────────────────────────


def test_blank_lines_survive_extraction():
    """The structuring step finds sections with blank lines. Dropping them is a bug.

    Line-level extraction loses MuPDF's paragraph grouping, so the gaps are
    re-derived. This asserts the re-derivation actually fires.
    """
    items: list[tuple[float, float, str]] = []
    y = 90.0
    for ln in SINGLE_COLUMN:
        if not ln:
            y += 24.0  # the blank line becomes vertical space in the PDF
            continue
        items.append((56.0, y, ln))
        y += 16.0

    doc = extract(make_pdf([items]), "resume.pdf")
    assert "\n\n" in doc.text, "section boundaries were flattened away"
    # Each heading should start a paragraph.
    for heading in ("EXPERIENCE", "EDUCATION", "SKILLS"):
        assert f"\n\n{heading}" in doc.text, f"{heading} lost its break"


def test_page_breaks_do_not_glue_bullets_together():
    p1 = [(56.0, 90.0 + i * 20.0, ln) for i, ln in enumerate(["EXPERIENCE", "- first bullet"])]
    p2 = [(56.0, 90.0, "- second bullet"), (56.0, 110.0, "- third bullet")]
    doc = extract(make_pdf([p1, p2]), "resume.pdf")
    assert doc.page_count == 2
    assert "- first bullet\n\n- second bullet" in doc.text


# ── the silent failures ────────────────────────────────────────────────────────


def test_scanned_pdf_blocks_instead_of_producing_an_empty_profile():
    doc = extract(scanned_pdf(), "scan.pdf")
    assert doc.text == ""
    assert not doc.is_usable
    assert WarningCode.NO_TEXT_LAYER in {w.code for w in doc.warnings}
    assert "paste" in " ".join(doc.blocking_reasons()).lower()
    # Not SINGLE_COLUMN: with no text, no layout was ever observed.
    assert doc.layout is Layout.UNKNOWN


def test_short_extraction_blocks():
    doc = extract(b"Alex Morgan\nEngineer\n", "resume.txt")
    assert not doc.is_usable
    assert WarningCode.TOO_SHORT in {w.code for w in doc.warnings}


def test_corrupt_pdf_blocks_with_a_readable_message():
    doc = extract(b"%PDF-1.7\nthis is not really a pdf", "resume.pdf")
    assert not doc.is_usable
    assert {w.code for w in doc.warnings} & {WarningCode.CORRUPT, WarningCode.NO_TEXT_LAYER}


def test_encrypted_pdf_blocks():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((56, 90), "secret resume")
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="hunter2")
    out = extract(data, "resume.pdf")
    assert not out.is_usable
    assert WarningCode.ENCRYPTED in {w.code for w in out.warnings}


def test_many_pages_warns_without_blocking():
    pages = [[(56.0, 90.0 + i * 20.0, f"line {i} of substantive resume content")
              for i in range(10)] for _ in range(8)]
    doc = extract(make_pdf(pages), "cv.pdf")
    assert doc.page_count == 8
    assert WarningCode.MANY_PAGES in {w.code for w in doc.warnings}
    assert doc.is_usable, "a long CV is odd, not unusable"


def test_garbled_text_blocks():
    doc = extract(("�" * 60 + "real text " * 40).encode("utf-8"), "resume.txt")
    assert not doc.is_usable
    assert WarningCode.GARBLED in {w.code for w in doc.warnings}


# ── docx ───────────────────────────────────────────────────────────────────────


def test_docx_reads_table_cells():
    """python-docx's `.paragraphs` skips tables, and résumé templates are tables.

    Missing this reads half a résumé — and the half that goes missing is usually
    the employment history.
    """
    data = docx_bytes(
        ["ALEX MORGAN", "alex.morgan@example.com"],
        table=[
            ["EXPERIENCE", "SKILLS"],
            ["Senior Platform Engineer, Acme Corp, 2019 - 2021", "Python"],
            ["Led the migration of 40 services to Kubernetes.", "Kubernetes"],
            ["Backend Engineer, Globex, 2016 - 2019", "PostgreSQL"],
        ],
    )
    doc = extract(data, "resume.docx")
    assert doc.kind is DocumentKind.DOCX
    assert doc.is_usable
    assert "Senior Platform Engineer, Acme Corp, 2019 - 2021" in doc.text
    assert "Kubernetes" in doc.text


def test_docx_keeps_document_order():
    data = docx_bytes(
        ["ALEX MORGAN", "SUMMARY", "Platform engineer with eight years of experience."],
        table=[["EXPERIENCE", "2019"], ["Acme Corp", "Seattle"], ["Globex Ltd", "Remote"]],
    )
    doc = extract(data, "resume.docx")
    lines = [ln for ln in doc.text.splitlines() if ln.strip()]
    assert lines.index("ALEX MORGAN") < lines.index("SUMMARY") < lines.index("EXPERIENCE")


def test_docx_layout_table_is_flagged():
    data = docx_bytes(
        ["ALEX MORGAN", "alex.morgan@example.com | +1 555 0142 | Seattle, WA"],
        table=[
            ["EXPERIENCE", "TECHNICAL SKILLS"],
            [
                "Senior Platform Engineer, Acme Corp, 2019 - 2021. Led the migration of "
                "40 services to Kubernetes, cutting deploy time 70%.",
                "Python, Go, Kubernetes, Terraform",
            ],
            [
                "Backend Engineer, Globex Ltd, 2016 - 2019. Built the billing "
                "reconciliation pipeline in Python and PostgreSQL.",
                "PostgreSQL, Redis, AWS, GCP",
            ],
        ],
    )
    doc = extract(data, "resume.docx")
    assert doc.layout is Layout.MULTI_COLUMN
    # Unlike the PDF path there is no geometry to recover from, so the advisory
    # is the entire mitigation — it must actually be emitted.
    assert WarningCode.MULTI_COLUMN in {w.code for w in doc.warnings}
    assert doc.is_usable


def test_merged_cells_are_not_duplicated():
    data = docx_bytes(["ALEX MORGAN"], table=[["Acme Corp", "Acme Corp"], ["a", "b"], ["c", "d"]])
    doc = extract(data, "resume.docx")
    assert doc.text.count("Acme Corp") == 1


# ── normalization ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("glyph", ["•", "▪", "◦", "‣", "●", "*", "➢"])
def test_every_bullet_glyph_becomes_one_marker(glyph):
    assert normalize(f"{glyph} Led the migration") == "- Led the migration"


def test_ligatures_are_folded():
    """A PDF ligature breaks the grounding check, which compares text literally."""
    assert normalize("identiﬁed the workﬂow") == "identified the workflow"


def test_invisible_characters_are_stripped():
    assert normalize("Kuber\xadnetes​ migration") == "Kubernetes migration"


def test_nonbreaking_space_becomes_a_space():
    assert normalize("Acme\xa0Corp") == "Acme Corp"


def test_date_dashes_are_normalized_not_dropped():
    assert normalize("2019 – 2021") == "2019 - 2021"


def test_line_wrapped_hyphens_rejoin_but_real_ones_survive():
    assert normalize("migra-\ntion of services") == "migration of services"
    assert normalize("state-\nOf-The-Art") == "state-\nOf-The-Art"
    assert normalize("Full-Stack Engineer") == "Full-Stack Engineer"


def test_structure_is_preserved():
    """The one thing normalization must not do is flatten the document."""
    text = "EXPERIENCE\n\n\n\nAcme Corp\n- Led a migration\n- Owned on-call"
    out = normalize(text)
    assert out == "EXPERIENCE\n\nAcme Corp\n- Led a migration\n- Owned on-call"
    assert "\n" in out


def test_garble_ratio_ignores_accents_and_cjk():
    assert garble_ratio("José Muñoz, 東京") == 0.0
    assert garble_ratio("����") == 1.0


# ── the paste escape hatch ─────────────────────────────────────────────────────


def test_pasted_text_has_no_layout_risk():
    doc = extract_pasted("\n".join(SINGLE_COLUMN))
    assert doc.kind is DocumentKind.PASTED
    assert doc.layout is Layout.UNKNOWN
    assert doc.is_usable
    assert doc.page_count == 0
    assert "EXPERIENCE" in doc.text


def test_pasted_text_is_still_audited():
    doc = extract_pasted("too short")
    assert not doc.is_usable


# ── idempotence ────────────────────────────────────────────────────────────────


def test_the_same_file_gets_the_same_id():
    """A user who double-clicks upload must not get two profiles to reconcile."""
    data = single_column_pdf()
    a, b = extract(data, "resume.pdf"), extract(data, "resume-copy.pdf")
    assert a.doc_id == b.doc_id
    assert a.sha256 == b.sha256


def test_different_files_get_different_ids():
    assert extract(single_column_pdf()).doc_id != extract(two_column_pdf()).doc_id


def test_pasting_the_same_text_is_idempotent():
    assert extract_pasted("x" * 300).doc_id == extract_pasted("x" * 300).doc_id


def test_counts_are_computed_not_stored():
    doc = extract_pasted("\n".join(SINGLE_COLUMN))
    assert doc.char_count == len(doc.text)
    assert doc.word_count == len(doc.text.split())
    assert doc.line_count == len(doc.text.splitlines())


# ── the store ──────────────────────────────────────────────────────────────────


@pytest.fixture
def store():
    from app.ingest.store import DocumentStore

    return DocumentStore()


def test_reuploading_returns_the_first_extraction(store):
    """A double-clicked upload must not fork into two candidate profiles."""
    data = single_column_pdf()
    first = store.put(extract(data, "resume.pdf"))
    second = store.put(extract(data, "resume (1).pdf"))
    assert second is first
    assert second.filename == "resume.pdf", "the later upload overwrote the earlier one"
    assert len(store.all()) == 1


def test_usable_excludes_blocked_documents(store):
    store.put(extract(single_column_pdf(), "good.pdf"))
    store.put(extract(scanned_pdf(), "scan.pdf"))
    assert len(store.all()) == 2
    assert [d.filename for d in store.usable()] == ["good.pdf"]


def test_store_evicts_oldest(store):
    from app.ingest.store import MAX_DOCUMENTS

    for i in range(MAX_DOCUMENTS + 5):
        store.put(extract_pasted(f"resume number {i} " * 30))
    assert len(store.all()) == MAX_DOCUMENTS


# ── HTTP surface ───────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from app.ingest.store import get_documents
    from app.main import app

    get_documents().clear()
    with TestClient(app) as c:
        yield c
    get_documents().clear()


def test_upload_endpoint_returns_text_and_counts(client):
    res = client.post(
        "/ingest/upload",
        files={"file": ("resume.pdf", single_column_pdf(), "application/pdf")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["is_usable"] is True
    assert body["layout"] == "single_column"
    assert body["char_count"] == len(body["text"])
    assert "EXPERIENCE" in body["text"]


def test_blocked_extraction_is_a_200_with_a_reason(client):
    """Not a 4xx: the extraction happened, and the client needs the warning text.

    A 422 here would leave the UI with a status code and nothing to tell the user.
    """
    res = client.post(
        "/ingest/upload", files={"file": ("scan.pdf", scanned_pdf(), "application/pdf")}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["is_usable"] is False
    assert any(w["blocking"] for w in body["warnings"])


def test_empty_upload_is_rejected(client):
    res = client.post("/ingest/upload", files={"file": ("empty.pdf", b"", "application/pdf")})
    assert res.status_code == 400


def test_paste_endpoint(client):
    res = client.post("/ingest/paste", json={"text": "\n".join(SINGLE_COLUMN)})
    assert res.status_code == 200
    assert res.json()["kind"] == "pasted"


def test_documents_are_listed_and_fetchable(client):
    doc_id = client.post("/ingest/paste", json={"text": "resume text " * 40}).json()["doc_id"]
    assert doc_id in [d["doc_id"] for d in client.get("/ingest/documents").json()]
    assert client.get(f"/ingest/documents/{doc_id}").json()["doc_id"] == doc_id
    assert client.get("/ingest/documents/doc_nope").status_code == 404
    assert client.delete(f"/ingest/documents/{doc_id}").json() == {"dropped": True}
    assert client.get("/ingest/documents").json() == []


def test_ingest_writes_nothing_to_durable_memory(client):
    """The L0-L5 boundary again: extraction is staging, not knowledge."""
    from app.memory.store import get_store

    before = get_store().stats()
    client.post(
        "/ingest/upload",
        files={"file": ("resume.pdf", two_column_pdf(), "application/pdf")},
    )
    assert get_store().stats() == before
