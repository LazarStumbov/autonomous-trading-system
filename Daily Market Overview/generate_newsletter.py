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

OUTPUT_PATH = "/Users/lazarstumbov/Documents/Business/Trading/Daily Market Overview/Daily_Market_Overview_2026-03-25.pdf"

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
story.append(Paragraph("Wednesday, March 25, 2026  |  Published by Your AI Trading Desk", DATE_STYLE))
story.append(divider())

# ── 1. Market Snapshot ─────────────────────────────────────────────
story.append(Paragraph("1. MARKET SNAPSHOT", SECTION_HEADER))

snap_data = [
    [Paragraph("INSTRUMENT", LABEL_STYLE),
     Paragraph("LEVEL", LABEL_STYLE),
     Paragraph("CHANGE", LABEL_STYLE)],
    mkt_row("S&P 500 (SPX)", "~5,450", "+0.75%", True),
    mkt_row("Dow Jones (DJIA)", "+330 pts", "+0.77%", True),
    mkt_row("Nasdaq Composite", "~17,200", "+0.92%", True),
    mkt_row("WTI Crude Oil", "$88.48 / bbl", "-$4.00  (-4.3%)", False),
    mkt_row("Gold (XAU/USD)", "$4,547 / oz", "+$145  (+3.3%)", True),
    mkt_row("Bitcoin (BTC/USD)", "$71,669", "+$1,101  (+1.6%)", True),
    mkt_row("10-Yr Treasury Yield", "~4.25%", "Lower (risk-on)", True),
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
    ("<b>US-Iran Ceasefire Diplomacy (Primary Driver):</b> President Trump sent Tehran a "
     "15-point ceasefire proposal, sparking a broad risk-on rally. WTI crude tumbled over "
     "4% as the market priced in a potential re-opening of the Strait of Hormuz — which "
     "carries ~20% of global oil supply. Iran's hawkish public response tempers optimism, "
     "keeping geopolitical risk premium partially elevated."),

    ("<b>ARM Holdings — Landmark Chip Pivot (+20%):</b> ARM announced its first proprietary "
     "in-house chip, the AGI CPU, engineered for AI inference in data centres. Meta is the "
     "anchor customer. CEO Rene Haas projects $15B in chip-related revenue by 2031, "
     "representing a radical reversal of the pure-licensing model. SoftBank (ARM majority "
     "owner) surged 7.9% in Tokyo."),

    ("<b>Semiconductor Supply Squeeze:</b> Intel (+5%) and AMD (+5%) both announced price "
     "hikes amid a worsening CPU shortage. Manufacturers are pivoting toward ARM-based "
     "alternatives. Broader chip sector sentiment is constructive."),

    ("<b>Amazon — AWS Upgrade:</b> Citigroup reiterated Buy and raised the price target to "
     "$285 (from $65), projecting AWS revenue growth of +28% YoY in Q1 2026. Amazon "
     "shares gained 2.50% on the session."),

    ("<b>Federal Reserve — Rates on Hold:</b> The March 18 FOMC meeting held the fed funds "
     "rate at 3.50–3.75%. The dot plot signals one cut in 2026 and one in 2027. 2026 PCE "
     "inflation revised up slightly to 2.7%; GDP growth projected at 2.4% for 2026."),
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
    [Paragraph("ARM Holdings (ARM)",  BODY_STYLE),
     Paragraph("+20%", VALUE_GREEN),
     Paragraph("AGI CPU launch; Meta anchor customer; $15B revenue target by 2031", BODY_STYLE)],
    [Paragraph("AMD", BODY_STYLE),
     Paragraph("+5%", VALUE_GREEN),
     Paragraph("CPU price hike announcement amid global chip shortage", BODY_STYLE)],
    [Paragraph("Intel (INTC)", BODY_STYLE),
     Paragraph("+5%", VALUE_GREEN),
     Paragraph("Price hikes planned; benefits from chip shortage pricing power", BODY_STYLE)],
    [Paragraph("Amazon (AMZN)", BODY_STYLE),
     Paragraph("+2.50%", VALUE_GREEN),
     Paragraph("Citi PT raised to $285; AWS Q1 2026 growth est. +28% YoY", BODY_STYLE)],
    [Paragraph("Amgen (AMGN)", BODY_STYLE),
     Paragraph("+1.79%", VALUE_GREEN),
     Paragraph("Defensive sector rotation; positive biotech sentiment", BODY_STYLE)],
    [Paragraph("Boeing (BA)", BODY_STYLE),
     Paragraph("+1.77%", VALUE_GREEN),
     Paragraph("Geopolitical de-escalation; industrial sector bid", BODY_STYLE)],
    [Paragraph("WTI Crude Oil", BODY_STYLE),
     Paragraph("-4.3%", VALUE_RED),
     Paragraph("US-Iran ceasefire proposal; Hormuz supply-disruption premium deflating", BODY_STYLE)],
]

