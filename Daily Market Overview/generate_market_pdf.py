#!/usr/bin/env python3
"""Generate Daily Market Overview PDF Newsletter - March 21, 2026"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import PageBreak
import os

# Output path
OUTPUT_DIR = "/Users/lazarstumbov/Documents/Business/Trading/Daily Market Overview"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "Daily_Market_Overview_2026-03-21.pdf")

# ── Color Palette ──────────────────────────────────────────────────────────────
DARK_BG       = colors.HexColor("#0D1117")
ACCENT_GOLD   = colors.HexColor("#D4AF37")
ACCENT_GREEN  = colors.HexColor("#00C896")
ACCENT_RED    = colors.HexColor("#FF4D4D")
ACCENT_BLUE   = colors.HexColor("#4A9EFF")
LIGHT_GRAY    = colors.HexColor("#8B949E")
MID_GRAY      = colors.HexColor("#21262D")
TEXT_WHITE    = colors.HexColor("#E6EDF3")
BORDER_COLOR  = colors.HexColor("#30363D")
HEADER_BG     = colors.HexColor("#161B22")

def build_styles():
    styles = getSampleStyleSheet()

    base = dict(fontName="Helvetica", textColor=TEXT_WHITE, backColor=DARK_BG)

    styles.add(ParagraphStyle("NewsTitle",
        fontName="Helvetica-Bold", fontSize=28, alignment=TA_CENTER,
        textColor=ACCENT_GOLD, spaceAfter=4, spaceBefore=8))

    styles.add(ParagraphStyle("NewsSubtitle",
        fontName="Helvetica", fontSize=11, alignment=TA_CENTER,
        textColor=LIGHT_GRAY, spaceAfter=2))

    styles.add(ParagraphStyle("NewsTagline",
        fontName="Helvetica-Oblique", fontSize=9, alignment=TA_CENTER,
        textColor=ACCENT_BLUE, spaceAfter=16))

    styles.add(ParagraphStyle("SectionHeader",
        fontName="Helvetica-Bold", fontSize=13, textColor=ACCENT_GOLD,
        spaceBefore=14, spaceAfter=6, borderPad=4))

    styles.add(ParagraphStyle("SubHeader",
        fontName="Helvetica-Bold", fontSize=10, textColor=ACCENT_BLUE,
        spaceBefore=8, spaceAfter=3))

    styles.add(ParagraphStyle("BodyTextCustom",
        fontName="Helvetica", fontSize=9, textColor=TEXT_WHITE,
        leading=14, spaceAfter=4, alignment=TA_JUSTIFY))

    styles.add(ParagraphStyle("BulletItem",
        fontName="Helvetica", fontSize=9, textColor=TEXT_WHITE,
        leading=13, leftIndent=12, spaceAfter=2,
        bulletIndent=4, bulletText="•"))

    styles.add(ParagraphStyle("AlertBox",
        fontName="Helvetica-Bold", fontSize=9, textColor=DARK_BG,
        backColor=ACCENT_GOLD, borderPad=6, leading=14,
        spaceBefore=6, spaceAfter=6, alignment=TA_CENTER))

    styles.add(ParagraphStyle("GreenText",
        fontName="Helvetica-Bold", fontSize=9, textColor=ACCENT_GREEN))

    styles.add(ParagraphStyle("RedText",
        fontName="Helvetica-Bold", fontSize=9, textColor=ACCENT_RED))

    styles.add(ParagraphStyle("Footer",
        fontName="Helvetica-Oblique", fontSize=7.5, textColor=LIGHT_GRAY,
        alignment=TA_CENTER, spaceAfter=0))

    styles.add(ParagraphStyle("Disclaimer",
        fontName="Helvetica-Oblique", fontSize=7, textColor=LIGHT_GRAY,
        leading=10, alignment=TA_JUSTIFY))

    return styles


def hr(color=BORDER_COLOR, thickness=0.5, space_before=4, space_after=4):
    return HRFlowable(width="100%", thickness=thickness, color=color,
                      spaceAfter=space_after, spaceBefore=space_before)


def section_table(data, col_widths, style_cmds=None):
    base_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), ACCENT_GOLD),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("BACKGROUND", (0, 1), (-1, -1), MID_GRAY),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT_WHITE),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [MID_GRAY, DARK_BG]),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER_COLOR),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    if style_cmds:
        base_cmds += style_cmds
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle(base_cmds))
    return t


def build_pdf():
    doc = SimpleDocTemplate(
        OUTPUT_FILE,
        pagesize=letter,
        rightMargin=0.65 * inch,
        leftMargin=0.65 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
    )

    styles = build_styles()
    story = []

    # ── HEADER ─────────────────────────────────────────────────────────────────
    story.append(Paragraph("DAILY MARKET OVERVIEW", styles["NewsTitle"]))
    story.append(Paragraph("Saturday, March 21, 2026  |  Issue #2026-080", styles["NewsSubtitle"]))
    story.append(Paragraph("Professional Trading Intelligence — Geopolitical Risk Edition", styles["NewsTagline"]))
    story.append(hr(ACCENT_GOLD, thickness=1.5, space_before=2, space_after=10))

    # ── MACRO ALERT ────────────────────────────────────────────────────────────
    story.append(Paragraph(
        "⚠  MACRO ALERT: U.S.-Israel War on Iran (Day ~8) — Strait of Hormuz Disruption "
        "Driving Stagflation Risk Across All Asset Classes  ⚠",
        styles["AlertBox"]
    ))
    story.append(Spacer(1, 6))

    # ── MARKET SNAPSHOT TABLE ──────────────────────────────────────────────────
    story.append(Paragraph("📊  MARKET SNAPSHOT — FRIDAY CLOSE (March 20, 2026)", styles["SectionHeader"]))

    index_data = [
        ["INDEX", "CLOSE", "CHANGE", "% CHANGE", "STATUS"],
        ["S&P 500",      "6,506.48", "▼ −99.50",  "−1.51%", "⚠ Testing Nov Low"],
        ["NASDAQ Comp.", "21,647.61","▼ −444.00", "−2.01%", "6-Month Low"],
        ["Dow Jones",    "45,577.47","▼ −443.96", "−0.96%", "4-Month Low"],
        ["Russell 2000", "2,462.82", "▼ −31.89",  "−1.28%", "Correction −10%"],
    ]
    red_rows = [("TEXTCOLOR", (2, i), (3, i), ACCENT_RED) for i in range(1, 5)]
    tbl = section_table(index_data, [1.55*inch, 1.1*inch, 1.1*inch, 1.0*inch, 1.75*inch],
                        style_cmds=red_rows)
    story.append(tbl)
    story.append(Spacer(1, 6))

    # ── COMMODITIES & RATES ────────────────────────────────────────────────────
    story.append(Paragraph("🛢  COMMODITIES, RATES & CRYPTO", styles["SectionHeader"]))
    comm_data = [
        ["ASSET",              "PRICE / LEVEL",    "CHANGE / NOTE"],
        ["Brent Crude (Oil)",  "~$113–$119 / bbl", "▲ +25%+ since Iran war began; Iraq FM"],
        ["WTI Crude",          ">$112 / bbl",      "Highest since Russia-Ukraine 2022"],
        ["Gold (Spot)",        "~$5,500+ / oz",    "▼ −10% worst weekly rout since 2011"],
        ["Silver (Spot)",      ">$120 / oz briefly","▼ −3% on week; −1% YTD"],
        ["10-Year Treasury",   "4.39% yield",      "▲ +14 bps Friday; highest since Jul 2025"],
        ["2-Year Treasury",    "3.90% yield",      "▲ +10 bps Friday"],
        ["Bitcoin (BTC)",      "$70,416",          "▼ Retreated from $76K post-FOMC"],
        ["Ethereum (ETH)",     "$2,142",           "Relatively resilient; +20% 8-day run"],
        ["VIX",                "24.63",            "▲ +2.37% — elevated fear; watch 30"],
    ]
    green_rows = [("TEXTCOLOR", (2, r), (2, r), ACCENT_GREEN) for r in [2, 3, 9]]
    red_rows2  = [("TEXTCOLOR", (2, r), (2, r), ACCENT_RED) for r in [1, 4, 5, 7, 8, 10]]
    tbl2 = section_table(comm_data, [1.7*inch, 1.5*inch, 3.4*inch],
                         style_cmds=green_rows + red_rows2)
    story.append(tbl2)
    story.append(Spacer(1, 6))

    # ── TOP MOVERS ─────────────────────────────────────────────────────────────
    story.append(Paragraph("📈  FRIDAY'S TOP MOVERS", styles["SectionHeader"]))

    movers_data = [
        ["TICKER", "COMPANY",             "MOVE",     "CATALYST"],
        ["FDX",    "FedEx",               "▲ +8%+",   "Q3 EPS $5.25 vs $4.09 est; raised guidance"],
        ["TORR",   "Torrid Holdings",     "▲ +32.8%", "Earnings beat / short squeeze"],
        ["PL",     "Planet Labs",         "▲ +31.5%", "Earnings beat"],
        ["SATL",   "Satellogic",          "▲ +22.7%", "Space sector momentum"],
        ["VZ",     "Verizon",             "▲ +1.3%",  "Defensive rotation"],
        ["---",    "---",                 "---",      "---"],
        ["CEG",    "Constellation Energy","▼ −10.9%", "NDX worst performer of day"],
        ["BARK",   "BARK Inc.",           "▼ −22.1%", "Earnings miss"],
        ["WDC",    "Western Digital",     "▼ −7.5%",  "Semiconductor selloff"],
        ["MU",     "Micron Technology",   "▼ −4.8%",  "$25B CapEx plan — sell the news"],
        ["NVDA",   "Nvidia",              "▼ −3.2%",  "AI capex scrutiny, sector pressure"],
        ["BA",     "Boeing",              "▼ −3.0%",  "Macro selloff, defense sector mixed"],
    ]
    green_m = [("TEXTCOLOR", (2, r), (2, r), ACCENT_GREEN) for r in [1, 2, 3, 4, 5]]
    red_m   = [("TEXTCOLOR", (2, r), (2, r), ACCENT_RED)   for r in [7, 8, 9, 10, 11, 12]]
    sep_row = [("BACKGROUND", (0, 6), (-1, 6), DARK_BG),
               ("TEXTCOLOR",  (0, 6), (-1, 6), BORDER_COLOR)]
    tbl3 = section_table(movers_data, [0.6*inch, 1.85*inch, 0.9*inch, 3.25*inch],
                         style_cmds=green_m + red_m + sep_row)
    story.append(tbl3)
    story.append(Spacer(1, 6))

    # ── FED & MACRO ────────────────────────────────────────────────────────────
    story.append(Paragraph("🏛  FEDERAL RESERVE & MACRO BACKDROP", styles["SectionHeader"]))
    story.append(Paragraph(
        "FOMC Decision — March 18, 2026: <b>HOLD at 3.50%–3.75%</b> (11-1 vote). "
        "One dissent (Miran) preferred 25 bps cut. Dot plot signals <b>one cut in 2026</b>, "
        "one in 2027. Core PCE forecast raised to <b>2.7%</b>. Fed cited Middle East conflict "
        "uncertainty as a key risk. Bond market is repricing: the 10-year at 4.39% is tightening "
        "financial conditions without any Fed action — watch <b>4.50%</b> as the next danger level.",
        styles["BodyTextCustom"]
    ))

    story.append(Paragraph("Key Macro Reads:", styles["SubHeader"]))
    macro_bullets = [
        "IMF formula: Every 10% oil price rise → +0.4% CPI, −0.15% GDP growth",
        "Strait of Hormuz disruption: ~20% of global crude/LNG supply suspended",
        "Qatar declared force majeure on LNG exports after Iranian drone strikes on gas infrastructure",
        "Iraq declared force majeure on ALL oilfields — unprecedented escalation",
        "Strategic reserve releases from multiple governments insufficient to offset disruption",
        "Stagflation risk is rising: higher inflation + slowing growth = worst backdrop for equities",
    ]
    for b in macro_bullets:
        story.append(Paragraph(b, styles["BulletItem"]))
    story.append(Spacer(1, 6))

    # ── SECTOR PERFORMANCE ─────────────────────────────────────────────────────
    story.append(Paragraph("🏭  SECTOR PERFORMANCE & ROTATION", styles["SectionHeader"]))
    sector_data = [
        ["SECTOR",           "FRIDAY", "YTD 2026",  "TREND"],
        ["Energy",           "+0.01%", "+25.0%",    "✦ DOMINANT LEADER"],
        ["Financials",       "+0.19%", "−6.0%",     "Struggling; rate uncertainty"],
        ["Healthcare",       "−0.89%", "Mixed",     "Defensive but under pressure"],
        ["Info Technology",  "−2.21%", "−3.6%",     "AI capex scrutiny; avoid"],
        ["Materials/Commodities","N/A","Outperform","Benefiting from oil shock"],
        ["Utilities",        "N/A",    "Outperform", "Defensive rotation winner"],
    ]
    green_s = [("TEXTCOLOR", (3, r), (3, r), ACCENT_GREEN) for r in [1, 5, 6]]
    red_s   = [("TEXTCOLOR", (3, r), (3, r), ACCENT_RED)   for r in [4]]
    tbl4 = section_table(sector_data, [1.8*inch, 0.85*inch, 1.0*inch, 2.95*inch],
                         style_cmds=green_s + red_s)
    story.append(tbl4)
    story.append(Spacer(1, 6))

    # ── TECHNICAL LEVELS ──────────────────────────────────────────────────────
    story.append(Paragraph("📐  KEY TECHNICAL LEVELS — S&P 500", styles["SectionHeader"]))
    tech_data = [
        ["LEVEL",   "PRICE",    "SIGNIFICANCE"],
        ["Resistance",  "6,840",    "Near-term ceiling / supply zone"],
        ["Resistance",  "6,782–6,731","Key resistance band"],
        ["200-DMA",     "6,630",    "Critical moving average — already breached"],
        ["⚠ Line in Sand","6,607–6,612","Must recapture for bullish recovery"],
        ["Current",     "6,506",    "Friday's close — at November 2025 low"],
        ["Support",     "~6,130",   "Next major support if 6,500 breaks"],
    ]
    tbl5 = section_table(tech_data, [1.3*inch, 1.3*inch, 4.0*inch])
    story.append(tbl5)
    story.append(Spacer(1, 6))

    # ── TRADING STRATEGY ──────────────────────────────────────────────────────
    story.append(hr(ACCENT_GOLD, thickness=1.2))
    story.append(Paragraph("🎯  TRADING STRATEGY — MARCH 21, 2026", styles["SectionHeader"]))

    # SHORT-TERM (Day / Swing)
    story.append(Paragraph("SHORT-TERM STRATEGY (Today / This Week)", styles["SubHeader"]))
    story.append(Paragraph(
        "The market is in a confirmed bearish regime. The Russell 2000 is in correction, the NASDAQ "
        "is at 6-month lows, and the S&P 500 closed Friday at the November 2025 structural low of 6,507. "
        "Monday's open will be critical. The default posture is <b>defensive / short-bias until proven otherwise</b>.",
        styles["BodyTextCustom"]
    ))

    short_term = [
        ("<b>Energy Longs (Core Trade)</b>: Oil remains the single best risk-reward in this environment. "
         "XLE, XOM, CVX, and energy royalty names (FANG, PSX) benefit directly from Brent >$110. "
         "Any dip in energy stocks is a buy opportunity while the Hormuz disruption persists."),
        ("<b>FedEx (FDX) Follow-Through</b>: The +8% post-earnings pop on Friday confirms institutional demand. "
         "Watch for continuation above $285–$290. Set a stop below Friday's close. FDX is one of the "
         "few stocks with genuine fundamental momentum right now."),
        ("<b>Volatility Play (VIX)</b>: VIX at ~24.63. If the S&P breaks below 6,500 on Monday's open, "
         "VIX will spike toward 28–30. Consider long VIX via UVXY/VIXY for short-term protection "
         "or outright profit in a breakdown scenario."),
        ("<b>Short Tech / NDX</b>: NASDAQ-100 at 6-month lows with no technical support until the 200-WMA. "
         "Semis are particularly weak (MU -4.8%, WDC -7.5%, NVDA -3.2%). Consider PSQ (inverse QQQ) "
         "or put spreads on QQQ if you want short tech exposure with defined risk."),
        ("<b>Treasury Short (TLT Puts / TBT Long)</b>: 10-year at 4.39%, heading toward 4.50%. "
         "The bond market is pricing in sustained inflation from the oil shock. TBT (2x inverse 20-year) "
         "or TLT put spreads capture continued yield rise."),
        ("<b>Gold Re-Entry Watch</b>: Gold sold off 10% in its worst week since 2011 — but this "
         "is the inflation trade unwinding, NOT a structural bear market in gold. Watch for stabilization "
         "around $5,200–$5,300/oz for a re-entry into GLD or gold miners (GDX)."),
        ("<b>Avoid Small Caps</b>: Russell 2000 in correction, high debt loads = most exposed to "
         "rising rates + slowing growth. Stay away from IWM longs."),
    ]
    for s in short_term:
        story.append(Paragraph(s, styles["BulletItem"]))
    story.append(Spacer(1, 6))

    # MEDIUM-TERM
    story.append(Paragraph("MEDIUM-TERM STRATEGY (2–8 Weeks)", styles["SubHeader"]))
    story.append(Paragraph(
        "The macro regime will be dictated by two variables: (1) Iran war resolution timeline, "
        "and (2) whether PCE inflation re-accelerates above 3%. Both favor a continued "
        "<b>stagflation trade</b> — energy/commodities/real assets over growth equities.",
        styles["BodyTextCustom"]
    ))

    medium_term = [
        ("<b>Scenario A — Iran Resolution (4–8 weeks)</b>: Brent falls back toward $70–80/bbl. "
         "Energy stocks give back gains. Fed pivot narrative returns. S&P 500 rebounds above 6,607. "
         "Probability: 35%. In this scenario, rotate from energy into beaten-down tech names (NVDA, META)."),
        ("<b>Scenario B — Prolonged Conflict (8+ weeks)</b>: Brent stays $100+. CPI re-accelerates "
         "to 3.5%+. Fed cannot cut. S&P 500 breaks 6,500 and targets 6,130. "
         "Probability: 65%. In this scenario, energy, gold, and TIPS outperform."),
        ("<b>Nike (NKE) — Earnings Watch (March 31)</b>: Down 24% YTD going into Q3 print. "
         "Guidance is for revenue decline + margin compression. High short interest = short squeeze "
         "potential on ANY positive surprise. Consider small speculative long into the print with "
         "tight stop. Risk/reward is asymmetric if they beat lowered bar."),
        ("<b>Micron (MU) — Technical Setup</b>: Sold off on capex concerns despite a massive earnings beat. "
         "This creates a longer-term entry opportunity for AI memory plays. Wait for HBM4 volume "
         "ramp confirmation in Q3 guidance. Target entry below $120 for a 3-month trade."),
        ("<b>Bitcoin ($BTC)</b>: Holding $70K post-FOMC is constructive. A Fed pivot (even one cut) "
         "could catalyze BTC above $80K. Use $65K as a stop level for any long position."),
    ]
    for m in medium_term:
        story.append(Paragraph(m, styles["BulletItem"]))
    story.append(Spacer(1, 6))

    # LONG-TERM
    story.append(Paragraph("LONG-TERM OUTLOOK (3–12 Months)", styles["SubHeader"]))
    long_term = [
        "Energy transition is being set back 3–5 years by the Iran shock — traditional energy companies "
        "will benefit from sustained higher prices and renewed investment. Long XLE / XOM for 12-month hold.",
        "Defense spending is accelerating globally. RTX, LMT, NOC will see multi-year tailwinds "
        "from geopolitical instability. Accumulate on dips.",
        "AI infrastructure remains a long-term secular trend despite near-term capex concerns. "
        "NVDA pullback toward $100–$110 creates a 12-month accumulation zone.",
        "The 60/40 portfolio is broken: both stocks and bonds are under pressure simultaneously. "
        "Real assets (energy, gold, commodities, real estate) should represent 20–30% of a balanced portfolio.",
        "Watch for Fed pivot in Q4 2026 — one cut expected. That event will be the catalyst for "
        "the next risk-on cycle, particularly for growth and small caps.",
    ]
    for l in long_term:
        story.append(Paragraph(l, styles["BulletItem"]))
    story.append(Spacer(1, 8))

    # ── RISK MATRIX ────────────────────────────────────────────────────────────
    story.append(Paragraph("⚡  RISK MATRIX — KEY WATCHLIST", styles["SectionHeader"]))
    risk_data = [
        ["EVENT / LEVEL",                "IMPACT IF TRIGGERED",          "TIMELINE"],
        ["S&P 500 breaks 6,500",         "Cascade to 6,130 — SELL",      "This week"],
        ["VIX spikes >30",               "Panic conditions — Buy puts",  "If S&P breaks"],
        ["10-Yr Treasury >4.50%",        "Mortgage shock / credit stress","1–2 weeks"],
        ["Brent crude >$120/bbl",        "CPI surge, Fed hawkish hold",  "If conflict widens"],
        ["Iran ceasefire/deal",          "Brent -$30+, tech rally",      "Wildcard"],
        ["S&P recaptures 6,607",         "Bullish — add risk-on",        "Need 3-day hold"],
        ["Gold stabilizes >$5,200",      "Re-entry signal for GLD/GDX",  "Watch next 5 days"],
        ["Nike (NKE) Q3 earnings",       "High short interest = squeeze potential", "March 31"],
    ]
    tbl6 = section_table(risk_data, [2.2*inch, 2.6*inch, 1.8*inch])
    story.append(tbl6)
    story.append(Spacer(1, 8))

    # ── EARNINGS CALENDAR ─────────────────────────────────────────────────────
    story.append(Paragraph("📅  UPCOMING EARNINGS CALENDAR", styles["SectionHeader"]))
    earnings_data = [
        ["DATE",        "TICKER", "COMPANY",          "CONSENSUS EPS", "NOTE"],
        ["Mar 31",      "NKE",    "Nike",              "$0.29",         "High watch; −24% YTD"],
        ["Early Apr",   "WMT",    "Walmart",           "TBD",           "Consumer health check"],
        ["Mid Apr",     "JPM",    "JPMorgan Chase",    "TBD",           "Financials bellwether"],
        ["Mid Apr",     "GS",     "Goldman Sachs",     "TBD",           "Trading revenue focus"],
        ["Mid-Late Apr","NVDA",   "Nvidia (est.)",     "TBD",           "AI demand signal"],
    ]
    tbl7 = section_table(earnings_data, [0.75*inch, 0.7*inch, 1.6*inch, 1.2*inch, 2.35*inch])
    story.append(tbl7)
    story.append(Spacer(1, 8))

    # ── TRADING CHECKLIST ─────────────────────────────────────────────────────
    story.append(Paragraph("✅  MONDAY PRE-MARKET CHECKLIST", styles["SectionHeader"]))
    checklist = [
        "Monitor S&P 500 futures — gap below 6,480 signals breakdown; gap above 6,560 signals relief rally",
        "Watch Brent crude at open — above $115 = energy longs remain in play",
        "Check VIX overnight — >27 pre-market = consider reducing equity exposure",
        "News scan: Any Iran ceasefire rumors = energy short / tech long instantly",
        "FedEx (FDX) follow-through — confirm continuation above Friday's close",
        "10-Year Treasury yield — if >4.45% pre-market, avoid rate-sensitive positions",
        "Bitcoin overnight — if BTC holds $70K through weekend, bullish for risk-on Monday",
        "Sector rotation check: Energy > Utilities > Healthcare > Tech (order of preference)",
    ]
    for c in checklist:
        story.append(Paragraph(c, styles["BulletItem"]))

    story.append(Spacer(1, 10))
    story.append(hr(ACCENT_GOLD, thickness=1.0))
    story.append(Spacer(1, 6))

    # ── FOOTER ────────────────────────────────────────────────────────────────
    story.append(Paragraph(
        "Daily Market Overview  |  March 21, 2026  |  Powered by AI Market Intelligence",
        styles["Footer"]
    ))
    story.append(Spacer(1, 3))
    story.append(Paragraph(
        "DISCLAIMER: This newsletter is for informational and educational purposes only. "
        "It does not constitute financial advice, investment recommendations, or a solicitation to buy "
        "or sell any security. All trading involves risk, including the possible loss of principal. "
        "Past performance is not indicative of future results. Always conduct your own due diligence "
        "and consult a qualified financial advisor before making investment decisions. "
        "Data sourced from CNBC, Yahoo Finance, Wolf Street, Kpler, CSIS, and other publicly available sources.",
        styles["Disclaimer"]
    ))

    doc.build(story)
    print(f"✅ PDF generated: {OUTPUT_FILE}")


if __name__ == "__main__":
    build_pdf()
