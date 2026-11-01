from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from trading_engine import (
    AlpacaMarketDataProvider, BacktestConfig, FixtureProvider, PaperPortfolio,
    RiskRequest, TradingService, evaluate_risk, run_backtest,
)
from trading_engine.scanner import scan_batch
from unexpected_runtime.http_api import create_server


class RiskEngineTests(unittest.TestCase):
    def test_position_size_obeys_risk_cash_and_position_caps(self):
        result = evaluate_risk(RiskRequest(
            symbol="DEMO", equity_usd=Decimal("10000"),
            cash_available_usd=Decimal("10000"), entry_price=Decimal("100"),
            stop_price=Decimal("95"), target_price=Decimal("110"),
            max_loss_usd=Decimal("100"), max_position_pct=Decimal("20"),
        ))
        self.assertTrue(result.approved)
        self.assertEqual(result.quantity, 20)
        self.assertEqual(result.planned_loss_usd, Decimal("100"))
        self.assertEqual(result.reward_risk, Decimal("2"))

    def test_long_risk_check_rejects_stop_above_entry(self):
        with self.assertRaises(ValueError):
            evaluate_risk(RiskRequest(
                symbol="DEMO", equity_usd=Decimal("10000"),
                cash_available_usd=Decimal("10000"), entry_price=Decimal("100"),
                stop_price=Decimal("101"), target_price=Decimal("110"),
                max_loss_usd=Decimal("100"), max_position_pct=Decimal("20"),
            ))

    def test_daily_loss_cap_blocks_new_risk(self):
        result = evaluate_risk(RiskRequest(
            symbol="DEMO", equity_usd=Decimal("10000"),
            cash_available_usd=Decimal("10000"), entry_price=Decimal("100"),
            stop_price=Decimal("95"), target_price=Decimal("110"),
            max_loss_usd=Decimal("100"), max_position_pct=Decimal("20"),
            current_daily_loss_usd=Decimal("500"), max_daily_loss_usd=Decimal("500"),
        ))
        self.assertFalse(result.approved)
        self.assertEqual(result.quantity, 0)
        self.assertEqual(result.reason, "daily loss limit reached")


class MarketDataAndScanTests(unittest.TestCase):
    def test_fixture_source_is_explicitly_synthetic_and_scanner_returns_provenanced_signal(self):
        batch = FixtureProvider().fetch_bars("DEMO", timeframe="1Day", limit=100)
        self.assertEqual(batch.source, "fixture")
        self.assertEqual(batch.feed_type, "synthetic")
        self.assertEqual(len(batch.bars), 30)
        result = scan_batch(batch)
        self.assertEqual(result.symbol, "DEMO")
        self.assertGreaterEqual(len(result.signals), 1)
        self.assertEqual(result.source, "fixture")
        self.assertEqual(result.feed_type, "synthetic")
        self.assertIsNotNone(result.retrieved_at)

    def test_unconfigured_alpaca_adapter_fails_closed_without_network_access(self):
        provider = AlpacaMarketDataProvider(key_id="", secret_key="")
        with self.assertRaisesRegex(RuntimeError, "credentials are not configured"):
            provider.fetch_bars("AAPL")

    def test_backtest_requires_explicit_initial_cash(self):
        service = TradingService(FixtureProvider())
        try:
            with self.assertRaisesRegex(ValueError, "explicit backtest configuration"):
                service.backtest("DEMO")
        finally:
            service.close()

    def test_backtest_refuses_partial_market_data(self):
        from dataclasses import replace
        batch = FixtureProvider().fetch_bars("DEMO")
        partial = replace(batch, status="partial", gaps=("fixture gap",))
        with self.assertRaisesRegex(ValueError, "partial or empty"):
            run_backtest(partial, BacktestConfig(initial_cash=Decimal("10000")))


class BacktestTests(unittest.TestCase):
    def test_backtest_is_reproducible_and_records_data_and_config_fingerprints(self):
        batch = FixtureProvider().fetch_bars("DEMO", timeframe="1Day", limit=100)
        config = BacktestConfig(initial_cash=Decimal("10000"))
        first = run_backtest(batch, config)
        second = run_backtest(batch, config)
        self.assertEqual(first.dataset_sha256, second.dataset_sha256)
        self.assertEqual(first.config_sha256, second.config_sha256)
        self.assertEqual(first.metrics, second.metrics)
        self.assertGreaterEqual(first.metrics["trades"], 0)
        self.assertGreaterEqual(first.metrics["max_drawdown_pct"], Decimal("0"))
        self.assertEqual(len(first.dataset_sha256), 64)


