"""Excel and PDF export utilities for Toza Hudud."""
from __future__ import annotations

import io
from datetime import datetime, timezone

import openpyxl
from openpyxl.styles import (
    Alignment,
    Border,
    Font,
    PatternFill,
    Side,
)
from openpyxl.utils import get_column_letter

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

from database.models import Report

# ── Colour palette ─────────────────────────────────────────────────────────
C_DARK_BLUE   = "1A5276"
C_MID_BLUE    = "2E86AB"
C_LIGHT_BLUE  = "D6EAF8"
C_GREEN       = "1E8449"
C_AMBER       = "D4AC0D"
C_RED         = "C0392B"
C_WHITE       = "FFFFFF"
C_VERY_LIGHT  = "EBF5FB"
C_GOLD        = "F0B429"
C_SILVER      = "BFC9CA"
C_BRONZE      = "CA6F1E"

STATUS_MAP: dict[str, str] = {
    "new":         "🆕 Yangi",
    "in_progress": "🔄 Jarayonda",
    "done":        "✅ Bajarildi",
    "rejected":    "❌ Rad etildi",
}
STATUS_COLORS: dict[str, str] = {
    "new":         C_MID_BLUE,
    "in_progress": C_AMBER,
    "done":        C_GREEN,
    "rejected":    C_RED,
}
RANK_COLORS = [C_GOLD, C_SILVER, C_BRONZE]

# ── Style helpers ───────────────────────────────────────────────────────────

def _fill(hex_color: str) -> PatternFill:
    return PatternFill(start_color=hex_color, end_color=hex_color, fill_type="solid")


def _font(bold=False, color=C_DARK_BLUE, size=10, italic=False) -> Font:
    return Font(bold=bold, color=color, size=size, italic=italic)


def _border() -> Border:
    thin = Side(style="thin", color="CCCCCC")
    return Border(left=thin, right=thin, top=thin, bottom=thin)


def _center() -> Alignment:
    return Alignment(horizontal="center", vertical="center", wrap_text=True)


def _left() -> Alignment:
    return Alignment(horizontal="left", vertical="center", wrap_text=True)


def _apply_header_row(ws, row: int, values: list, col_widths: list | None = None) -> None:
    for col, val in enumerate(values, 1):
        cell = ws.cell(row=row, column=col, value=val)
        cell.font      = _font(bold=True, color=C_WHITE, size=10)
        cell.fill      = _fill(C_DARK_BLUE)
        cell.alignment = _center()
        cell.border    = _border()
    ws.row_dimensions[row].height = 22
    if col_widths:
        for col, width in enumerate(col_widths, 1):
            ws.column_dimensions[get_column_letter(col)].width = width


def _apply_data_cell(cell, value, row_idx: int, color_override: str | None = None) -> None:
    even = (row_idx % 2 == 0)
    cell.value     = value
    cell.fill      = _fill(color_override or (C_LIGHT_BLUE if even else C_VERY_LIGHT))
    cell.alignment = _center()
    cell.border    = _border()
    cell.font      = _font(size=9)


def _section_title(ws, row: int, text: str, col_span: int = 5) -> None:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=col_span)
    cell = ws.cell(row=row, column=1, value=text)
    cell.font      = _font(bold=True, color=C_WHITE, size=11)
    cell.fill      = _fill(C_MID_BLUE)
    cell.alignment = _left()
    cell.border    = _border()
    ws.row_dimensions[row].height = 20


# ── Sheet builders ──────────────────────────────────────────────────────────

def _build_cover(ws, period_label: str, stats: dict, district_label: str) -> None:
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 22

    ws.merge_cells("A1:B1")
    t = ws["A1"]
    t.value     = "🌿 TOZA HUDUD — HISOBOT"
    t.font      = Font(bold=True, color=C_WHITE, size=16)
    t.fill      = _fill(C_DARK_BLUE)
    t.alignment = _center()
    ws.row_dimensions[1].height = 36

    ws.merge_cells("A2:B2")
    s = ws["A2"]
    s.value     = f"Davr: {period_label}   |   Hudud: {district_label}"
    s.font      = _font(italic=True, size=11, color=C_DARK_BLUE)
    s.fill      = _fill(C_LIGHT_BLUE)
    s.alignment = _center()
    ws.row_dimensions[2].height = 22

    ws.merge_cells("A3:B3")
    g = ws["A3"]
    g.value     = f"Yaratilgan: {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')} (UTC)"
    g.font      = _font(italic=True, size=9, color="555555")
    g.alignment = _center()
    ws.row_dimensions[3].height = 18
    ws.row_dimensions[4].height = 10

    rows_data = [
        ("📋 Jami xabarlar",   stats.get("total", 0)),
        ("📅 Bugungi xabarlar", stats.get("today", 0)),
        ("✅ Bajarildi",        stats.get("by_status", {}).get("done", 0)),
        ("🔄 Jarayonda",       stats.get("by_status", {}).get("in_progress", 0)),
        ("🆕 Yangi",            stats.get("by_status", {}).get("new", 0)),
        ("❌ Rad etildi",       stats.get("by_status", {}).get("rejected", 0)),
    ]
    for r_idx, (label, val) in enumerate(rows_data, 5):
        lc = ws.cell(row=r_idx, column=1, value=label)
        vc = ws.cell(row=r_idx, column=2, value=val)
        bg = C_LIGHT_BLUE if r_idx % 2 == 0 else C_VERY_LIGHT
        lc.fill = vc.fill = _fill(bg)
        lc.border = vc.border = _border()
        lc.font  = _font(bold=True, size=10)
        vc.font  = _font(bold=True, size=12, color=C_MID_BLUE)
        lc.alignment = _left()
        vc.alignment = _center()
        ws.row_dimensions[r_idx].height = 22