movers_table = Table(movers_data, colWidths=[1.6*inch, 0.8*inch, 4.6*inch])
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

# Short-term
story.append(Paragraph("SHORT-TERM STRATEGY (Today – 1 Week)", STRATEGY_HEADER))
story.append(Paragraph(
    "The dominant trade is <b>long risk / short energy</b>. Markets are pricing a "
    "ceasefire premium; as long as diplomatic rhetoric remains positive, equities benefit "
    "while oil faces continued headwinds.", BODY_STYLE))

short_term = [
    ("<b>LONG ARM Holdings (ARM):</b> Momentum is strong post-announcement. Consider a "
     "buy-the-breakout entry above today's close with a tight stop ~10% below. Target: "
     "prior November highs. Risk: ARM overshoots on hype — scale in rather than chasing."),
    ("<b>LONG Semiconductor ETF (SOXX / SMH):</b> ARM rally lifts the sector. Intel and "
     "AMD price hikes signal pricing power returning. This is a 1–2 week momentum trade."),
    ("<b>LONG Amazon (AMZN):</b> Citi's upgraded PT ($285) gives a near-term catalyst. "
     "AWS cloud revenue growth story intact. Entry on any intraday dips."),
    ("<b>SHORT WTI Crude / Long Energy Shorts (USO puts or bear spreads):</b> The "
     "ceasefire trade has legs. If Iran accepts any part of the 15-point plan, oil drops "
     "further toward $80. Defined-risk options structure recommended given Iran's "
     "hawkish denial adds headline risk."),
    ("<b>LONG Gold (GLD):</b> Gold's +3.3% move today reflects dual demand — geopolitical "
     "hedge AND inflation hedge. Hold gold alongside equities as long as uncertainty "
     "persists. Take partial profits if a formal ceasefire is announced."),
    ("<b>LONG Raytheon (RTX) — Options Play:</b> 30-day IV at ~31.6% makes "
     "strangles attractive ahead of any major geopolitical announcement. A strangle "
     "captures the move in either direction (ceasefire = down; escalation = up)."),
]
for b in short_term:
    story.append(Paragraph(f"\u2022  {b}", BULLET_STYLE))

story.append(Spacer(1, 8))

# Medium / Long term
story.append(Paragraph("MEDIUM-TERM STRATEGY (1 Week – 3 Months)", STRATEGY_HEADER))
story.append(Paragraph(
    "Macro backdrop: Fed on hold, GDP +2.4%, inflation ticking up slightly. "
    "Risk assets remain supported unless Iran escalates or a second supply shock "
    "materialises. Focus on AI, cloud, and dividend growers.", BODY_STYLE))

medium_term = [
    ("<b>OVERWEIGHT AI / Cloud (AMZN, MSFT, GOOGL, ARM):</b> AWS +28% YoY growth, "
     "ARM's new chip, and the ongoing AI capex supercycle all point to sustained "
     "earnings growth. Add on dips."),
    ("<b>UNDERWEIGHT Energy (XLE):</b> Any ceasefire resolution would structurally "
     "remove the war-premium from oil. Even without full resolution, rising US "
     "inventories weigh. Reduce or hedge energy exposure."),
    ("<b>SELECTIVE INDUSTRIALS (BA, GE Aerospace):</b> Defence names benefit "
     "regardless of outcome — escalation drives defence budgets; de-escalation "
     "supports commercial aviation recovery. Boeing's rebound is a multi-month story."),
    ("<b>DIVIDEND GROWERS as Fed Hedge (MDLZ, BRK.B):</b> With only one Fed cut "
     "projected for 2026, dividend compounders with wide moats (Berkshire, "
     "Mondelez) offer equity-like returns with lower duration risk."),
    ("<b>BITCOIN / Digital Assets — Tactical Long:</b> BTC at $71,669, risk-on "
     "environment, and Fed pause (not hiking) all support crypto. Watch the "
     "$75,000 level as next resistance."),
]
for b in medium_term:
    story.append(Paragraph(f"\u2022  {b}", BULLET_STYLE))

