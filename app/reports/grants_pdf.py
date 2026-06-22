import io
from datetime import date
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── Palette ───────────────────────────────────────────────────────────────────
NAVY  = colors.HexColor("#1B2A4A")
BLUE  = colors.HexColor("#2563EB")
GREEN = colors.HexColor("#16A34A")
LGRAY = colors.HexColor("#F3F4F6")
MGRAY = colors.HexColor("#6B7280")
DGRAY = colors.HexColor("#374151")
CHECK = colors.HexColor("#15803D")
RULE  = colors.HexColor("#E5E7EB")


# ── Style registry ────────────────────────────────────────────────────────────
def _make_styles() -> dict:
    return {
        "banner_title": ParagraphStyle(
            "banner_title",
            fontName="Helvetica-Bold",
            fontSize=18,
            textColor=colors.white,
            leading=22,
        ),
        "banner_sub": ParagraphStyle(
            "banner_sub",
            fontName="Helvetica",
            fontSize=9,
            textColor=colors.HexColor("#CBD5E1"),
            leading=13,
        ),
        "section": ParagraphStyle(
            "section",
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=NAVY,
            spaceBefore=12,
            spaceAfter=4,
            letterSpacing=0.8,
        ),
        "grant_name": ParagraphStyle(
            "grant_name",
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=DGRAY,
            leading=14,
        ),
        "meta": ParagraphStyle(
            "meta",
            fontName="Helvetica",
            fontSize=8,
            textColor=MGRAY,
            leading=12,
        ),
        "body": ParagraphStyle(
            "body",
            fontName="Helvetica",
            fontSize=9,
            textColor=DGRAY,
            leading=13,
        ),
        "reason": ParagraphStyle(
            "reason",
            fontName="Helvetica",
            fontSize=8,
            textColor=CHECK,
            leading=12,
            leftIndent=8,
        ),
        "url": ParagraphStyle(
            "url",
            fontName="Helvetica-Oblique",
            fontSize=8,
            textColor=BLUE,
            leading=11,
            leftIndent=8,
        ),
        "badge": ParagraphStyle(
            "badge",
            fontName="Helvetica-Bold",
            fontSize=7,
            textColor=colors.white,
            alignment=TA_CENTER,
            leading=10,
        ),
        "tbl_label": ParagraphStyle(
            "tbl_label",
            fontName="Helvetica-Bold",
            fontSize=7,
            textColor=MGRAY,
            leading=10,
        ),
        "tbl_value": ParagraphStyle(
            "tbl_value",
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=DGRAY,
            leading=14,
        ),
    }


# ── Formatters ────────────────────────────────────────────────────────────────
def _currency(v) -> str:
    return f"${v:,.0f}" if v is not None else "—"


def _pct(v) -> str:
    return f"{v:.1f}%" if v is not None else "—"


def _number(v) -> str:
    return f"{v:,}" if v is not None else "—"


# ── Public entry point ────────────────────────────────────────────────────────
def build_grants_pdf(
    geoid: str,
    tract_name: Optional[str],
    vintage: int,
    profile: dict,
    grants: list[dict],
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.75 * inch,
        title=f"Grant Intelligence Report — {geoid}",
        author="Locivus Location Intelligence",
    )

    S = _make_styles()
    story: list = []

    _add_banner(story, S, geoid, tract_name, vintage)
    story.append(Spacer(1, 14))
    _add_profile_section(story, S, geoid, profile)
    story.append(Spacer(1, 14))
    _add_grants_section(story, S, grants)

    doc.build(story)
    return buf.getvalue()


# ── Banner ────────────────────────────────────────────────────────────────────
def _add_banner(story, S, geoid, tract_name, vintage):
    label = f"Census Tract {tract_name or geoid}"
    generated = date.today().strftime("%B %d, %Y")

    title_tbl = Table(
        [[Paragraph("LOCIVUS &nbsp; Grant Intelligence Report", S["banner_title"])]],
        colWidths=[7 * inch],
    )
    title_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), NAVY),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 14),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 14),
    ]))
    story.append(title_tbl)

    sub_tbl = Table(
        [[Paragraph(f"{label}  ·  {vintage} ACS  ·  Generated {generated}", S["banner_sub"])]],
        colWidths=[7 * inch],
    )
    sub_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), NAVY),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LEFTPADDING",   (0, 0), (-1, -1), 14),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 14),
    ]))
    story.append(sub_tbl)