def _build_reports_sheet(ws, reports: list[Report]) -> None:
    ws.freeze_panes = "A2"
    ws.sheet_view.showGridLines = False
    headers    = ["#", "Sana / Vaqt", "Viloyat", "Tuman", "Manzil", "Koordinata", "Status"]
    col_widths = [6, 18, 18, 18, 38, 24, 16]
    _apply_header_row(ws, 1, headers, col_widths)

    for row_idx, report in enumerate(reports, 2):
        status_key   = report.status or "new"
        status_color = STATUS_COLORS.get(status_key, C_MID_BLUE)
        values = [
            report.id,
            report.created_at.strftime("%d.%m.%Y %H:%M") if report.created_at else "",
            report.region   or "Noma'lum",
            report.district or "Noma'lum",
            report.address  or "",
            (f"{report.latitude:.5f}, {report.longitude:.5f}"
             if report.latitude and report.longitude else ""),
            STATUS_MAP.get(status_key, status_key),
        ]
        for col_idx, val in enumerate(values, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            if col_idx == 7:
                cell.fill      = _fill(status_color)
                cell.font      = _font(bold=True, color=C_WHITE, size=9)
                cell.alignment = _center()
                cell.border    = _border()
            else:
                _apply_data_cell(cell, val, row_idx)
        ws.row_dimensions[row_idx].height = 18


def _build_timeseries_sheet(ws, data: list[dict], label_header: str) -> None:
    ws.sheet_view.showGridLines = False
    _apply_header_row(ws, 1, [label_header, "Xabarlar soni"], col_widths=[22, 18])
    max_cnt = max((r["count"] for r in data), default=1) or 1
    for row_idx, row in enumerate(data, 2):
        intensity = int(row["count"] / max_cnt * 160)
        r_val = max(0, 214 - intensity)
        g_val = max(0, 234 - intensity // 2)
        b_val = 255
        hex_shade = f"{r_val:02X}{g_val:02X}{b_val:02X}"
        lc = ws.cell(row=row_idx, column=1, value=row["label"])
        cc = ws.cell(row=row_idx, column=2, value=row["count"])
        lc.fill = cc.fill = _fill(hex_shade)
        lc.border = cc.border = _border()
        lc.font  = _font(size=10)
        cc.font  = _font(bold=True, size=10, color=C_DARK_BLUE)
        lc.alignment = _center()
        cc.alignment = _center()
        ws.row_dimensions[row_idx].height = 18


def _build_stats_sheet(ws, user_stats: list[dict], location_stats: list[dict]) -> None:
    ws.sheet_view.showGridLines = False

    _section_title(ws, 1, "👥 Eng faol foydalanuvchilar (Top 10)", col_span=3)
    _apply_header_row(ws, 2, ["#", "Ism / Username", "Xabarlar soni"],
                      col_widths=[6, 32, 18])
    for i, u in enumerate(user_stats, 1):
        row = i + 2
        rc = RANK_COLORS[i - 1] if i <= 3 else None
        for col, val in enumerate([i, u["full_name"], u["count"]], 1):
            cell = ws.cell(row=row, column=col, value=val)
            _apply_data_cell(cell, val, row, color_override=rc)
            if col == 1 and rc:
                cell.font = _font(bold=True, color=C_WHITE, size=10)
        ws.row_dimensions[row].height = 18

    spacer_row = len(user_stats) + 4
    ws.row_dimensions[spacer_row].height = 14

    loc_start = spacer_row + 1
    _section_title(ws, loc_start, "🔥 Eng ko'p murojaat qilingan joylar (Top 15)", col_span=5)
    _apply_header_row(
        ws, loc_start + 1,
        ["#", "Manzil", "Tuman", "Koordinata", "Murojaat soni"],
        col_widths=[6, 38, 18, 24, 16],
    )
    for i, loc in enumerate(location_stats, 1):
        row = loc_start + 1 + i
        rc = RANK_COLORS[i - 1] if i <= 3 else None
        vals = [
            i,
            loc["address"] or "Manzil aniqlanmagan",
            loc["district"] or "",
            f"{loc['lat']:.3f}, {loc['lon']:.3f}",
            loc["count"],
        ]
        for col, val in enumerate(vals, 1):
            cell = ws.cell(row=row, column=col, value=val)
            _apply_data_cell(cell, val, row, color_override=rc)
            if col == 1 and rc:
                cell.font = _font(bold=True, color=C_WHITE, size=10)
        ws.row_dimensions[row].height = 18


# ── Public API ──────────────────────────────────────────────────────────────

def export_to_excel(
    reports: list[Report],
    period_label: str,
    stats: dict,
    user_stats: list[dict],
    location_stats: list[dict],
    daily_stats: list[dict],
    monthly_stats: list[dict],
    yearly_stats: list[dict],
    district_label: str = "Barchasi",
) -> bytes:
    """Build a 6-sheet styled .xlsx workbook and return raw bytes."""
    wb = openpyxl.Workbook()

    ws_cover = wb.active
    ws_cover.title = "Umumiy"
    _build_cover(ws_cover, period_label, stats, district_label)

    ws_reports = wb.create_sheet("Xabarlar")
    _build_reports_sheet(ws_reports, reports)

    ws_daily = wb.create_sheet("Kunlik (30 kun)")
    _build_timeseries_sheet(ws_daily, daily_stats, "Sana")

    ws_monthly = wb.create_sheet("Oylik (12 oy)")
    _build_timeseries_sheet(ws_monthly, monthly_stats, "Oy")

    ws_yearly = wb.create_sheet("Yillik")
    _build_timeseries_sheet(ws_yearly, yearly_stats, "Yil")

    ws_stats = wb.create_sheet("Faollik")
    _build_stats_sheet(ws_stats, user_stats, location_stats)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# ── Legacy single-sheet export (kept so old call sites don't break) ─────────

def export_to_excel_simple(reports: list[Report]) -> bytes:
    """Old single-sheet export — kept for backward compatibility only."""
    return export_to_excel(
        reports=reports,
        period_label="Barchasi",
        stats={},
        user_stats=[],
        location_stats=[],
        daily_stats=[],
        monthly_stats=[],
        yearly_stats=[],
    )


# ── PDF export ───────────────────────────────────────────────────────────────

def export_to_pdf(reports: list[Report], stats: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=20,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title",
        parent=styles["Heading1"],
        fontSize=20,
        textColor=colors.HexColor(f"#{C_MID_BLUE}"),
        spaceAfter=6,
        alignment=1,
    )
    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.grey,
        spaceAfter=12,
        alignment=1,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=10,
        spaceAfter=4,
    )

    elements: list = []

    elements.append(Paragraph("Toza Hudud — Xabar Hisoboti", title_style))
    elements.append(
        Paragraph(f"Yaratilgan: {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')} (UTC)", subtitle_style)
    )
    elements.append(Spacer(1, 8))

    elements.append(Paragraph(f"<b>Jami xabarlar:</b> {stats.get('total', 0)}", body_style))
    elements.append(Paragraph(f"<b>Bugungi xabarlar:</b> {stats.get('today', 0)}", body_style))

    by_status = stats.get("by_status", {})
    if by_status:
        _uz = {"new": "Yangi", "in_progress": "Jarayonda", "done": "Bajarildi", "rejected": "Rad etildi"}
        status_text = " | ".join(f"{_uz.get(k, k)}: {v}" for k, v in by_status.items())
        elements.append(Paragraph(f"<b>Status bo'yicha:</b> {status_text}", body_style))

    elements.append(Spacer(1, 14))

    # Table
    table_data = [["#", "Sana", "Viloyat", "Tuman", "Status"]]
    for report in reports[:200]:
        table_data.append([
            str(report.id),
            report.created_at.strftime("%d.%m.%Y") if report.created_at else "",
            report.region or "Noma'lum",
            report.district or "Noma'lum",
            STATUS_MAP.get(report.status or "", report.status or ""),
        ])

    col_widths = [0.5 * inch, 1.3 * inch, 1.7 * inch, 1.7 * inch, 1.3 * inch]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(f"#{C_DARK_BLUE}")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(f"#{C_LIGHT_BLUE}")]),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    elements.append(table)

    doc.build(elements)
    return buffer.getvalue()
