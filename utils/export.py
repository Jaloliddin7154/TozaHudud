import io
from datetime import datetime

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

from database.models import Report

STATUS_MAP: dict[str, str] = {
    "new": "Yangi",
    "in_progress": "Jarayonda",
    "done": "Bajarildi",
    "rejected": "Rad etildi",
}

HEADER_COLOR = "2E86AB"
ROW_ALT_COLOR = "EAF4FB"


def export_to_excel(reports: list[Report]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Xabarlar"

    headers = ["#", "Sana", "Foydalanuvchi ID", "Viloyat", "Tuman", "Manzil", "Status"]
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color=HEADER_COLOR, end_color=HEADER_COLOR, fill_type="solid")
    center = Alignment(horizontal="center", vertical="center")
    thin = Side(style="thin", color="CCCCCC")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center
        cell.border = border

    ws.row_dimensions[1].height = 22

    alt_fill = PatternFill(start_color=ROW_ALT_COLOR, end_color=ROW_ALT_COLOR, fill_type="solid")

    for row_idx, report in enumerate(reports, 2):
        values = [
            report.id,
            report.created_at.strftime("%d.%m.%Y %H:%M") if report.created_at else "",
            report.user_id,
            report.region or "Noma'lum",
            report.district or "Noma'lum",
            report.address or "",
            STATUS_MAP.get(report.status or "", report.status or ""),
        ]
        fill = alt_fill if row_idx % 2 == 0 else None
        for col_idx, value in enumerate(values, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.alignment = center
            cell.border = border
            if fill:
                cell.fill = fill

    col_widths = [6, 18, 18, 20, 20, 40, 14]
    for col_idx, width in enumerate(col_widths, 1):
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = width

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


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
        textColor=colors.HexColor(f"#{HEADER_COLOR}"),
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
        Paragraph(f"Yaratilgan: {datetime.now().strftime('%d.%m.%Y %H:%M')}", subtitle_style)
    )
    elements.append(Spacer(1, 8))

    elements.append(Paragraph(f"<b>Jami xabarlar:</b> {stats.get('total', 0)}", body_style))
    elements.append(Paragraph(f"<b>Bugungi xabarlar:</b> {stats.get('today', 0)}", body_style))

    by_status = stats.get("by_status", {})
    if by_status:
        status_text = " | ".join(
            f"{STATUS_MAP.get(k, k)}: {v}" for k, v in by_status.items()
        )
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
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(f"#{HEADER_COLOR}")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(f"#{ROW_ALT_COLOR}")]),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    elements.append(table)

    doc.build(elements)
    return buffer.getvalue()