# ── Demographic profile ───────────────────────────────────────────────────────
def _add_profile_section(story, S, geoid, profile):
    story.append(Paragraph("DEMOGRAPHIC PROFILE", S["section"]))
    story.append(HRFlowable(width="100%", thickness=1, color=NAVY, spaceAfter=8))

    cells = [
        ("Total Population",   _number(profile.get("total_population"))),
        ("Median HH Income",   _currency(profile.get("median_hh_income"))),
        ("Poverty Rate",       _pct(profile.get("poverty_rate"))),
        ("Minority Population", _pct(profile.get("pct_minority"))),
        ("Renter-Occupied",    _pct(profile.get("pct_renter"))),
        ("Unemployment Rate",  _pct(profile.get("unemployment_rate"))),
        ("Bachelor's Degree+", _pct(profile.get("pct_bachelors"))),
        ("Census Tract GEOID", geoid),
    ]

    # Arrange into 2-column pairs
    rows = []
    for i in range(0, len(cells), 2):
        lbl1, val1 = cells[i]
        lbl2, val2 = cells[i + 1] if i + 1 < len(cells) else ("", "")
        rows.append([
            Paragraph(lbl1, S["tbl_label"]), Paragraph(val1, S["tbl_value"]),
            Paragraph(lbl2, S["tbl_label"]), Paragraph(val2, S["tbl_value"]),
        ])

    col_w = [1.7 * inch, 1.8 * inch, 1.7 * inch, 1.8 * inch]
    tbl = Table(rows, colWidths=col_w, hAlign="LEFT")

    style_cmds = [
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",   (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 7),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("BOX",          (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ("LINEBELOW",    (0, 0), (-1, -2), 0.5, RULE),
        ("LINEBEFORE",   (2, 0), (2, -1), 0.5, RULE),
    ]
    for row_idx in range(len(rows)):
        bg = colors.white if row_idx % 2 == 0 else LGRAY
        style_cmds.append(("BACKGROUND", (0, row_idx), (-1, row_idx), bg))

    tbl.setStyle(TableStyle(style_cmds))
    story.append(tbl)


# ── Grants list ───────────────────────────────────────────────────────────────
def _add_grants_section(story, S, grants):
    count = len(grants)
    label = f"{count} MATCHING GRANT{'S' if count != 1 else ''} FOUND"
    story.append(Paragraph(label, S["section"]))
    story.append(HRFlowable(width="100%", thickness=1, color=NAVY, spaceAfter=10))

    if not grants:
        story.append(Paragraph(
            "No grants matched the demographic profile for this tract.",
            S["body"],
        ))
        return

    for i, grant in enumerate(grants, 1):
        _add_grant_entry(story, S, i, grant)


def _add_grant_entry(story, S, index: int, grant: dict):
    grant_type  = grant.get("grant_type", "federal")
    badge_color = BLUE if grant_type == "federal" else GREEN

    # Row: "N. Program Name"  [FEDERAL / STATE badge]
    name_row = Table(
        [[
            Paragraph(f"{index}.  {grant['program_name']}", S["grant_name"]),
            Paragraph(grant_type.upper(), S["badge"]),
        ]],
        colWidths=[5.9 * inch, 0.8 * inch],
    )
    name_row.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND",    (1, 0), (1, 0),   badge_color),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (0, 0),   0),
        ("LEFTPADDING",   (1, 0), (1, 0),   3),
        ("RIGHTPADDING",  (1, 0), (1, 0),   3),
    ]))
    story.append(name_row)

    # Meta: agency · CFDA · max award
    meta_parts = [grant.get("agency") or ""]
    if grant.get("program_number"):
        meta_parts.append(f"CFDA {grant['program_number']}")
    if grant.get("max_award_amount"):
        meta_parts.append(f"Max award: ${grant['max_award_amount']:,}")
    story.append(Paragraph("  ·  ".join(filter(None, meta_parts)), S["meta"]))

    # Description
    if grant.get("description"):
        story.append(Spacer(1, 3))
        story.append(Paragraph(grant["description"], S["body"]))

    # Eligibility reasons
    for reason in grant.get("matched_criteria", []):
        story.append(Paragraph(f"✓  {reason}", S["reason"]))

    # Funding URL
    if grant.get("funding_url"):
        story.append(Paragraph(grant["funding_url"], S["url"]))

    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=0.5, color=RULE, spaceAfter=8))
