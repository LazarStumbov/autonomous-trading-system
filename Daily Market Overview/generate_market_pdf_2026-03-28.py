from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
import os

OUTPUT_PATH = "/Users/lazarstumbov/Documents/Business/Trading/Daily Market Overview/Daily_Market_Overview_2026-03-28.pdf"

# ── Colour palette ───────────────────────────────────────────────
DARK_BG      = colors.HexColor("#0D1117")
ACCENT_GOLD  = colors.HexColor("#C9A84C")
ACCENT_GREEN = colors.HexColor("#2EA84F")
ACCENT_RED   = colors.HexColor("#E63946")
ACCENT_BLUE  = colors.HexColor("#1E90FF")
LIGHT_GRAY   = colors.HexColor("#8B949E")
WHITE        = colors.HexColor("#E6EDF3")
CARD_BG      = colors.HexColor("#161B22")
BORDER_COLOR = colors.HexColor("#30363D")

# ── Styles ────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

def S(name, **kw):
    return ParagraphStyle(name, **kw)

TITLE_STYLE = S("NewsTitle",
    fontName="Helvetica-Bold", fontSize=28, textColor=ACCENT_GOLD,
    alignment=TA_CENTER, spaceAfter=4)

SUBTITLE_STYLE = S("NewsSubtitle",
    fontName="Helvetica", fontSize=11, textColor=LIGHT_GRAY,
    alignment=TA_CENTER, spaceAfter=2)

DATE_STYLE = S("NewsDate",
    fontName="Helvetica", fontSize=10, textColor=LIGHT_GRAY,
    alignment=TA_CENTER, spaceAfter=14)

SECTION_HEADER = S("SecHeader",
    fontName="Helvetica-Bold", fontSize=13, textColor=ACCENT_GOLD,
    spaceBefore=14, spaceAfter=6, borderPadding=(0,0,3,0))

BODY_STYLE = S("Body",
    fontName="Helvetica", fontSize=9.5, textColor=WHITE,
    leading=15, spaceAfter=6)

BODY_BOLD = S("BodyBold",
    fontName="Helvetica-Bold", fontSize=9.5, textColor=WHITE,
    leading=15, spaceAfter=4)

BULLET_STYLE = S("Bullet",
    fontName="Helvetica", fontSize=9.5, textColor=WHITE,
    leading=14, leftIndent=14, spaceAfter=3)

LABEL_STYLE = S("Label",
    fontName="Helvetica-Bold", fontSize=8.5, textColor=ACCENT_GOLD,
    leading=12)

VALUE_GREEN = S("ValGreen",
    fontName="Helvetica-Bold", fontSize=9.5, textColor=ACCENT_GREEN,
    leading=12, alignment=TA_RIGHT)

VALUE_RED = S("ValRed",
    fontName="Helvetica-Bold", fontSize=9.5, textColor=ACCENT_RED,
    leading=12, alignment=TA_RIGHT)

VALUE_WHITE = S("ValWhite",
    fontName="Helvetica-Bold", fontSize=9.5, textColor=WHITE,
    leading=12, alignment=TA_RIGHT)

STRATEGY_HEADER = S("StratHeader",
    fontName="Helvetica-Bold", fontSize=11, textColor=ACCENT_BLUE,
    spaceBefore=8, spaceAfter=5)

DISCLAIMER_STYLE = S("Disclaimer",
    fontName="Helvetica-Oblique", fontSize=7.5, textColor=LIGHT_GRAY,
    alignment=TA_CENTER, leading=11)

# ── Helper: section divider ────────────────────────────────────────
def divider():
    return HRFlowable(width="100%", thickness=0.5, color=BORDER_COLOR,
                      spaceAfter=6, spaceBefore=2)

# ── Helper: market table row ───────────────────────────────────────
def mkt_row(label, value, change, positive=True):
    val_style = VALUE_GREEN if positive else VALUE_RED
    change_style = VALUE_GREEN if positive else VALUE_RED
    return [
        Paragraph(label, LABEL_STYLE),
        Paragraph(value, VALUE_WHITE),
        Paragraph(change, val_style),
    ]

# ── Build story ────────────────────────────────────────────────────
story = []

