from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR

from .models import DataBatch, as_decimal


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: Decimal
    lookback: int = 20
    risk_fraction: Decimal = Decimal("0.01")
    stop_pct: Decimal = Decimal("0.03")
    target_pct: Decimal = Decimal("0.06")
    commission_bps: Decimal = Decimal("1")
    slippage_bps: Decimal = Decimal("5")

    def __post_init__(self):
        for field in ("initial_cash", "risk_fraction", "stop_pct", "target_pct",
                      "commission_bps", "slippage_bps"):
            value = as_decimal(getattr(self, field), field)
            if value <= 0 and field in {"initial_cash", "risk_fraction", "stop_pct", "target_pct"}:
                raise ValueError(f"{field} must be positive")
            if value < 0:
                raise ValueError(f"{field} cannot be negative")
            object.__setattr__(self, field, value)
        if isinstance(self.lookback, bool) or not isinstance(self.lookback, int) or not 2 <= self.lookback <= 250:
            raise ValueError("lookback must be an integer between 2 and 250")
        if self.risk_fraction > 1 or self.stop_pct >= 1 or self.target_pct >= 5:
            raise ValueError("risk_fraction, stop_pct or target_pct is outside the supported range")


@dataclass(frozen=True)
class BacktestResult:
    symbol: str
    timeframe: str
    dataset_sha256: str
    config_sha256: str
    metrics: dict
    trades: tuple[dict, ...]
    limitations: tuple[str, ...]

    def to_dict(self):
        return {
            "symbol": self.symbol, "timeframe": self.timeframe,
            "dataset_sha256": self.dataset_sha256, "config_sha256": self.config_sha256,
            "metrics": {key: str(value) if isinstance(value, Decimal) else value for key, value in self.metrics.items()},
            "trades": [
                {key: str(value) if isinstance(value, Decimal) else value for key, value in trade.items()}
                for trade in self.trades
            ],
            "limitations": list(self.limitations),
        }


