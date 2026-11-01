from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from trading_engine import FixtureProvider, PaperPortfolio, RiskRequest, evaluate_risk, run_backtest, BacktestConfig
from trading_engine.scanner import scan_batch


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
            with self.assertRaises(ValueError):
                store.sell("demo", "DEMO", 1, Decimal("100"), Decimal("0"), "sell-1")
            store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