# ── Header banner ──────────────────────────────────────────────────
story.append(Spacer(1, 8))
story.append(Paragraph("DAILY MARKET OVERVIEW", TITLE_STYLE))
story.append(Paragraph("Professional Trading Intelligence Report", SUBTITLE_STYLE))
story.append(Paragraph("Saturday, March 28, 2026  |  Published by Your AI Trading Desk  |  Week-End Edition", DATE_STYLE))
story.append(divider())

# ── Weekly Summary Banner ──────────────────────────────────────────
story.append(Paragraph(
    "\u26a0  WEEK-END EDITION — Reporting on the March 27 close. Markets closed for the weekend. "
    "The S&P 500 has now posted its <b>5th consecutive losing week</b>, the longest streak since 2022. "
    "Stagflation fears, Iran War disruptions, and Fed rate-hike speculation define the macro backdrop heading into April.",
    BODY_STYLE))

# ── 1. Market Snapshot ─────────────────────────────────────────────
story.append(divider())
story.append(Paragraph("1. MARKET SNAPSHOT  (Friday, March 27 Close)", SECTION_HEADER))

snap_data = [
    [Paragraph("INSTRUMENT", LABEL_STYLE),
     Paragraph("LEVEL", LABEL_STYLE),
     Paragraph("CHANGE", LABEL_STYLE)],
    mkt_row("S&P 500 (SPX)", "6,368.85", "-1.67%  (-108 pts)", False),
    mkt_row("Dow Jones (DJIA)", "45,166.64", "-1.73%  (-793 pts)", False),
    mkt_row("Nasdaq Composite", "20,948.36", "-2.15%  (-460 pts)", False),
    mkt_row("CBOE VIX (Fear Index)", "31.05", "+13.16%  (Elevated Fear)", False),
    mkt_row("WTI Crude Oil", "$99.64 / bbl", "+5.46%  (Near $100)", False),
    mkt_row("Brent Crude", "$112.57 / bbl", "+4.22%", False),
    mkt_row("Gold (XAU/USD)", "$4,433.53 / oz", "Safe-Haven Bid", True),
    mkt_row("Bitcoin (BTC/USD)", "$66,587", "Risk-Off Pressure", False),
    mkt_row("10-Yr Treasury Yield", "~4.55%", "Rising (Inflation Fears)", False),
]

snap_table = Table(snap_data, colWidths=[2.6*inch, 2.2*inch, 2.2*inch])
snap_table.setStyle(TableStyle([
    ("BACKGROUND",    (0,0), (-1,0),  DARK_BG),
    ("BACKGROUND",    (0,1), (-1,-1), CARD_BG),
    ("ROWBACKGROUNDS",(0,1), (-1,-1), [CARD_BG, colors.HexColor("#1A222C")]),
    ("GRID",          (0,0), (-1,-1), 0.4, BORDER_COLOR),
    ("TOPPADDING",    (0,0), (-1,-1), 6),
    ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ("LEFTPADDING",   (0,0), (-1,-1), 8),
    ("RIGHTPADDING",  (0,0), (-1,-1), 8),
    ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
]))
story.append(snap_table)
story.append(Spacer(1, 10))

# ── 2. Key Market Drivers ──────────────────────────────────────────
story.append(divider())
story.append(Paragraph("2. KEY MARKET DRIVERS", SECTION_HEADER))

