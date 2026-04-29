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


def generate_daily_pdf(filepath: str, date_str: str, stats: dict, open_trades: list, metrics: dict) -> str:
    """Render a daily performance PDF. Returns filepath on success."""
    doc = create_report_doc(filepath, title=f"Daily Trading Report — {date_str}")
    elements: list = []
    elements += build_header("Daily Trading Report", subtitle=date_str)

    pnl = stats.get("realized_pnl", 0) or 0
    total = stats.get("total", 0)
    wins = stats.get("wins", 0)
    losses = stats.get("losses", 0)
    wr = (wins / total * 100) if total else 0
    sharpe = (metrics.get("overall") or {}).get("sharpe", 0) or 0

    elements.append(build_metrics_table([
        ("Trades", str(total), "neutral"),
        ("Wins / Losses", f"{wins}W / {losses}L", "neutral"),
        ("Win rate", f"{wr:.0f}%", "green" if wr >= 50 else "red"),
        ("Realized P&L", f"${pnl:+,.2f}", "green" if pnl >= 0 else "red"),
        ("Sharpe (rolling)", f"{sharpe:.2f}", "neutral"),
        ("Open positions", str(len(open_trades)), "neutral"),
    ]))
    elements.append(Spacer(1, 6 * mm))

    by_strat = (metrics.get("by_strategy") or {})
    if by_strat:
        elements += build_section("By strategy",
            "<br/>".join(
                f"{sid}: n={m.get('n',0)} pnl=${m.get('total_pnl',0):.2f} wr={m.get('win_rate',0)*100:.0f}%"
                for sid, m in sorted(by_strat.items(), key=lambda kv: -kv[1].get("total_pnl", 0))
            ),
        )

    if open_trades:
        elements += build_section("Open positions", "")
        elements.append(build_trades_table(open_trades))

    elements += build_disclaimer()
    doc.build(elements)
    return filepath


def generate_weekly_pdf(filepath: str, period: str, overall: dict, by_strategy: dict, strategies=None) -> str:
    """Render a weekly performance PDF. Returns filepath on success.

    Signature matches caller in generate_weekly_report.py:
      generate_weekly_pdf(path, today, overall_metrics, by_strategy_metrics, strategies)
    """
    doc = create_report_doc(filepath, title=f"Weekly Trading Report - {period}")
    elements: list = []
    elements += build_header("Weekly Trading Report", subtitle=period)

    overall = overall or {}
    n = overall.get("trades", overall.get("n", 0)) or 0
    wr = (overall.get("win_rate", 0) or 0) * (100 if (overall.get("win_rate", 0) or 0) <= 1 else 1)
    pnl = overall.get("total_pnl", 0) or 0

    elements.append(build_metrics_table([
        ("Trades (7d)", str(n), "neutral"),
        ("Win rate", f"{wr:.0f}%", "green" if wr >= 50 else "red"),
        ("Realized P&L", f"${pnl:+,.2f}", "green" if pnl >= 0 else "red"),
        ("Sharpe", f"{overall.get('sharpe', 0):.2f}", "neutral"),
        ("Sortino", f"{overall.get('sortino', 0):.2f}", "neutral"),
        ("Max DD", f"{overall.get('max_dd_pct', 0):.1f}%", "red"),
        ("Grade", str(overall.get("grade", "?")), "gold"),
    ]))
    elements.append(Spacer(1, 6 * mm))

    if by_strategy:
        body = "<br/>".join(
            f"{sid}: n={m.get('n',0)} pnl=${m.get('total_pnl',0):.2f} wr={m.get('win_rate',0)*100:.0f}%"
            for sid, m in sorted(by_strategy.items(), key=lambda kv: -(kv[1] or {}).get("total_pnl", 0))
        )
        elements += build_section("By strategy", body)

    if isinstance(strategies, str) and strategies.strip():
        elements += build_section("Opus narrative", strategies.replace("\n", "<br/>"))
    elif isinstance(strategies, dict) and strategies:
        elements += build_section("Strategies",
            "<br/>".join(f"{k}: {v}" for k, v in list(strategies.items())[:30]))

    elements += build_disclaimer()
    doc.build(elements)
    return filepath


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
