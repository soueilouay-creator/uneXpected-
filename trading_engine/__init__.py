"""Controlled, paper-only trading research engine for uneXpected."""
from .backtest import BacktestConfig, BacktestResult, run_backtest
from .data import AlpacaMarketDataProvider, FixtureProvider, MarketDataProvider
from .models import Bar, DataBatch
from .portfolio import PaperPortfolio
from .risk import RiskRequest, RiskResult, evaluate_risk
from .scanner import ScanResult, scan_batch
from .service import JournalDisabledError, TradingService

__all__ = [
    "AlpacaMarketDataProvider", "BacktestConfig", "BacktestResult", "Bar",
    "DataBatch", "FixtureProvider", "JournalDisabledError", "MarketDataProvider",
    "PaperPortfolio", "RiskRequest", "RiskResult", "ScanResult", "TradingService",
    "evaluate_risk", "run_backtest", "scan_batch",
]
