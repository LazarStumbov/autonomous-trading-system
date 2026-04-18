"""Shared PDF generation utilities using ReportLab.

Professional dark-theme styling consistent with the Daily Market Overview reports.
"""

import os
from datetime import datetime, timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable


# Color palette (dark professional theme)
COLORS = {
    "bg_dark": colors.HexColor("#1a1a2e"),
    "bg_medium": colors.HexColor("#16213e"),
    "bg_light": colors.HexColor("#0f3460"),
    "accent_gold": colors.HexColor("#e6b800"),
    "accent_green": colors.HexColor("#00d4aa"),
    "accent_red": colors.HexColor("#ff4757"),
    "text_primary": colors.HexColor("#ffffff"),
    "text_secondary": colors.HexColor("#a0a0b0"),
    "text_muted": colors.HexColor("#6c6c7c"),
    "border": colors.HexColor("#2a2a4a"),
}


def get_styles() -> dict:
    """Get custom paragraph styles for trading reports."""
    base = getSampleStyleSheet()

    styles = {
        "title": ParagraphStyle(
            "TradingTitle",
            parent=base["Title"],
            fontSize=24,
            textColor=COLORS["accent_gold"],
            spaceAfter=6 * mm,
        ),
        "subtitle": ParagraphStyle(
            "TradingSubtitle",
            parent=base["Normal"],
            fontSize=12,
            textColor=COLORS["text_secondary"],
            spaceAfter=4 * mm,
        ),
        "heading": ParagraphStyle(
            "TradingHeading",
            parent=base["Heading2"],
            fontSize=16,
            textColor=COLORS["accent_gold"],
            spaceBefore=6 * mm,
            spaceAfter=3 * mm,
        ),
        "body": ParagraphStyle(
            "TradingBody",
            parent=base["Normal"],
            fontSize=10,
            textColor=COLORS["text_primary"],
            leading=14,
        ),
        "metric_label": ParagraphStyle(
            "MetricLabel",
            parent=base["Normal"],
            fontSize=9,
            textColor=COLORS["text_muted"],
        ),
        "metric_value": ParagraphStyle(
            "MetricValue",
            parent=base["Normal"],
            fontSize=14,
            textColor=COLORS["text_primary"],
        ),
        "positive": ParagraphStyle(
            "Positive",
            parent=base["Normal"],
            fontSize=12,
            textColor=COLORS["accent_green"],
        ),
        "negative": ParagraphStyle(
            "Negative",
            parent=base["Normal"],
            fontSize=12,
            textColor=COLORS["accent_red"],
        ),
    }
    return styles


def create_report_doc(filepath: str, title: str = "Trading Report") -> SimpleDocTemplate:
    """Create a ReportLab document with standard margins."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    return SimpleDocTemplate(
        filepath,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=title,
    )


def build_header(title: str, subtitle: str = None) -> list:
    """Build a report header with title and optional subtitle."""
    styles = get_styles()
    elements = [
        Paragraph(title, styles["title"]),
    ]
    if subtitle:
        elements.append(Paragraph(subtitle, styles["subtitle"]))
    elements.append(HRFlowable(width="100%", thickness=1, color=COLORS["accent_gold"]))
    elements.append(Spacer(1, 4 * mm))
    return elements


def build_metrics_table(metrics: list[tuple[str, str, str]]) -> Table:
    """Build a metrics summary table.

    Args:
        metrics: List of (label, value, color) tuples.
                 color should be "green", "red", or "neutral"
    """
    styles = get_styles()
    color_map = {
        "green": COLORS["accent_green"],
        "red": COLORS["accent_red"],
        "neutral": COLORS["text_primary"],
        "gold": COLORS["accent_gold"],
    }

    data = []
    for label, value, color in metrics:
        data.append([
            Paragraph(label, styles["metric_label"]),
            Paragraph(str(value), ParagraphStyle(
                "DynMetric", parent=styles["metric_value"],
                textColor=color_map.get(color, COLORS["text_primary"]),
            )),
        ])

    table = Table(data, colWidths=[50 * mm, 40 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def build_trades_table(trades: list[dict]) -> Table:
    """Build a table of trades for the report."""
    styles = get_styles()

    header = ["Asset", "Dir", "Entry", "Exit", "P&L", "Leverage"]
    data = [header]

    for t in trades:
        pnl = t.get("pnl_usd", 0)
        pnl_str = f"${pnl:+,.2f}" if pnl else "-"
        data.append([
            t.get("asset", ""),
            t.get("direction", "").upper(),
            f"${t.get('entry_price', 0):,.2f}",
            f"${t.get('exit_price', 0):,.2f}" if t.get("exit_price") else "OPEN",
            pnl_str,
            f"{t.get('leverage', 1)}x",
        ])

    table = Table(data, colWidths=[35 * mm, 15 * mm, 30 * mm, 30 * mm, 25 * mm, 20 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLORS["bg_light"]),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLORS["accent_gold"]),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLORS["text_primary"]),
        ("GRID", (0, 0), (-1, -1), 0.5, COLORS["border"]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def build_section(title: str, content: str) -> list:
    """Build a section with heading and body text."""
    styles = get_styles()
    return [
        Paragraph(title, styles["heading"]),
        Paragraph(content, styles["body"]),
        Spacer(1, 3 * mm),
    ]


def build_disclaimer() -> list:
    """Build the standard disclaimer footer."""
    styles = get_styles()
    return [
        Spacer(1, 10 * mm),
        HRFlowable(width="100%", thickness=0.5, color=COLORS["text_muted"]),
        Spacer(1, 2 * mm),
        Paragraph(
            "This report is generated by an autonomous AI trading system. "
            "Past performance does not guarantee future results. "
            "All trading involves risk of loss.",
            ParagraphStyle("Disclaimer", parent=styles["body"], fontSize=7, textColor=COLORS["text_muted"]),
        ),
    ]