drivers = [
    ("<b>Iran War — Strait of Hormuz Crisis (Primary Driver):</b> The 2026 Iran War, which began "
     "February 28 with US-Israeli airstrikes, has triggered the most severe global oil supply "
     "disruption since the 1970s. Flows through the Strait of Hormuz have fallen from ~20 mb/d "
     "to a trickle; Gulf producers have cut output by at least 10 mb/d. WTI crude approached "
     "$100/bbl and Brent crossed $112. Trump extended a pause on attacks on Iran's energy "
     "infrastructure through April 6, but Iran flatly rejected direct US talks, dashing "
     "de-escalation hopes and keeping the risk premium embedded in energy prices."),

    ("<b>Fed Rate-Hike Odds Cross 50% for the First Time:</b> Futures markets now assign a 52% "
     "probability of at least one Fed rate hike by end-2026 — the first time this threshold has "
     "been crossed. The March 18 FOMC held at 3.50–3.75%, but elevated oil prices, sticky "
     "inflation, and tariff-driven import costs are forcing the market to reconsider whether the "
     "next move is a cut or a hike. Fed Chair Powell acknowledged the war and tariffs "
     "'complicate the picture on both sides of the dual mandate.'"),

    ("<b>Tariff Shock — Largest US Tax Increase Since 1993:</b> Trump's tariff package now "
     "constitutes the largest US tax increase as a percentage of GDP since 1993, averaging "
     "$1,500 per household in 2026. February import prices surged +1.3% MoM (largest since "
     "March 2022) and export prices +1.5% (largest since May 2022). Core PCE is tracking at "
     "2.7%. Stagflation risk — slowing growth alongside rising prices — is the dominant "
     "macro concern heading into Q2 2026."),

    ("<b>Magnificent Seven Collapse — $300B in Market Cap Erased:</b> The Mag 7 fell 5.9% "
     "collectively on Friday, shedding over $300 billion in market cap in a single session. "
     "Microsoft led the decline at -17.4% YTD, followed by Tesla at -11.3%. These seven "
     "names represent 33.3% of the S&P 500, meaning their weakness disproportionately "
     "drags the index. High-multiple tech is acutely vulnerable to rate-hike speculation."),

    ("<b>Consumer Confidence Deteriorating:</b> Carnival Corporation (CCL) cut its full-year "
     "2026 outlook, citing the direct impact of surging fuel costs. This is a leading "
     "indicator of consumer-facing sectors: travel, leisure, and retail face a "
     "stagflationary squeeze — higher costs alongside cautious consumer spending."),
]

for d in drivers:
    story.append(Paragraph(d, BODY_STYLE))

# ── 3. Top Movers ──────────────────────────────────────────────────
story.append(divider())
story.append(Paragraph("3. TOP MOVERS", SECTION_HEADER))

movers_data = [
    [Paragraph("TICKER", LABEL_STYLE),
     Paragraph("MOVE", LABEL_STYLE),
     Paragraph("CATALYST", LABEL_STYLE)],
    [Paragraph("Microsoft (MSFT)",  BODY_STYLE),
     Paragraph("-17.4% YTD", VALUE_RED),
     Paragraph("AI capex scrutiny; rate-hike fears crush high-multiple tech; Mag 7 rotation", BODY_STYLE)],
    [Paragraph("Tesla (TSLA)", BODY_STYLE),
     Paragraph("-11.3% YTD", VALUE_RED),
     Paragraph("Consumer confidence weakness; Musk distraction; EV demand slowdown", BODY_STYLE)],
    [Paragraph("Carnival Corp (CCL)", BODY_STYLE),
     Paragraph("-4.0%", VALUE_RED),
     Paragraph("Lowered FY2026 guidance; oil price surge directly impacts fuel costs", BODY_STYLE)],
    [Paragraph("Energy Sector (XLE)", BODY_STYLE),
     Paragraph("+3–5%", VALUE_GREEN),
     Paragraph("WTI near $100; Hormuz supply shock; CVX, XOM, OXY outperform", BODY_STYLE)],
    [Paragraph("Defense (RTX, LMT)", BODY_STYLE),
     Paragraph("+2–3%", VALUE_GREEN),
     Paragraph("Iran War escalation; NATO defence budget hikes; geopolitical premium", BODY_STYLE)],
    [Paragraph("Gold (GLD)", BODY_STYLE),
     Paragraph("Near $4,433/oz", VALUE_GREEN),
     Paragraph("Stagflation hedge; geopolitical safe haven; dollar uncertainty", BODY_STYLE)],
    [Paragraph("WTI Crude (USO)", BODY_STYLE),
     Paragraph("+5.46%", VALUE_RED),
     Paragraph("Iran-Hormuz supply crisis; Iran rejects US talks; supply 10 mb/d short", BODY_STYLE)],
]

