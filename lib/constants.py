"""Shared constants, enums, and type definitions for the trading system."""

from enum import Enum


class Pillar(str, Enum):
    MARKET = "market"
    POLYMARKET = "polymarket"


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"
    YES = "yes"
    NO = "no"


class TradeStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class SignalType(str, Enum):
    TECHNICAL_BREAKOUT = "technical_breakout"
    SENTIMENT_SHIFT = "sentiment_shift"
    TRADER_ACCUMULATION = "trader_accumulation"
    POLYMARKET_WHALE_ENTRY = "polymarket_whale_entry"
    NEWS_CATALYST = "news_catalyst"
    VOLUME_ANOMALY = "volume_anomaly"
    CROSS_ASSET_CORRELATION = "cross_asset_correlation"


class RiskVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class Strategy(str, Enum):
    MOMENTUM_BREAKOUT = "momentum_breakout"
    MEAN_REVERSION = "mean_reversion"
    NEWS_CATALYST = "news_catalyst"
    COPY_TRADE = "copy_trade"


class AssetClass(str, Enum):
    """Coarse asset class taxonomy. Each maps to a broker adapter in lib/brokers/.

    `kept_for_pillar` indicates which pillar handles this class:
      MARKET     — all crypto + stocks/bonds/CFDs
      POLYMARKET — only PM contracts
    """

    CRYPTO_PERP = "crypto_perp"          # Bybit derivatives
    CRYPTO_SPOT = "crypto_spot"          # Bybit / Binance spot
    STOCK_EQUITY = "stock_equity"        # Alpaca, IBKR
    BOND_ETF = "bond_etf"                # TLT, IEF, AGG via Alpaca/IBKR
    BOND_FUTURE = "bond_future"          # ZN, ZB futures via IBKR
    FOREX_SPOT = "forex_spot"            # EUR/USD etc. via IBKR/oanda
    CFD_INDEX = "cfd_index"              # SPX500, NAS100 via CFD broker
    CFD_COMMODITY = "cfd_commodity"      # XAU/USD, oil via CFD broker
    CFD_FOREX = "cfd_forex"              # FX as CFD
    POLYMARKET_BINARY = "polymarket_binary"  # PM YES/NO contracts
    UNKNOWN = "unknown"


# Adapter availability — gates which classes the system will actually trade.
# Stage 4 will flip stocks/bonds/CFDs to True once their adapters are
# verified end-to-end with a paper account. Keep crypto-only on by default.
ASSET_CLASS_ENABLED: dict[AssetClass, bool] = {
    AssetClass.CRYPTO_PERP: True,
    AssetClass.CRYPTO_SPOT: True,
    AssetClass.STOCK_EQUITY: True,        # Paper-only: priced via Yahoo (delayed ~15s; closed outside RTH)
    AssetClass.BOND_ETF: True,            # Paper-only: priced via Yahoo (delayed ~15s; closed outside RTH)
    AssetClass.BOND_FUTURE: False,
    AssetClass.FOREX_SPOT: True,          # Paper-only: priced via Yahoo (24/5 except weekends)
    AssetClass.CFD_INDEX: True,           # Paper-only: priced via Yahoo Finance public feed
    AssetClass.CFD_COMMODITY: True,       # Paper-only: priced via Yahoo Finance public feed
    AssetClass.CFD_FOREX: False,
    AssetClass.POLYMARKET_BINARY: False,  # Stage 3
    AssetClass.UNKNOWN: False,
}


class AlertType(str, Enum):
    TRADE_EXECUTED = "trade_executed"
    TRADE_CLOSED = "trade_closed"
    STOP_LOSS_HIT = "stop_loss_hit"
    CIRCUIT_BREAKER = "circuit_breaker_triggered"
    DAILY_REPORT = "daily_report"
    WEEKLY_REPORT = "weekly_report"
    HIGH_CONFLUENCE = "high_confluence_alert"
    NEWS_URGENT = "news_urgent"
    SYSTEM_ERROR = "system_error"
    DRAWDOWN_WARNING = "drawdown_warning"
    PM_BET_PLACED = "polymarket_bet_placed"
    PM_BET_RESOLVED = "polymarket_bet_resolved"


# Confluence thresholds
MIN_CONFLUENCE_SCORE = 60
HIGH_CONFLUENCE_SCORE = 80


def get_effective_min_score() -> float:
    """Resolve the confluence threshold actually in use.

    PAPER_MODE=true uses the loosened paper-mode override from risk_params.json
    so the system can build a richer paper sample. Live mode uses the strict
    MIN_CONFLUENCE_SCORE. Any caller that decides whether to act on an alert
    MUST use this value, not the raw constant — otherwise tier labels and
    execution gates can diverge.
    """
    import json
    import os

    if os.environ.get("PAPER_MODE", "").lower() != "true":
        return float(MIN_CONFLUENCE_SCORE)
    try:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        cfg_path = os.path.join(root, "config", "risk_params.json")
        with open(cfg_path) as f:
            cfg = json.load(f)
        return float(cfg.get("paper_mode_overrides", {}).get("min_confluence_score", MIN_CONFLUENCE_SCORE))
    except Exception:
        return float(MIN_CONFLUENCE_SCORE)

# Risk defaults
DEFAULT_ATR_MULTIPLIER = 2.0
DEFAULT_LEVERAGE = 3
MAX_LEVERAGE = 10
MAX_RISK_PER_TRADE_PCT = 2.0
MAX_DAILY_DRAWDOWN_PCT = 6.0
MAX_WEEKLY_DRAWDOWN_PCT = 15.0
MAX_PORTFOLIO_EXPOSURE_PCT = 30.0

# Polymarket defaults
PM_MIN_EDGE_PCT = 5.0
PM_KELLY_FRACTION = 0.25
PM_MAX_BET_PCT = 5.0

# Paths (relative to project root)
CONFIG_DIR = "config"
DATA_DIR = "data"
DB_PATH = "data/db/trading.db"
MEMORY_DIR = "data/memory"
SIGNALS_DIR = "data/signals"
REPORTS_DIR = "data/reports"
