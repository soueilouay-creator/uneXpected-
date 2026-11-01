from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

from .backtest import BacktestConfig, run_backtest
from .data import AlpacaMarketDataProvider, FixtureProvider
from .models import as_decimal, validate_symbol
from .portfolio import PaperPortfolio
from .risk import RiskRequest, evaluate_risk
from .scanner import scan_batch


class JournalDisabledError(RuntimeError):
    pass


class TradingService:
    """Typed service boundary used by the runtime API and CLI."""

    def __init__(self, provider=None, database_path=":memory:", journal_writes=False):
        self.provider = provider or FixtureProvider()
        self.portfolio_store = PaperPortfolio(database_path)
        self.journal_writes = bool(journal_writes)
        self.database_path = str(database_path)
        self.storage_mode = "durable" if self.journal_writes else "read-only"

    @classmethod
    def from_env(cls):
        provider_name = os.getenv("UNEXPECTED_TRADING_DATA_PROVIDER", "fixture").strip().lower()
        if provider_name == "fixture":
            provider = FixtureProvider()
        elif provider_name == "alpaca":
            provider = AlpacaMarketDataProvider.from_env()
        else:
            raise ValueError("UNEXPECTED_TRADING_DATA_PROVIDER must be fixture or alpaca")
        database_path = os.getenv("UNEXPECTED_TRADING_DB_PATH", "./state/trading.sqlite3")
        storage_mode = os.getenv("UNEXPECTED_TRADING_STORAGE_MODE", "ephemeral").strip().lower()
        writes_requested = os.getenv("UNEXPECTED_TRADING_ALLOW_JOURNAL_WRITES", "false").strip().lower() == "true"
        # This is an explicit operator attestation after a persistent volume has been configured.
        journal_writes = writes_requested and storage_mode == "durable"
        service = cls(provider=provider, database_path=database_path, journal_writes=journal_writes)
        service.storage_mode = storage_mode
        return service

    def health(self):
        return {
            "ok": True,
            "mode": "paper_only",
            "provider": self.provider.name,
            "provider_configured": bool(self.provider.configured),
            "fixture_data_is_synthetic": self.provider.name == "fixture",
            "storage_mode": self.storage_mode,
            "journal_writes_enabled": self.journal_writes,
            "database_integrity": self.portfolio_store.integrity_check(),
            "broker_connection": False,
            "live_order_execution": False,
            "background_polling": False,
        }

    def scan(self, symbols, timeframe="1Day", limit=100):
        if not isinstance(symbols, list) or not symbols or len(symbols) > 50:
            raise ValueError("symbols must be a list containing 1 to 50 tickers")
        clean = [validate_symbol(symbol) for symbol in symbols]
        if len(set(clean)) != len(clean):
            raise ValueError("symbols must be unique")
        results, failures = [], []
        for symbol in clean:
            try:
                batch = self.provider.fetch_bars(symbol, timeframe=timeframe, limit=limit)
                results.append(scan_batch(batch).to_dict())
            except (RuntimeError, ValueError):
                failures.append({"symbol": symbol, "error": "data_unavailable_or_invalid"})
        status = "partial" if failures and results else ("unavailable" if failures else "complete")
        return {"status": status, "results": results, "failures": failures, "scanned": len(clean)}

    def risk_check(self, payload):
        allowed = {
            "symbol", "equity_usd", "cash_available_usd", "entry_price", "stop_price",
            "target_price", "max_loss_usd", "max_position_pct", "existing_exposure_usd",
            "current_daily_loss_usd", "max_daily_loss_usd",
        }
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise ValueError("risk-check payload contains unsupported fields")
        required = {"symbol", "equity_usd", "cash_available_usd", "entry_price",
                    "stop_price", "target_price", "max_loss_usd", "max_position_pct"}
        if required - set(payload):
            raise ValueError("risk-check payload is missing required fields")
        values = dict(payload)
        for key in required - {"symbol"}:
            values[key] = as_decimal(values[key], key)
        for key in ("existing_exposure_usd", "current_daily_loss_usd", "max_daily_loss_usd"):
            if key in values and values[key] is not None:
                values[key] = as_decimal(values[key], key)
        return evaluate_risk(RiskRequest(**values)).to_dict()

    def backtest(self, symbol, timeframe="1Day", limit=100, config=None):
        symbol = validate_symbol(symbol)
        batch = self.provider.fetch_bars(symbol, timeframe=timeframe, limit=limit)
        if config is None:
            raise ValueError("an explicit backtest configuration and initial cash are required")
        result = run_backtest(batch, config)
        return result.to_dict()

    def _require_writable(self):
        if not self.journal_writes:
            raise JournalDisabledError(
                "paper journal writes are disabled until durable storage is explicitly configured"
            )

    def open_account(self, account_id, initial_cash_usd):
        self._require_writable()
        return self.portfolio_store.open_account(account_id, initial_cash_usd)

    def paper_order(self, account_id, symbol, side, quantity, price_usd, fees_usd, idempotency_key):
        self._require_writable()
        if side == "buy":
            result = self.portfolio_store.buy(account_id, symbol, quantity, price_usd, fees_usd, idempotency_key)
        elif side == "sell":
            result = self.portfolio_store.sell(account_id, symbol, quantity, price_usd, fees_usd, idempotency_key)
        else:
            raise ValueError("side must be buy or sell")
        result["portfolio"] = self.portfolio_store.snapshot(account_id)
        return result

    def portfolio(self, account_id):
        return self.portfolio_store.snapshot(account_id)

    def journal(self, account_id):
        return self.portfolio_store.journal(account_id)

    def close(self):
        self.portfolio_store.close()