class PaperPortfolioTests(unittest.TestCase):
    def test_paper_ledger_persists_and_idempotency_prevents_duplicate_buy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.sqlite3"
            store = PaperPortfolio(path)
            store.open_account("demo", Decimal("10000"))
            first = store.buy("demo", "DEMO", 10, Decimal("100"), Decimal("1"), "order-1")
            duplicate = store.buy("demo", "DEMO", 10, Decimal("100"), Decimal("1"), "order-1")
            self.assertEqual(first["order_id"], duplicate["order_id"])
            self.assertTrue(duplicate["duplicate"])
            before = store.snapshot("demo")
            store.close()
            reopened = PaperPortfolio(path)
            after = reopened.snapshot("demo")
            self.assertEqual(before, after)
            self.assertEqual(after["cash_usd"], Decimal("8999"))
            self.assertEqual(after["positions"]["DEMO"]["quantity"], 10)
            reopened.close()

    def test_paper_sell_cannot_create_a_short_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PaperPortfolio(Path(tmp) / "paper.sqlite3")
            store.open_account("demo", Decimal("1000"))
            with self.assertRaisesRegex(ValueError, "short position"):
                store.sell("demo", "DEMO", 1, Decimal("100"), Decimal("0"), "sell-1")
            store.close()

    def test_journal_labels_simulated_fills_and_calculates_realized_pnl(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PaperPortfolio(Path(tmp) / "journal.sqlite3")
            store.open_account("demo", "2000")
            store.buy("demo", "DEMO", 10, "100", "1", "journal-buy")
            store.sell("demo", "DEMO", 5, "110", "1", "journal-sell")
            snapshot = store.snapshot("demo")
            self.assertEqual(snapshot["realized_pnl_usd"], Decimal("48.5"))
            self.assertEqual(snapshot["positions"]["DEMO"]["quantity"], 5)
            entries = store.journal("demo")
            self.assertEqual(len(entries), 2)
            self.assertTrue(all(entry["record_type"] == "SIMULATED_FILL" for entry in entries))
            self.assertEqual(entries[1]["side"], "sell")
            store.close()

    def test_backup_is_integrity_checked_and_restorable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.sqlite3"
            backup = Path(tmp) / "backup" / "paper-copy.sqlite3"
            store = PaperPortfolio(path)
            store.open_account("demo", "1000")
            store.buy("demo", "DEMO", 2, "100", "0", "backup-order")
            result = store.backup(backup)
            self.assertEqual(result["integrity"], "ok")
            store.close()
            restored = PaperPortfolio(backup)
            self.assertEqual(restored.integrity_check(), "ok")
            self.assertEqual(restored.snapshot("demo")["positions"]["DEMO"]["quantity"], 2)
            restored.close()


class RuntimeTradingApiTests(unittest.TestCase):
    def _request(self, base, path, token, payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Authorization": "Bearer " + token}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(base + path, data=data, headers=headers)
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_runtime_exposes_authenticated_scans_and_paper_only_journal(self):
        token = "t" * 40
        with tempfile.TemporaryDirectory() as tmp:
            service = TradingService(FixtureProvider(), Path(tmp) / "paper.sqlite3", journal_writes=True)
            self.assertTrue(service.health()["ok"])
            from unexpected_runtime.trading_api import dispatch_trading_get
            direct_code, direct_payload = dispatch_trading_get("/v1/trading/health", "", service)
            self.assertEqual(direct_code, 200, direct_payload)
            server = create_server(coordinator=object(), trading_service=service, api_token=token)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                status, _ = self._request(base, "/v1/trading/health", "")
                self.assertEqual(status, 401)
                status, health = self._request(base, "/v1/trading/health", token)
                self.assertEqual(status, 200, health)
                self.assertTrue(health["broker_connection"] is False)
                status, scan = self._request(base, "/v1/trading/scan", token, {"symbols": ["DEMO"]})
                self.assertEqual(status, 200)
                self.assertEqual(scan["results"][0]["feed_type"], "synthetic")
                status, account = self._request(base, "/v1/trading/accounts", token, {
                    "account_id": "demo", "initial_cash_usd": "1000",
                })
                self.assertEqual(status, 201)
                status, order = self._request(base, "/v1/trading/paper-orders", token, {
                    "account_id": "demo", "symbol": "DEMO", "side": "buy",
                    "quantity": 1, "price_usd": "100", "fees_usd": "1",
                    "idempotency_key": "api-order-1",
                })
                self.assertEqual(status, 201)
                self.assertFalse(order["duplicate"])
                status, _ = self._request(base, "/v1/trading/paper-orders", token, {
                    "account_id": "demo", "symbol": "DEMO", "side": "buy",
                    "quantity": 1, "price_usd": "100", "fees_usd": "1",
                    "idempotency_key": "api-order-live", "mode": "live",
                })
                self.assertEqual(status, 400)
                status, journal = self._request(base, "/v1/trading/journal?account_id=demo", token)
                self.assertEqual(status, 200)
                self.assertEqual(len(journal), 1)
                self.assertEqual(journal[0]["record_type"], "SIMULATED_FILL")
                status, portfolio = self._request(base, "/v1/trading/portfolio?account_id=demo", token)
                self.assertEqual(status, 200)
                self.assertEqual(portfolio["cash_usd"], "899")
                self.assertEqual(portfolio["realized_pnl_usd"], "0")
            finally:
                server.shutdown()
                server.server_close()
                service.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
