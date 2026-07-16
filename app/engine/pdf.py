"""Certificate PDF rendering.

Renders a drafted GCC / CPC certificate (the dict produced by ``drafter.draft_certificate``)
into a formatted, printable PDF. Placeholder fields (``[... REQUIRED]``) and an unfinished
gap analysis are surfaced as a visible **DRAFT** watermark and an "outstanding items"
section, so an incomplete certificate can never be mistaken for a final, issuable one.

Pure function of its inputs — returns PDF bytes, no I/O — so it is fully unit-testable.
"""
from __future__ import annotations

from typing import Any

from fpdf import FPDF

CERT_TITLES = {
    "GCC": "General Certificate of Conformity",
    "CPC": "Children's Product Certificate",
}

_INK = (23, 33, 43)
_MUTED = (110, 125, 140)
_RULE = (200, 208, 216)
_WARN = (176, 120, 20)


def render_certificate_pdf(
    draft: dict[str, Any], gap_analysis: dict[str, Any] | None = None, *, compress: bool = True
) -> bytes:
    """Render a certificate draft to PDF bytes.

    ``compress`` defaults to True; pass False to emit an uncompressed content stream
    (useful in tests that assert on the rendered text).
    """
    gap_analysis = gap_analysis or {}
    is_draft = not gap_analysis.get("ready_to_issue", False)

    pdf = FPDF(format="Letter", unit="mm")
    pdf.set_compression(compress)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(20, 18, 20)
    pdf.add_page()

    cert_type = draft.get("certificate_type", "undetermined")
    title = CERT_TITLES.get(cert_type, "Certificate of Conformity")

    if is_draft:
        _watermark(pdf, "DRAFT")

    # Header
    pdf.set_text_color(*_INK)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, _safe(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*_MUTED)
    pdf.cell(0, 6, _safe(f"{cert_type}  -  issued {draft.get('issued_on', '')}"), new_x="LMARGIN", new_y="NEXT")
    _rule(pdf)

    # Product
    _field(pdf, "Product identification", draft.get("product_identification", ""))

    # Regulations cited
    _heading(pdf, "Cited regulations")
    citations = draft.get("citations_to_regulations", [])
    if citations and citations[0].get("citation"):
        for c in citations:
            std = f"  ({c['standard']})" if c.get("standard") else ""
            _bullet(pdf, f"{c.get('title', '')}", f"{c.get('citation', '')}{std}")
    else:
        note = citations[0].get("note") if citations else "No mandatory standards identified."
        _body(pdf, note or "No mandatory standards identified.")

    # Third-party labs (CPC only)
    if cert_type == "CPC":
        _heading(pdf, "Third-party testing laboratory")
        for lab in draft.get("third_party_labs", []):
            _body(pdf, f"- {lab}")

    # Responsible party
    _heading(pdf, "Certifier (importer / U.S. manufacturer)")
    certifier = draft.get("certifier", {})
    _body(pdf, certifier.get("name", ""))
    _body(pdf, certifier.get("address", ""))

    _heading(pdf, "Contact for test records")
    rc = draft.get("records_contact", {})
    _body(pdf, rc.get("name", ""))
    _body(pdf, "  ".join(x for x in [rc.get("email", ""), rc.get("phone", "")] if x))

    # Manufacture / testing
    mfg, test = draft.get("manufacture", {}), draft.get("testing", {})
    _field(pdf, "Date & place of manufacture", f"{mfg.get('date', '')}  -  {mfg.get('place', '')}")
    _field(pdf, "Date & place of testing", f"{test.get('date', '')}  -  {test.get('place', '')}")

    # Gap analysis (only when not ready)
    outstanding = gap_analysis.get("outstanding") or []
    if outstanding:
        _rule(pdf)
        pdf.set_text_color(*_WARN)
        _heading(pdf, "Outstanding before this certificate is valid", color=_WARN)
        for item in outstanding:
            _body(pdf, f"- {item}", color=_WARN)

    # Disclaimer
    _rule(pdf)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(*_MUTED)
    pdf.multi_cell(0, 4, _safe(draft.get("disclaimer", "DRAFT - not legal advice.")), new_x="LMARGIN", new_y="NEXT")

    out = pdf.output()
    return bytes(out)


def filename_for(product_name: str, cert_type: str) -> str:
    """A safe download filename, e.g. ``CPC-stacking-rings.pdf``."""
    slug = "-".join("".join(c if c.isalnum() else " " for c in product_name).split())[:50] or "certificate"
    return f"{cert_type}-{slug}.pdf"


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------
_UNICODE_REPL = {
    "—": "-", "–": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "…": "...", "→": "->", "•": "-",
}


def _safe(text: str) -> str:
    """Make text renderable by fpdf2's latin-1 core fonts (replace common Unicode)."""
    text = text or ""
    for bad, good in _UNICODE_REPL.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", "replace").decode("latin-1")


def _rule(pdf: FPDF) -> None:
    pdf.ln(2)
    pdf.set_draw_color(*_RULE)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(3)


def _heading(pdf: FPDF, text: str, color: tuple[int, int, int] = _MUTED) -> None:
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*color)
    pdf.cell(0, 5, _safe(text.upper()), new_x="LMARGIN", new_y="NEXT")


def _field(pdf: FPDF, label: str, value: str) -> None:
    _heading(pdf, label)
    _body(pdf, value)


def _body(pdf: FPDF, text: str, color: tuple[int, int, int] = _INK) -> None:
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*color)
    pdf.multi_cell(0, 5, _safe(text or "-"), new_x="LMARGIN", new_y="NEXT")


def _bullet(pdf: FPDF, title: str, citation: str) -> None:
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*_INK)
    pdf.multi_cell(0, 5, _safe(f"- {title}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Courier", "", 9)
    pdf.set_text_color(*_MUTED)
    pdf.multi_cell(0, 5, _safe(f"    {citation}"), new_x="LMARGIN", new_y="NEXT")


def _watermark(pdf: FPDF, text: str) -> None:
    # text() moves the cursor; save and restore x/y so it doesn't disturb layout.
    x, y = pdf.get_x(), pdf.get_y()
    with pdf.local_context():
        pdf.set_font("Helvetica", "B", 90)
        pdf.set_text_color(230, 230, 230)
        with pdf.rotation(45, pdf.w / 2, pdf.h / 2):
            pdf.text(pdf.w / 2 - 55, pdf.h / 2 + 15, text)
    pdf.set_xy(x, y)
