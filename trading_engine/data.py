from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Protocol

from .models import Bar, DataBatch, validate_symbol


class MarketDataProvider(Protocol):
    name: str
    configured: bool

    def fetch_bars(self, symbol: str, timeframe: str = "1Day", limit: int = 100) -> DataBatch: ...


class FixtureProvider:
    """Deterministic synthetic data. Never label these fixtures as market prices."""
    name = "fixture"
    configured = True

    def fetch_bars(self, symbol: str, timeframe: str = "1Day", limit: int = 100) -> DataBatch:
        symbol = validate_symbol(symbol)
        if timeframe not in {"1Day", "15Min"}:
            raise ValueError("timeframe must be 1Day or 15Min")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be an integer from 1 to 1000")
        count = min(limit, 30)
        start = datetime(2025, 1, 2, 14, 30, tzinfo=timezone.utc)
        bars = []
        offset = sum(ord(char) for char in symbol) % 7
        for index in range(count):
            close = 100 + offset + (index * 1.5)
            bars.append(Bar(
                symbol=symbol,
                timestamp=(start + timedelta(days=index)).isoformat(),
                open=str(close - 0.10),
                high=str(close + 0.25),
                low=str(close - 0.45),
                close=str(close),
                volume=str(100000 + index * 1000),
            ))
        return DataBatch(
            symbol=symbol, source=self.name, feed_type="synthetic",
            timeframe=timeframe, bars=tuple(bars),
            retrieved_at=datetime.now(timezone.utc).isoformat(),
        )


class _RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "market-data redirect rejected", headers, fp)


class AlpacaMarketDataProvider:
    """Read-only Alpaca market-data client. Fixed host, GET-only, no trading endpoints."""
    name = "alpaca-market-data"
    BASE_URL = "https://data.alpaca.markets"
    MAX_RESPONSE_BYTES = 2 * 1024 * 1024

    def __init__(self, key_id: str | None = None, secret_key: str | None = None, timeout: float = 10.0):
        self._key_id = (key_id or os.getenv("APCA_API_KEY_ID", "")).strip()
        self._secret_key = (secret_key or os.getenv("APCA_API_SECRET_KEY", "")).strip()
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 20:
            raise ValueError("timeout must be between 1 and 20 seconds")
        self.timeout = float(timeout)
        self.configured = bool(self._key_id and self._secret_key)
        self._opener = urllib.request.build_opener(_RejectRedirect())

    @classmethod
    def from_env(cls):
        return cls()

    def fetch_bars(self, symbol: str, timeframe: str = "1Day", limit: int = 100) -> DataBatch:
        symbol = validate_symbol(symbol)
        if not self.configured:
            raise RuntimeError("Alpaca market-data credentials are not configured")
        if timeframe not in {"1Day", "15Min"}:
            raise ValueError("timeframe must be 1Day or 15Min")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be an integer from 1 to 1000")
        params = urllib.parse.urlencode({"timeframe": timeframe, "limit": limit, "feed": "iex", "adjustment": "raw"})
        url = f"{self.BASE_URL}/v2/stocks/{urllib.parse.quote(symbol, safe='')}/bars?{params}"
        request = urllib.request.Request(url, method="GET", headers={
            "APCA-API-KEY-ID": self._key_id,
            "APCA-API-SECRET-KEY": self._secret_key,
            "Accept": "application/json",
            "User-Agent": "uneXpected-trading-engine/0.2.0",
        })
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(self.MAX_RESPONSE_BYTES + 1)
                if len(raw) > self.MAX_RESPONSE_BYTES:
                    raise RuntimeError("market-data response exceeded the size limit")
                payload = json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Alpaca market-data request failed (HTTP {exc.code})") from None
        except (urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeError("Alpaca market-data request failed") from None
        records = payload.get("bars", [])
        if not isinstance(records, list):
            raise RuntimeError("Alpaca returned an invalid bars payload")
        bars = []
        for row in records:
            try:
                bars.append(Bar(
                    symbol=symbol, timestamp=row["t"], open=row["o"], high=row["h"],
                    low=row["l"], close=row["c"], volume=row.get("v", 0),
                ))
            except (KeyError, TypeError, ValueError):
                raise RuntimeError("Alpaca returned a malformed bar") from None
        bars.sort(key=lambda item: item.timestamp)
        has_more = bool(payload.get("next_page_token"))
        gaps = ("provider returned another page; requested window is partial",) if has_more else ()
        return DataBatch(
            symbol=symbol, source=self.name, feed_type="IEX",
            timeframe=timeframe, bars=tuple(bars),
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            status="partial" if gaps else ("complete" if bars else "empty"),
            gaps=gaps,
        )