movers_table = Table(movers_data, colWidths=[1.7*inch, 1.0*inch, 4.3*inch])
movers_table.setStyle(TableStyle([
    ("BACKGROUND",    (0,0), (-1,0),  DARK_BG),
    ("ROWBACKGROUNDS",(0,1), (-1,-1), [CARD_BG, colors.HexColor("#1A222C")]),
    ("GRID",          (0,0), (-1,-1), 0.4, BORDER_COLOR),
    ("TOPPADDING",    (0,0), (-1,-1), 6),
    ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ("LEFTPADDING",   (0,0), (-1,-1), 8),
    ("RIGHTPADDING",  (0,0), (-1,-1), 8),
    ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
]))
story.append(movers_table)
story.append(Spacer(1, 10))

# ── 4. Trading Strategy ────────────────────────────────────────────
story.append(divider())
story.append(Paragraph("4. TRADING STRATEGY", SECTION_HEADER))

story.append(Paragraph(
    "\u26a0  MACRO REGIME: <b>STAGFLATION / RISK-OFF.</b>  The playbook has shifted. "
    "The dominant themes are energy supply shock, rate-hike risk, and multiple compression "
    "in tech. The strategy is: <b>rotate from growth to value, energy, defense, and real assets.</b>",
    BODY_BOLD))

story.append(Spacer(1, 6))

# Short-term
story.append(Paragraph("SHORT-TERM STRATEGY (Monday Open – 1 Week)", STRATEGY_HEADER))
story.append(Paragraph(
    "Expect continued volatility at the open. Oil headlines will dominate — any Iran "
    "escalation or ceasefire signal will move markets sharply. Position defensively "
    "and use options for defined-risk exposure.", BODY_STYLE))

short_term = [
    ("<b>LONG Energy (XLE / CVX / XOM):</b> With WTI near $100 and Hormuz flows at a "
     "fraction of normal, integrated oil majors are printing cash. Add exposure on any "
     "intraday pullback. Stop below the $95/bbl WTI level. Target: $110 WTI = XLE +10–15%."),
    ("<b>LONG Gold (GLD / IAU):</b> Gold is the stagflation trade. It combines a "
     "geopolitical hedge with an inflation hedge. Hold a core position. Add if gold "
     "pulls back to $4,350–4,380. Next target: $4,600+."),
    ("<b>LONG Defense (RTX / LMT / NOC):</b> Iran War escalation supports defence budgets "
     "globally. These names outperform regardless of war outcome — escalation = more "
     "contracts; de-escalation = commercial aviation recovery (RTX dual benefit). "
     "RTX is the strongest risk/reward in the sector."),
    ("<b>SHORT / AVOID Magnificent Seven (MSFT, TSLA, META, NVDA):</b> Rate-hike "
     "probability at 52% is poison for high-multiple growth stocks. With VIX at 31, "
     "consider buying put spreads on QQQ or MSFT for portfolio protection. "
     "Risk: any Iran ceasefire announcement will trigger a sharp tech bounce."),
    ("<b>SHORT Consumer Discretionary (XLY / CCL / RCL):</b> Carnival's guidance cut "
     "is a warning shot for the entire leisure/travel sector. Fuel-cost exposure plus "
     "weakening consumer confidence = earnings risk. Bear call spreads on XLY offer "
     "defined-risk short exposure into Q1 earnings season."),
    ("<b>AVOID / REDUCE Bitcoin:</b> Crypto is in risk-off mode. BTC at $66,587 is "
     "down significantly from highs. Rate-hike speculation is headwind. Only re-enter "
     "on confirmed geopolitical de-escalation or dovish Fed pivot signal."),
]
for b in short_term:
    story.append(Paragraph(f"\u2022  {b}", BULLET_STYLE))

story.append(Spacer(1, 8))

# Medium-term
story.append(Paragraph("MEDIUM-TERM STRATEGY (1 Week – 3 Months)", STRATEGY_HEADER))
story.append(Paragraph(
    "April 6 is a critical inflection point — Trump's pause on strikes against Iran's "
    "energy infrastructure expires. Market pricing will be driven by whether talks "
    "resume, escalate, or remain frozen. Position for multiple scenarios.", BODY_STYLE))

