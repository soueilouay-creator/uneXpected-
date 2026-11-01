from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import DataBatch


@dataclass(frozen=True)
class ScanResult:
    symbol: str
    source: str
    feed_type: str
    timeframe: str
    retrieved_at: str
    status: str
    bars_scanned: int
    signals: tuple[dict, ...]
    notes: tuple[str, ...] = ()

    def to_dict(self):
        return {
            "symbol": self.symbol, "source": self.source, "feed_type": self.feed_type,
            "timeframe": self.timeframe, "retrieved_at": self.retrieved_at,
            "status": self.status, "bars_scanned": self.bars_scanned,
            "signals": list(self.signals), "notes": list(self.notes),
        }


def _mean(values):
    return sum(values, Decimal("0")) / Decimal(len(values))


def _rsi(values):
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    gains = [max(change, Decimal("0")) for change in changes]
    losses = [max(-change, Decimal("0")) for change in changes]
    average_gain = _mean(gains)
    average_loss = _mean(losses)
    if average_loss == 0:
        return Decimal("100")
    relative_strength = average_gain / average_loss
    return Decimal("100") - (Decimal("100") / (Decimal("1") + relative_strength))


def scan_batch(batch: DataBatch) -> ScanResult:
    if not isinstance(batch, DataBatch):
        raise TypeError("batch must be a DataBatch")
    bars = list(batch.bars)
    signals = []
    notes = list(batch.gaps)
    if len(bars) < 21:
        return ScanResult(
            batch.symbol, batch.source, batch.feed_type, batch.timeframe,
            batch.retrieved_at, "insufficient_data", len(bars), (), tuple(notes + ["at least 21 completed bars are required"]),
        )
    previous = bars[-21:-1]
    latest = bars[-1]
    prior_high = max(bar.high for bar in previous)
    if latest.close > prior_high:
        signals.append({
            "strategy": "20_bar_breakout",
            "timestamp": latest.timestamp,
            "close": str(latest.close),
            "reference_high": str(prior_high),
            "rule": "latest completed close exceeded the prior 20 completed bars' high",
        })
    previous_sma = _mean([bar.close for bar in previous])
    current_sma = _mean([bar.close for bar in bars[-20:]])
    if bars[-2].close <= previous_sma and latest.close > current_sma:
        signals.append({
            "strategy": "20_bar_sma_reclaim",
            "timestamp": latest.timestamp,
            "close": str(latest.close),
            "sma20": str(current_sma),
            "rule": "completed close crossed above the 20-bar simple moving average",
        })
    if len(bars) >= 16:
        closes = [bar.close for bar in bars]
        prior_rsi = _rsi(closes[-16:-1])
        current_rsi = _rsi(closes[-15:])
        if prior_rsi < Decimal("30") and current_rsi >= Decimal("30"):
            signals.append({
                "strategy": "rsi14_oversold_bounce",
                "timestamp": latest.timestamp,
                "rsi14": str(current_rsi),
                "rule": "RSI crossed up through 30 on completed bars",
            })
    if batch.timeframe == "15Min":
        session = latest.timestamp[:10]
        same_day = [bar for bar in bars if bar.timestamp[:10] == session]
        if len(same_day) >= 3 and latest.close > max(bar.high for bar in same_day[:2]):
            signals.append({
                "strategy": "opening_range_breakout_15m",
                "timestamp": latest.timestamp,
                "close": str(latest.close),
                "opening_range_high": str(max(bar.high for bar in same_day[:2])),
                "rule": "completed bar closed above the first two 15-minute bars of the UTC date",
            })
    status = "partial" if batch.status == "partial" else "complete"
    return ScanResult(
        batch.symbol, batch.source, batch.feed_type, batch.timeframe,
        batch.retrieved_at, status, len(bars), tuple(signals), tuple(notes),
    )
