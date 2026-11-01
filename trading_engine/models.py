from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation


def as_decimal(value, name: str = "value") -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{name} must be a valid decimal") from None
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def utc_timestamp(value: str, name: str = "timestamp") -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.isoformat()


def validate_symbol(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("symbol must be text")
    symbol = value.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol):
        raise ValueError("symbol must be a valid US-listed ticker")
    return symbol


@dataclass(frozen=True)
class Bar:
    symbol: str
    timestamp: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self):
        object.__setattr__(self, "symbol", validate_symbol(self.symbol))
        object.__setattr__(self, "timestamp", utc_timestamp(self.timestamp))
        for field in ("open", "high", "low", "close", "volume"):
            value = as_decimal(getattr(self, field), field)
            if field == "volume":
                if value < 0:
                    raise ValueError("volume cannot be negative")
            elif value <= 0:
                raise ValueError(f"{field} must be positive")
            object.__setattr__(self, field, value)
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be at least open, close and low")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be at most open, close and high")


@dataclass(frozen=True)
class DataBatch:
    symbol: str
    source: str
    feed_type: str
    timeframe: str
    bars: tuple[Bar, ...]
    retrieved_at: str
    status: str = "complete"
    gaps: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "symbol", validate_symbol(self.symbol))
        object.__setattr__(self, "retrieved_at", utc_timestamp(self.retrieved_at, "retrieved_at"))
        if self.status not in {"complete", "partial", "empty"}:
            raise ValueError("status must be complete, partial or empty")
        if not self.source or not self.feed_type or not self.timeframe:
            raise ValueError("source, feed_type and timeframe are required")
        if not isinstance(self.bars, tuple):
            object.__setattr__(self, "bars", tuple(self.bars))
        if any(not isinstance(bar, Bar) or bar.symbol != self.symbol for bar in self.bars):
            raise ValueError("every bar must belong to the batch symbol")
        if len(self.bars) > 1 and any(
            self.bars[index].timestamp >= self.bars[index + 1].timestamp
            for index in range(len(self.bars) - 1)
        ):
            raise ValueError("bars must be strictly ordered by timestamp")
        if not self.bars and self.status != "empty":
            object.__setattr__(self, "status", "empty")
        if self.gaps and self.status == "complete":
            object.__setattr__(self, "status", "partial")

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "source": self.source,
            "feed_type": self.feed_type,
            "timeframe": self.timeframe,
            "retrieved_at": self.retrieved_at,
            "status": self.status,
            "gaps": list(self.gaps),
            "bars_count": len(self.bars),
            "bars": [
                {
                    "timestamp": bar.timestamp,
                    "open": str(bar.open), "high": str(bar.high),
                    "low": str(bar.low), "close": str(bar.close),
                    "volume": str(bar.volume),
                } for bar in self.bars
            ],
        }