medium_term = [
    ("<b>SCENARIO A — Escalation (Base Case, 55%):</b> Iran rejects talks; strikes resume "
     "after April 6. Oil spikes toward $120–130. Double down on energy, defense, gold. "
     "Reduce equity beta sharply. Buy TLT puts (rates rise further)."),
    ("<b>SCENARIO B — Ceasefire Signal (30%):</b> Any credible negotiation framework "
     "sends oil down 15–20% instantly. This would be a massive relief rally — tech and "
     "growth bounce hard. Pre-position a small long in QQQ calls as a 'ceasefire lottery.'"),
    ("<b>SCENARIO C — Stalemate (15%):</b> Oil stays $90–105. Markets grind lower "
     "on Fed uncertainty and tariff drag. Value, dividend growers, and Staples "
     "(PG, KO, WMT) outperform. PCE data (next release Apr 30) becomes the pivotal event."),
    ("<b>OVERWEIGHT Commodities Broadly:</b> Oil, gold, and agricultural commodities "
     "all benefit from the Hormuz disruption and tariff-driven supply chain stress. "
     "DJP (broad commodity ETF) is a clean macro hedge."),
    ("<b>UNDERWEIGHT Long-Duration Bonds:</b> With rate-hike odds at 52%, TLT (20+ yr "
     "Treasury ETF) faces further headwinds. Reduce duration. Prefer short-duration "
     "Treasuries (SHY) or TIPS for inflation protection."),
]
for b in medium_term:
    story.append(Paragraph(f"\u2022  {b}", BULLET_STYLE))

story.append(Spacer(1, 8))

# Long-term
story.append(Paragraph("LONG-TERM STRATEGIC THEMES (3 Months – 1 Year)", STRATEGY_HEADER))
long_term = [
    ("<b>Iran War Resolution = Deflationary Supercycle Reversal:</b> A full ceasefire "
     "and reopening of the Strait of Hormuz would be the single most deflationary "
     "macro event possible. Oil back to $70–75 would cut CPI by ~1.5pp, accelerate "
     "Fed cuts, and massively re-rate growth stocks. This is the most asymmetric "
     "long-term trade: hold a small position in tech/QQQ as a ceasefire option."),
    ("<b>Stagflation-Proof Portfolio Construction:</b> Build around the 1970s playbook: "
     "energy (XLE), commodities (GLD, DJP), real assets (REITs with pricing power), "
     "dividend compounders (BRK.B, PG, KO), and short-duration bonds. Reduce "
     "pure-growth, long-duration, and highly-leveraged balance sheets."),
    ("<b>AI Infrastructure — Selective, Not Broad:</b> Despite tech's selloff, the AI "
     "capex supercycle is intact. Data centers still need power. Infrastructure "
     "plays (VST, CEG — nuclear power for AI data centers) are more insulated "
     "than pure software/SaaS names."),
    ("<b>Tariff De-escalation Trade:</b> If the US-China or US-EU trade situation "
     "improves, it will relieve supply chain pressure and reduce input costs. "
     "Industrial supply chains (reshoring plays: FAST, EMR) benefit from "
     "both escalation (domestic demand) and de-escalation (normalized trade flows)."),
]
for b in long_term:
    story.append(Paragraph(f"\u2022  {b}", BULLET_STYLE))

# ── 5. Risk Factors ────────────────────────────────────────────────
story.append(divider())
story.append(Paragraph("5. KEY RISKS TO MONITOR", SECTION_HEADER))

risks = [
    "<b>April 6 — Trump Pause Expires:</b> If strikes on Iran's energy infrastructure resume, expect oil to spike toward $110–120 and equities to sell off sharply.",
    "<b>April 28–29 FOMC:</b> If inflation data deteriorates further before the meeting, the Fed may signal a hike. Markets are not positioned for this — the selloff could be severe.",
    "<b>PCE / CPI Surprise:</b> Any inflation print above 2.8% (core PCE) or 3.5% (CPI) will accelerate rate-hike pricing and crush growth stocks.",
    "<b>Mag 7 Earnings (April):</b> Microsoft, Alphabet, Meta, and Amazon report in late April. Guidance cuts tied to AI capex uncertainty or demand softness could trigger another leg down.",
    "<b>Recession Signal:</b> VIX at 31 + oil at $100 + consumer confidence falling = classic pre-recession setup. Watch ISM Manufacturing PMI on March 31 as a leading indicator.",
    "<b>Dollar Volatility:</b> Stagflation is ambiguous for the USD. Tariffs are mildly bullish; rate-hike expectations are bullish; growth fears are bearish. Currency hedges warranted for international positions.",
]
for r in risks:
    story.append(Paragraph(f"\u2022  {r}", BULLET_STYLE))

