"""Export Service for GCP FinOps Observatory.

Provides functional utility methods to convert JSON metric datasets and
DashboardMetricsPayload objects into formatted CSV bytes, multi-tab Excel
workbooks (using OpenPyXL / Pandas), and executive PDF summary layouts (using ReportLab).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from schemas import (
    AlertRule,
    AlertSeverity,
    DashboardMetricsPayload,
    MetricReading,
    MetricStatus,
)


class ExportFormat(str, Enum):
    """Supported file export formats."""

    CSV = "csv"
    XLSX = "xlsx"
    PDF = "pdf"


# ----------------------------------------------------------------------------
# Dataset Normalization Helpers
# ----------------------------------------------------------------------------


def _extract_metric_rows(payload: DashboardMetricsPayload) -> List[Dict[str, Any]]:
    """Flatten category metrics into a normalized tabular row structure."""
    rows: List[Dict[str, Any]] = []

    categories = [
        ("Database", payload.database),
        ("Cloud & Compute", payload.cloud),
        ("Storage & IOPS", payload.storage),
        ("Batch Processing", payload.processing),
        ("Token Usage & AI", payload.tokens),
        ("Platform SLA", payload.sla),
    ]

    for cat_name, cat_obj in categories:
        for field_name, field_val in cat_obj.__dict__.items():
            if isinstance(field_val, MetricReading):
                rows.append(
                    {
                        "category": cat_name,
                        "metric": field_name.replace("_", " ").title(),
                        "metric_id": f"{cat_name.lower().split()[0]}.{field_name}",
                        "current_value": field_val.current_value,
                        "unit": (
                            field_val.unit.value
                            if hasattr(field_val.unit, "value")
                            else str(field_val.unit)
                        ),
                        "status": (
                            field_val.status.value
                            if hasattr(field_val.status, "value")
                            else str(field_val.status)
                        ),
                        "change_pct": (
                            f"{field_val.change_percentage:+.1f}%"
                            if field_val.change_percentage is not None
                            else "N/A"
                        ),
                    }
                )

    return rows


# ----------------------------------------------------------------------------
# 1. CSV Export Handler
# ----------------------------------------------------------------------------


def to_csv_bytes(payload: DashboardMetricsPayload) -> bytes:
    """Convert metric dataset into structured, human-readable CSV bytes.

    Includes metadata header, formatted metric summary rows, and active alert rules.
    """
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")

    # Header section
    writer.writerow(["# GCP FINOPS & INFRASTRUCTURE OBSERVATORY REPORT"])
    writer.writerow(["# Generated UTC", datetime.now(timezone.utc).isoformat()])
    writer.writerow(["# Environment", payload.filter_params.environment.value])
    writer.writerow(["# Time Period", payload.filter_params.time_period.value])
    writer.writerow(["# Overall Status", payload.aggregate_status.value])
    writer.writerow([])

    # Metrics section
    writer.writerow(["--- METRIC READINGS SUMMARY ---"])
    writer.writerow(
        ["Category", "Metric Name", "Metric Key", "Current Value", "Unit", "Status", "24h Change"]
    )

    rows = _extract_metric_rows(payload)
    for r in rows:
        writer.writerow(
            [
                r["category"],
                r["metric"],
                r["metric_id"],
                r["current_value"],
                r["unit"],
                r["status"],
                r["change_pct"],
            ]
        )

    # Alerts section
    writer.writerow([])
    writer.writerow(["--- ACTIVE ALERTS & ACTIONABLE RECOMMENDATIONS ---"])
    writer.writerow(
        [
            "Rule ID",
            "Target Metric",
            "Severity",
            "Current Value",
            "Resource ID",
            "Triggered At UTC",
            "Suggested Remediation Action",
        ]
    )

    if payload.active_alerts:
        for alert in payload.active_alerts:
            writer.writerow(
                [
                    str(alert.rule_id),
                    alert.metric_id,
                    (
                        alert.severity.value
                        if hasattr(alert.severity, "value")
                        else str(alert.severity)
                    ),
                    alert.current_value,
                    alert.resource_id or "fleet-wide",
                    alert.triggered_at.isoformat(),
                    alert.suggested_action,
                ]
            )
    else:
        writer.writerow(["No active alerts reported. All infrastructure operational."])

    return output.getvalue().encode("utf-8")


# ----------------------------------------------------------------------------
# 2. Multi-Tab Excel Export Handler (OpenPyXL)
# ----------------------------------------------------------------------------


def to_excel_bytes(payload: DashboardMetricsPayload) -> bytes:
    """Convert metric dataset into a multi-tab styled Excel workbook.

    Tabs:
      1. Executive Overview
      2. Database Metrics
      3. Cloud & Compute
      4. Storage & IOPS
      5. Processing & Jobs
      6. Token & AI FinOps
      7. Platform SLA
      8. Active Alerts & Runbooks
    """
    wb = openpyxl.Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    # Styles
    navy_fill = PatternFill(start_color="1A73E8", end_color="1A73E8", fill_type="solid")
    dark_header_fill = PatternFill(start_color="202124", end_color="202124", fill_type="solid")
    stripe_fill = PatternFill(start_color="F8F9FA", end_color="F8F9FA", fill_type="solid")
    crit_fill = PatternFill(start_color="FCE8E6", end_color="FCE8E6", fill_type="solid")
    warn_fill = PatternFill(start_color="FEF7E0", end_color="FEF7E0", fill_type="solid")
    healthy_fill = PatternFill(start_color="E6F4EA", end_color="E6F4EA", fill_type="solid")

    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    title_font = Font(name="Calibri", size=15, bold=True, color="1A73E8")
    section_font = Font(name="Calibri", size=12, bold=True, color="202124")
    bold_cell_font = Font(name="Calibri", size=10, bold=True)
    regular_font = Font(name="Calibri", size=10)

    thin_border = Border(
        left=Side(style="thin", color="DADCE0"),
        right=Side(style="thin", color="DADCE0"),
        top=Side(style="thin", color="DADCE0"),
        bottom=Side(style="thin", color="DADCE0"),
    )

    # --- Tab 1: Executive Overview ---
    ws_ov = wb.create_sheet(title="Executive Overview")
    ws_ov.views.sheetView[0].showGridLines = True

    ws_ov.append(["GCP FINOPS & INFRASTRUCTURE OBSERVATORY"])
    ws_ov.cell(1, 1).font = title_font

    ws_ov.append([f"Executive Summary Report · Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"])
    ws_ov.cell(2, 1).font = regular_font
    ws_ov.append([])

    # KPI Table
    ws_ov.append(["Environment", payload.filter_params.environment.value])
    ws_ov.append(["Time Period", payload.filter_params.time_period.value])
    ws_ov.append(["Aggregate Platform Health", payload.aggregate_status.value])
    ws_ov.append(["Active Critical/Warning Alerts", len(payload.active_alerts)])

    for row_idx in range(4, 8):
        ws_ov.cell(row_idx, 1).font = bold_cell_font
        ws_ov.cell(row_idx, 1).fill = stripe_fill
        ws_ov.cell(row_idx, 2).font = bold_cell_font
        if ws_ov.cell(row_idx, 1).value == "Aggregate Platform Health":
            st = payload.aggregate_status
            ws_ov.cell(row_idx, 2).fill = (
                crit_fill if st == MetricStatus.CRITICAL else warn_fill if st == MetricStatus.WARNING else healthy_fill
            )
    ws_ov.append([])

    # All metrics rollup table
    ws_ov.append(["Category", "Metric Name", "Current Value", "Unit", "Status", "24h Change"])
    header_row_ov = ws_ov.max_row
    for col_idx in range(1, 7):
        cell = ws_ov.cell(header_row_ov, col_idx)
        cell.font = header_font
        cell.fill = navy_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    all_rows = _extract_metric_rows(payload)
    for idx, r in enumerate(all_rows):
        ws_ov.append([r["category"], r["metric"], r["current_value"], r["unit"], r["status"], r["change_pct"]])
        curr_row = ws_ov.max_row
        for col_idx in range(1, 7):
            c = ws_ov.cell(curr_row, col_idx)
            c.font = regular_font
            c.border = thin_border
            if idx % 2 == 1:
                c.fill = stripe_fill
            if col_idx == 5:  # Status
                if r["status"] == "CRITICAL":
                    c.fill = crit_fill
                elif r["status"] == "WARNING":
                    c.fill = warn_fill
                elif r["status"] == "HEALTHY":
                    c.fill = healthy_fill

    # --- Category Tabs ---
    category_tabs = [
        ("Database", payload.database),
        ("Cloud & Compute", payload.cloud),
        ("Storage & IOPS", payload.storage),
        ("Processing & Jobs", payload.processing),
        ("Token & AI FinOps", payload.tokens),
        ("Platform SLA", payload.sla),
    ]

    for tab_title, cat_obj in category_tabs:
        ws = wb.create_sheet(title=tab_title)
        ws.views.sheetView[0].showGridLines = True

        ws.append([f"GCP Observatory - {tab_title} Telemetry"])
        ws.cell(1, 1).font = title_font
        ws.append([f"Resource Scope: {cat_obj.resource_id or 'Fleet-wide'} | Status: {cat_obj.overall_status.value}"])
        ws.cell(2, 1).font = bold_cell_font
        ws.append([])

        ws.append(["Metric Name", "Value", "Unit", "Status", "24h Trend / Change"])
        cat_hdr_row = ws.max_row
        for col in range(1, 6):
            cell = ws.cell(cat_hdr_row, col)
            cell.font = header_font
            cell.fill = dark_header_fill
            cell.alignment = Alignment(horizontal="center")

        for f_name, f_val in cat_obj.__dict__.items():
            if isinstance(f_val, MetricReading):
                status_str = f_val.status.value if hasattr(f_val.status, "value") else str(f_val.status)
                chg = f"{f_val.change_percentage:+.1f}%" if f_val.change_percentage is not None else "0.0%"
                unit_str = f_val.unit.value if hasattr(f_val.unit, "value") else str(f_val.unit)

                ws.append([f_name.replace("_", " ").title(), f_val.current_value, unit_str, status_str, chg])
                r_num = ws.max_row
                for col in range(1, 6):
                    c = ws.cell(r_num, col)
                    c.font = regular_font
                    c.border = thin_border
                    if col == 4:
                        if status_str == "CRITICAL":
                            c.fill = crit_fill
                        elif status_str == "WARNING":
                            c.fill = warn_fill
                        elif status_str == "HEALTHY":
                            c.fill = healthy_fill

    # --- Active Alerts Tab ---
    ws_al = wb.create_sheet(title="Active Alerts")
    ws_al.views.sheetView[0].showGridLines = True
    ws_al.append(["GCP Active Infrastructure Alerts & Prescriptive Runbooks"])
    ws_al.cell(1, 1).font = title_font
    ws_al.append([])

    ws_al.append(["Severity", "Metric ID", "Value", "Resource", "Triggered At (UTC)", "Prescribed Remediation Action"])
    al_hdr_row = ws_al.max_row
    for col in range(1, 7):
        cell = ws_al.cell(al_hdr_row, col)
        cell.font = header_font
        cell.fill = navy_fill
        cell.alignment = Alignment(horizontal="center")

    for alert in payload.active_alerts:
        sev = alert.severity.value if hasattr(alert.severity, "value") else str(alert.severity)
        ws_al.append([
            sev,
            alert.metric_id,
            alert.current_value,
            alert.resource_id or "fleet-wide",
            alert.triggered_at.strftime("%Y-%m-%d %H:%M:%S"),
            alert.suggested_action,
        ])
        curr = ws_al.max_row
        for col in range(1, 7):
            c = ws_al.cell(curr, col)
            c.font = regular_font
            c.border = thin_border
            if col == 1:
                c.fill = crit_fill if sev == "CRITICAL" else warn_fill
                c.font = bold_cell_font

    # Auto-fit columns across all sheets
    for ws_cur in wb.worksheets:
        for col in ws_cur.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val = str(cell.value or "")
                # Only check length of lines without newlines for title cells
                first_line = val.split("\n")[0]
                if len(first_line) > max_len and len(first_line) < 80:
                    max_len = len(first_line)
            ws_cur.column_dimensions[col_letter].width = max(max_len + 3, 12)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ----------------------------------------------------------------------------
# 3. PDF Summary Layout Handler (ReportLab)
# ----------------------------------------------------------------------------


def to_pdf_bytes(payload: DashboardMetricsPayload) -> bytes:
    """Convert metric dataset into a formatted executive summary PDF report.

    Features GCP-branded styling, aggregate health status banners, tabular metric
    summaries, and highlighted remediation instructions for active alerts.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#1A73E8"),
    )
    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#5F6368"),
    )
    section_h2 = ParagraphStyle(
        "SectionH2",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#202124"),
        spaceBefore=10,
        spaceAfter=6,
    )
    cell_body = ParagraphStyle(
        "CellBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#202124"),
    )
    cell_bold = ParagraphStyle(
        "CellBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#202124"),
    )
    alert_action_style = ParagraphStyle(
        "AlertAction",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=8.0,
        leading=10,
        textColor=colors.HexColor("#3C4043"),
    )

    elements: List[Any] = []

    # Title & Subtitle Banner
    elements.append(Paragraph("GCP FinOps & Infrastructure Observatory", title_style))
    gen_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    elements.append(
        Paragraph(
            f"Executive Operational & Cost Telemetry Report · Generated: {gen_time} · "
            f"Env: <b>{payload.filter_params.environment.value}</b> · Scope: <b>{payload.filter_params.time_period.value}</b>",
            subtitle_style,
        )
    )
    elements.append(Spacer(1, 12))

    # Aggregate Health Banner Table
    agg_st = payload.aggregate_status.value
    st_bg = (
        colors.HexColor("#FCE8E6")
        if agg_st == "CRITICAL"
        else colors.HexColor("#FEF7E0")
        if agg_st == "WARNING"
        else colors.HexColor("#E6F4EA")
    )
    st_fg = (
        colors.HexColor("#C5221F")
        if agg_st == "CRITICAL"
        else colors.HexColor("#B06000")
        if agg_st == "WARNING"
        else colors.HexColor("#137333")
    )

    health_data = [
        [
            Paragraph("<b>Overall System Status</b>", cell_bold),
            Paragraph(f"<font color='{st_fg.hexval()}'><b>{agg_st}</b></font>", cell_bold),
            Paragraph("<b>Active Incident Alerts</b>", cell_bold),
            Paragraph(f"<b>{len(payload.active_alerts)} triggered</b>", cell_bold),
        ]
    ]
    health_table = Table(health_data, colWidths=[130, 140, 130, 140])
    health_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F3F4")),
                ("BACKGROUND", (1, 0), (1, 0), st_bg),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#DADCE0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DADCE0")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    elements.append(health_table)
    elements.append(Spacer(1, 14))

    # Section 1: Active Alerts & Prescribed Action items
    if payload.active_alerts:
        elements.append(Paragraph("Active Alerts & Actionable Prescriptions", section_h2))
        alert_rows = [
            [
                Paragraph("<b>Severity</b>", cell_bold),
                Paragraph("<b>Metric / Resource</b>", cell_bold),
                Paragraph("<b>Value</b>", cell_bold),
                Paragraph("<b>Prescribed Remediation Action</b>", cell_bold),
            ]
        ]
        for a in payload.active_alerts:
            sev = a.severity.value if hasattr(a.severity, "value") else str(a.severity)
            s_color = "#C5221F" if sev == "CRITICAL" else "#B06000"
            alert_rows.append(
                [
                    Paragraph(f"<font color='{s_color}'><b>{sev}</b></font>", cell_bold),
                    Paragraph(f"{a.metric_id}<br/><i>{a.resource_id or 'fleet'}</i>", cell_body),
                    Paragraph(f"<b>{a.current_value}</b>", cell_body),
                    Paragraph(a.suggested_action, alert_action_style),
                ]
            )
        alert_table = Table(alert_rows, colWidths=[65, 130, 45, 300])
        alert_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#202124")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#DADCE0")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E8EAED")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        elements.append(alert_table)
        elements.append(Spacer(1, 14))

    # Section 2: Metric Readings Snapshot
    elements.append(Paragraph("Infrastructure Telemetry Snapshot", section_h2))
    metric_rows = [
        [
            Paragraph("<b>Category</b>", cell_bold),
            Paragraph("<b>Metric</b>", cell_bold),
            Paragraph("<b>Value</b>", cell_bold),
            Paragraph("<b>Unit</b>", cell_bold),
            Paragraph("<b>Status</b>", cell_bold),
            Paragraph("<b>24h Chg</b>", cell_bold),
        ]
    ]

    all_metrics = _extract_metric_rows(payload)
    for idx, m in enumerate(all_metrics):
        st = m["status"]
        st_color = "#C5221F" if st == "CRITICAL" else "#B06000" if st == "WARNING" else "#137333"
        bg = colors.HexColor("#F8F9FA") if idx % 2 == 1 else colors.white
        metric_rows.append(
            [
                Paragraph(m["category"], cell_body),
                Paragraph(m["metric"], cell_body),
                Paragraph(f"<b>{m['current_value']}</b>", cell_body),
                Paragraph(m["unit"], cell_body),
                Paragraph(f"<font color='{st_color}'><b>{st}</b></font>", cell_bold),
                Paragraph(m["change_pct"], cell_body),
            ]
        )

    metric_table = Table(metric_rows, colWidths=[100, 150, 70, 70, 80, 70])
    metric_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A73E8")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#DADCE0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E8EAED")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(metric_table)
    elements.append(Spacer(1, 18))

    # Footer note
    footer_text = Paragraph(
        "<font size='7' color='#70757A'>Confidential · Internal Google Cloud Platform FinOps Observatory "
        "· Generated automatically via FastAPI export handler.</font>",
        ParagraphStyle("FootNote", parent=styles["Normal"], alignment=TA_CENTER),
    )
    elements.append(footer_text)

    doc.build(elements)
    return buffer.getvalue()