story.append(Spacer(1, 8))

# Long term
story.append(Paragraph("LONG-TERM STRATEGIC THEMES (3 Months – 1 Year)", STRATEGY_HEADER))
long_term = [
    ("<b>AI Infrastructure Buildout:</b> ARM's chip pivot, AMD/Intel pricing power, and "
     "hyperscaler capex all point to a multi-year semiconductor supercycle."),
    ("<b>Middle East Geopolitical Resolution:</b> A full ceasefire would be a structural "
     "deflationary shock — oil back toward $70–75 would cut inflation, accelerate "
     "Fed cuts, and re-rate growth stocks higher."),
    ("<b>US Dollar & Treasury Positioning:</b> Fed holds at 3.5–3.75% while inflation "
     "prints 2.7%. Real yields remain attractive. Consider laddered Treasuries for "
     "cash management alongside equities."),
    ("<b>Emerging Market E-Commerce (MELI):</b> MercadoLibre's $300B annualised payment "
     "volume and 37% YoY merchandise growth offer compounding at scale. A core "
     "long-term position."),
]
for b in long_term:
    story.append(Paragraph(f"\u2022  {b}", BULLET_STYLE))

# ── 5. Risk Factors ────────────────────────────────────────────────
story.append(divider())
story.append(Paragraph("5. KEY RISKS TO MONITOR", SECTION_HEADER))

risks = [
    "<b>Iran Rejects 15-Point Proposal:</b> Any hawkish statement or renewed military action spikes oil and triggers equity sell-off.",
    "<b>Inflation Surprise:</b> PCE above 2.7% could force the Fed to delay cuts further, pressuring rate-sensitive growth stocks.",
    "<b>ARM Hype Unwind:</b> A +20% single-day move invites profit-taking. Watch for lock-up expiry and insider selling.",
    "<b>Semiconductor Supply Shock:</b> CPU shortage worsening could constrain cloud capex and delay AI deployments.",
    "<b>Bitcoin Volatility:</b> Digital asset markets remain correlated with risk sentiment — sharp reversals possible.",
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
    [Paragraph("Mar 26", BODY_STYLE),
     Paragraph("Fed Minutes Release", BODY_STYLE),
     Paragraph("HIGH — rate path clarity", VALUE_GREEN)],
    [Paragraph("Mar 27", BODY_STYLE),
     Paragraph("PCE Inflation (Feb)", BODY_STYLE),
     Paragraph("HIGH — key Fed gauge", VALUE_RED)],
    [Paragraph("Mar 28", BODY_STYLE),
     Paragraph("University of Michigan Sentiment (Final)", BODY_STYLE),
     Paragraph("MEDIUM", VALUE_WHITE)],
    [Paragraph("Mar 31", BODY_STYLE),
     Paragraph("ISM Manufacturing PMI", BODY_STYLE),
     Paragraph("MEDIUM — growth signal", VALUE_WHITE)],
    [Paragraph("Apr 2", BODY_STYLE),
     Paragraph("Non-Farm Payrolls (Mar)", BODY_STYLE),
     Paragraph("HIGH — labour market", VALUE_RED)],
]

cal_table = Table(cal_data, colWidths=[0.9*inch, 3.6*inch, 2.5*inch])
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
    "All data sourced from Bloomberg, CNBC, Yahoo Finance, Benzinga, and public filings as of "
    "March 25, 2026. Past performance is not indicative of future results. Trade at your own risk.",
    DISCLAIMER_STYLE))

# ── Build PDF ──────────────────────────────────────────────────────
doc = SimpleDocTemplate(
    OUTPUT_PATH,
    pagesize=letter,
    leftMargin=0.65*inch,
    rightMargin=0.65*inch,
    topMargin=0.6*inch,
    bottomMargin=0.6*inch,
    title="Daily Market Overview – March 25, 2026",
    author="AI Trading Desk",
)

def dark_canvas(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(DARK_BG)
    canvas.rect(0, 0, letter[0], letter[1], fill=1, stroke=0)
    canvas.restoreState()

doc.build(story, onFirstPage=dark_canvas, onLaterPages=dark_canvas)
print(f"PDF saved to: {OUTPUT_PATH}")