# ── 6. Economic Calendar ───────────────────────────────────────────
story.append(divider())
story.append(Paragraph("6. UPCOMING ECONOMIC CALENDAR", SECTION_HEADER))

cal_data = [
    [Paragraph("DATE", LABEL_STYLE),
     Paragraph("EVENT", LABEL_STYLE),
     Paragraph("IMPACT", LABEL_STYLE)],
    [Paragraph("Mar 28 (Today)", BODY_STYLE),
     Paragraph("Univ. of Michigan Consumer Sentiment — Final (Mar)", BODY_STYLE),
     Paragraph("MEDIUM — consumer confidence read", VALUE_WHITE)],
    [Paragraph("Mar 31", BODY_STYLE),
     Paragraph("ISM Manufacturing PMI (Mar)", BODY_STYLE),
     Paragraph("HIGH — recession watch signal", VALUE_RED)],
    [Paragraph("Apr 1", BODY_STYLE),
     Paragraph("JOLTS Job Openings (Feb)", BODY_STYLE),
     Paragraph("MEDIUM — labor market health", VALUE_WHITE)],
    [Paragraph("Apr 2", BODY_STYLE),
     Paragraph("Non-Farm Payrolls (Mar) + Unemployment Rate", BODY_STYLE),
     Paragraph("HIGH — key Fed input", VALUE_RED)],
    [Paragraph("Apr 6", BODY_STYLE),
     Paragraph("Trump Iran Strike Pause Expires — Geopolitical X-Factor", BODY_STYLE),
     Paragraph("CRITICAL — market-moving", VALUE_RED)],
    [Paragraph("Apr 28–29", BODY_STYLE),
     Paragraph("FOMC Rate Decision", BODY_STYLE),
     Paragraph("HIGH — hike vs. hold pivotal", VALUE_RED)],
    [Paragraph("Apr 30", BODY_STYLE),
     Paragraph("PCE Inflation (Mar) — Fed's Preferred Gauge", BODY_STYLE),
     Paragraph("HIGH — inflation trajectory", VALUE_RED)],
]

cal_table = Table(cal_data, colWidths=[1.1*inch, 3.6*inch, 2.3*inch])
cal_table.setStyle(TableStyle([
    ("BACKGROUND",    (0,0), (-1,0),  DARK_BG),
    ("ROWBACKGROUNDS",(0,1), (-1,-1), [CARD_BG, colors.HexColor("#1A222C")]),
    ("GRID",          (0,0), (-1,-1), 0.4, BORDER_COLOR),
    ("TOPPADDING",    (0,0), (-1,-1), 6),
    ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ("LEFTPADDING",   (0,0), (-1,-1), 8),
    ("RIGHTPADDING",  (0,0), (-1,-1), 8),
    ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
]))
story.append(cal_table)
story.append(Spacer(1, 14))

# ── Footer disclaimer ──────────────────────────────────────────────
story.append(divider())
story.append(Paragraph(
    "DISCLAIMER: This newsletter is generated for informational and educational purposes only. "
    "It does not constitute financial advice or a solicitation to buy or sell any security. "
    "Data sourced from CNBC, Yahoo Finance, Bloomberg, Al Jazeera, Fortune, CBS News, IEA, and public filings "
    "as of March 27–28, 2026. Past performance is not indicative of future results. Trade at your own risk.",
    DISCLAIMER_STYLE))

# ── Build PDF ──────────────────────────────────────────────────────
doc = SimpleDocTemplate(
    OUTPUT_PATH,
    pagesize=letter,
    leftMargin=0.65*inch,
    rightMargin=0.65*inch,
    topMargin=0.6*inch,
    bottomMargin=0.6*inch,
    title="Daily Market Overview – March 28, 2026",
    author="AI Trading Desk",
)

def dark_canvas(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(DARK_BG)
    canvas.rect(0, 0, letter[0], letter[1], fill=1, stroke=0)
    canvas.restoreState()

doc.build(story, onFirstPage=dark_canvas, onLaterPages=dark_canvas)
print(f"PDF saved to: {OUTPUT_PATH}")