# ----------------------------------------------------------------------------
# Unified Functional Dispatcher
# ----------------------------------------------------------------------------


def export_metrics_report(
    payload: DashboardMetricsPayload,
    format: Union[ExportFormat, str],
) -> Tuple[bytes, str, str]:
    """Unified handler that returns (content_bytes, media_type, filename)."""
    fmt_str = format.value if isinstance(format, ExportFormat) else str(format).lower()
    env_str = payload.filter_params.environment.value.lower()
    period_str = payload.filter_params.time_period.value
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")

    if fmt_str in ("csv", "text/csv"):
        data = to_csv_bytes(payload)
        media_type = "text/csv"
        filename = f"gcp-finops-report-{env_str}-{period_str}-{timestamp_str}.csv"
    elif fmt_str in ("xlsx", "excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"):
        data = to_excel_bytes(payload)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"gcp-finops-report-{env_str}-{period_str}-{timestamp_str}.xlsx"
    elif fmt_str in ("pdf", "application/pdf"):
        data = to_pdf_bytes(payload)
        media_type = "application/pdf"
        filename = f"gcp-finops-report-{env_str}-{period_str}-{timestamp_str}.pdf"
    else:
        raise ValueError(f"Unsupported export format '{format}'. Supported formats: csv, xlsx, pdf.")

    return data, media_type, filename