def _canonical_hash(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def run_backtest(batch: DataBatch, config: BacktestConfig) -> BacktestResult:
    if not isinstance(batch, DataBatch) or not isinstance(config, BacktestConfig):
        raise TypeError("run_backtest requires a DataBatch and BacktestConfig")
    if batch.status != "complete":
        raise ValueError("backtest refuses partial or empty market data")
    bars = list(batch.bars)
    if len(bars) < config.lookback + 2:
        raise ValueError("insufficient completed bars for the requested lookback")
    bar_payload = [
        [bar.timestamp, str(bar.open), str(bar.high), str(bar.low), str(bar.close), str(bar.volume)]
        for bar in bars
    ]
    dataset_hash = _canonical_hash({
        "symbol": batch.symbol, "source": batch.source,
        "feed_type": batch.feed_type, "timeframe": batch.timeframe, "bars": bar_payload,
    })
    config_hash = _canonical_hash({
        key: str(value) if isinstance(value, Decimal) else value
        for key, value in config.__dict__.items()
    })
    cash = config.initial_cash
    commission_rate = config.commission_bps / Decimal("10000")
    slippage_rate = config.slippage_bps / Decimal("10000")
    position = None
    trades = []
    equity_peak = config.initial_cash
    max_drawdown = Decimal("0")

    def close_position(raw_exit: Decimal, timestamp: str, reason: str):
        nonlocal cash, position
        exit_price = raw_exit * (Decimal("1") - slippage_rate)
        exit_fee = position["quantity"] * exit_price * commission_rate
        cash += position["quantity"] * exit_price - exit_fee
        pnl = (
            position["quantity"] * (exit_price - position["entry_price"])
            - position["entry_fee"] - exit_fee
        )
        trades.append({
            "entry_timestamp": position["entry_timestamp"],
            "exit_timestamp": timestamp,
            "quantity": position["quantity"],
            "entry_price": position["entry_price"],
            "exit_price": exit_price,
            "pnl_usd": pnl,
            "exit_reason": reason,
        })
        position = None

    for index in range(config.lookback, len(bars)):
        bar = bars[index]
        if position is not None:
            if bar.low <= position["stop_price"]:
                close_position(position["stop_price"], bar.timestamp, "stop_first")
            elif bar.high >= position["target_price"]:
                close_position(position["target_price"], bar.timestamp, "target")
            elif index == len(bars) - 1:
                close_position(bar.close, bar.timestamp, "end_of_data")
        if position is None and index < len(bars) - 1:
            prior_high = max(item.high for item in bars[index - config.lookback:index])
            if bar.close > prior_high:
                next_bar = bars[index + 1]
                entry_price = next_bar.open * (Decimal("1") + slippage_rate)
                stop_price = entry_price * (Decimal("1") - config.stop_pct)
                target_price = entry_price * (Decimal("1") + config.target_pct)
                risk_per_share = entry_price - stop_price
                risk_budget = cash * config.risk_fraction
                risk_qty = int((risk_budget / risk_per_share).to_integral_value(rounding=ROUND_FLOOR))
                cash_qty = int((cash / (entry_price * (Decimal("1") + commission_rate))).to_integral_value(rounding=ROUND_FLOOR))
                quantity = min(risk_qty, cash_qty)
                if quantity > 0:
                    entry_fee = quantity * entry_price * commission_rate
                    cash -= quantity * entry_price + entry_fee
                    position = {
                        "quantity": quantity, "entry_price": entry_price,
                        "entry_fee": entry_fee, "entry_timestamp": next_bar.timestamp,
                        "stop_price": stop_price, "target_price": target_price,
                    }
        marked_equity = cash + (
            position["quantity"] * (position["entry_price"] if index < len(bars) - 1 and position["entry_timestamp"] == bars[index + 1].timestamp else bar.close)
            if position is not None else Decimal("0")
        )
        equity_peak = max(equity_peak, marked_equity)
        if equity_peak > 0:
            max_drawdown = max(max_drawdown, (equity_peak - marked_equity) / equity_peak * Decimal("100"))

    if position is not None:
        close_position(bars[-1].close, bars[-1].timestamp, "end_of_data")
    final_equity = cash
    pnl_values = [trade["pnl_usd"] for trade in trades]
    gross_profit = sum((value for value in pnl_values if value > 0), Decimal("0"))
    gross_loss = abs(sum((value for value in pnl_values if value < 0), Decimal("0")))
    wins = sum(1 for value in pnl_values if value > 0)
    profit_factor = gross_profit / gross_loss if gross_loss else (gross_profit if gross_profit else Decimal("0"))
    metrics = {
        "initial_cash_usd": config.initial_cash,
        "final_equity_usd": final_equity,
        "net_return_pct": (final_equity - config.initial_cash) / config.initial_cash * Decimal("100"),
        "max_drawdown_pct": max_drawdown,
        "win_rate_pct": Decimal(wins) / Decimal(len(trades)) * Decimal("100") if trades else Decimal("0"),
        "profit_factor": profit_factor,
        "trades": len(trades),
        "wins": wins,
        "losses": len(trades) - wins,
        "data_bars": len(bars),
    }
    return BacktestResult(
        symbol=batch.symbol, timeframe=batch.timeframe,
        dataset_sha256=dataset_hash, config_sha256=config_hash,
        metrics=metrics, trades=tuple(trades),
        limitations=(
            "Long-only breakout simulation; one open position at a time.",
            "Signals are evaluated after bar close and entries use the next bar open.",
            "If stop and target both touch within one bar, the stop is applied first.",
            "Commission and slippage are modeled inputs; gaps, market impact and taxes are not modeled.",
            "Synthetic or vendor-provided bar history may be incomplete and can contain survivorship bias.",
            "Backtest results are historical simulation, not a forecast or investment recommendation.",
        ),
    )
