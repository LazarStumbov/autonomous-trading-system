"""Unified market data fetcher. Abstracts multiple data sources into a single interface."""

import os
import time
import json
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()


class MarketDataFetcher:
    """Fetch market data from multiple sources with rate limiting."""

    def __init__(self):
        self.alpha_vantage_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
        self.finnhub_key = os.getenv("FINNHUB_API_KEY", "")
        self.cmc_key = os.getenv("COINMARKETCAP_API_KEY", "")
        self.marketaux_key = os.getenv("MARKETAUX_API_KEY", "")
        self._last_av_call = 0  # Rate limit: 5 calls/min for Alpha Vantage

    def _rate_limit_av(self):
        """Enforce Alpha Vantage rate limit (5 calls/min = 12s between calls)."""
        elapsed = time.time() - self._last_av_call
        if elapsed < 12:
            time.sleep(12 - elapsed)
        self._last_av_call = time.time()

    def fetch_crypto_price(self, symbol: str, source: str = "cmc") -> dict:
        """Fetch current crypto price.

        Args:
            symbol: e.g., "BTC", "ETH"
            source: "cmc" (CoinMarketCap) or "finnhub"

        Returns:
            Dict with price, change_24h, volume_24h, market_cap
        """
        if source == "cmc" and self.cmc_key:
            return self._fetch_cmc(symbol)
        elif source == "finnhub" and self.finnhub_key:
            return self._fetch_finnhub_crypto(symbol)
        return {"error": f"No API key for {source}"}

    def _fetch_cmc(self, symbol: str) -> dict:
        """Fetch from CoinMarketCap."""
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
        headers = {"X-CMC_PRO_API_KEY": self.cmc_key}
        params = {"symbol": symbol, "convert": "USD"}

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()["data"][symbol]
            quote = data["quote"]["USD"]
            return {
                "symbol": symbol,
                "price": quote["price"],
                "change_24h_pct": quote["percent_change_24h"],
                "volume_24h": quote["volume_24h"],
                "market_cap": quote["market_cap"],
                "source": "coinmarketcap",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {"symbol": symbol, "error": str(e), "source": "coinmarketcap"}

    def _fetch_finnhub_crypto(self, symbol: str) -> dict:
        """Fetch crypto from Finnhub."""
        url = "https://finnhub.io/api/v1/quote"
        params = {"symbol": f"BINANCE:{symbol}USDT", "token": self.finnhub_key}

        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return {
                "symbol": symbol,
                "price": data.get("c", 0),
                "change_pct": data.get("dp", 0),
                "high": data.get("h", 0),
                "low": data.get("l", 0),
                "open": data.get("o", 0),
                "source": "finnhub",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {"symbol": symbol, "error": str(e), "source": "finnhub"}

    def fetch_news(self, category: str = "crypto", limit: int = 20) -> list[dict]:
        """Fetch latest news from MarketAux.

        Args:
            category: "crypto", "forex", "general"
            limit: Number of articles

        Returns:
            List of news articles with title, description, sentiment, source
        """
        if not self.marketaux_key:
            return [{"error": "No MarketAux API key"}]

        url = "https://api.marketaux.com/v1/news/all"
        params = {
            "api_token": self.marketaux_key,
            "filter_entities": "true",
            "limit": limit,
            "language": "en",
        }

        if category == "crypto":
            params["industries"] = "cryptocurrency"
        elif category == "forex":
            params["industries"] = "financial"

        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            articles = resp.json().get("data", [])
            return [
                {
                    "title": a.get("title", ""),
                    "description": a.get("description", ""),
                    "url": a.get("url", ""),
                    "source": a.get("source", ""),
                    "published_at": a.get("published_at", ""),
                    "sentiment": a.get("entities", [{}])[0].get("sentiment_score", 0)
                    if a.get("entities") else 0,
                }
                for a in articles
            ]
        except Exception as e:
            return [{"error": str(e)}]

    def fetch_economic_calendar(self, days_ahead: int = 7) -> list[dict]:
        """Fetch upcoming economic events from Finnhub."""
        if not self.finnhub_key:
            return [{"error": "No Finnhub API key"}]

        from datetime import timedelta

        now = datetime.now(timezone.utc)
        url = "https://finnhub.io/api/v1/calendar/economic"
        params = {
            "from": now.strftime("%Y-%m-%d"),
            "to": (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d"),
            "token": self.finnhub_key,
        }

        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            events = resp.json().get("economicCalendar", [])
            return [
                {
                    "event": e.get("event", ""),
                    "country": e.get("country", ""),
                    "date": e.get("date", ""),
                    "time": e.get("time", ""),
                    "impact": e.get("impact", ""),
                    "forecast": e.get("estimate", ""),
                    "previous": e.get("prev", ""),
                    "actual": e.get("actual", ""),
                }
                for e in events
            ]
        except Exception as e:
            return [{"error": str(e)}]

    def fetch_market_sentiment(self, symbol: str) -> dict:
        """Fetch social sentiment from Finnhub."""
        if not self.finnhub_key:
            return {"error": "No Finnhub API key"}

        url = "https://finnhub.io/api/v1/news-sentiment"
        params = {"symbol": symbol, "token": self.finnhub_key}

        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            sentiment = data.get("sentiment", {})
            return {
                "symbol": symbol,
                "bullish_pct": sentiment.get("bullishPercent", 0),
                "bearish_pct": sentiment.get("bearishPercent", 0),
                "buzz_score": data.get("buzz", {}).get("buzz", 0),
                "articles_in_last_week": data.get("buzz", {}).get("articlesInLastWeek", 0),
                "source": "finnhub",
            }
        except Exception as e:
            return {"symbol": symbol, "error": str(e)}
