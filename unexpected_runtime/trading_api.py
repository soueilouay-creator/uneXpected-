from __future__ import annotations

from decimal import Decimal
from urllib.parse import parse_qs

from trading_engine import BacktestConfig, JournalDisabledError
from trading_engine.models import as_decimal


def _failure(exc):
    if isinstance(exc, JournalDisabledError):
        return 503, {"error": "Paper journal writes are disabled until durable storage is configured."}
    if isinstance(exc, ValueError):
        return 400, {"error": str(exc)}
    if isinstance(exc, RuntimeError):
        return 503, {"error": "Trading operation is unavailable."}
    return 500, {"error": "Trading operation failed.", "error_type": type(exc).__name__}


def dispatch_trading_get(path: str, query: str, service):
    try:
        if path == "/v1/trading/health":
            if query:
                return 400, {"error": "health does not accept query parameters"}
            return 200, service.health()
        if path == "/v1/trading/portfolio":
            params = parse_qs(query, keep_blank_values=True)
            if set(params) != {"account_id"} or len(params["account_id"]) != 1 or not params["account_id"][0]:
                return 400, {"error": "exactly one account_id query parameter is required"}
            return 200, service.portfolio(params["account_id"][0])
        return 404, {"error": "Not found."}
    except Exception as exc:
        return _failure(exc)


def dispatch_trading_post(path: str, body: dict, service):
    if not isinstance(body, dict):
        return 400, {"error": "Body must be a JSON object."}
    try:
        if path == "/v1/trading/scan":
            allowed = {"symbols", "timeframe", "limit"}
            if set(body) - allowed:
                raise ValueError("scan payload contains unsupported fields")
            return 200, service.scan(
                body.get("symbols"), body.get("timeframe", "1Day"), body.get("limit", 100)
            )
        if path == "/v1/trading/risk-check":
            return 200, service.risk_check(body)
        if path == "/v1/trading/backtest":
            allowed = {"symbol", "timeframe", "limit", "config"}
            if set(body) - allowed or "symbol" not in body or not isinstance(body.get("config"), dict):
                raise ValueError("backtest requires symbol and a config object with initial_cash_usd")
            raw = body["config"]
            config_fields = {
                "initial_cash_usd", "lookback", "risk_fraction", "stop_pct",
                "target_pct", "commission_bps", "slippage_bps",
            }
            if set(raw) - config_fields or "initial_cash_usd" not in raw:
                raise ValueError("backtest config contains unsupported fields or lacks initial_cash_usd")
            config = BacktestConfig(
                initial_cash=as_decimal(raw["initial_cash_usd"], "initial_cash_usd"),
                lookback=raw.get("lookback", 20),
                risk_fraction=as_decimal(raw.get("risk_fraction", "0.01"), "risk_fraction"),
                stop_pct=as_decimal(raw.get("stop_pct", "0.03"), "stop_pct"),
                target_pct=as_decimal(raw.get("target_pct", "0.06"), "target_pct"),
                commission_bps=as_decimal(raw.get("commission_bps", "1"), "commission_bps"),
                slippage_bps=as_decimal(raw.get("slippage_bps", "5"), "slippage_bps"),
            )
            return 200, service.backtest(
                body["symbol"], body.get("timeframe", "1Day"), body.get("limit", 100), config
            )
        if path == "/v1/trading/accounts":
            if set(body) != {"account_id", "initial_cash_usd"}:
                raise ValueError("account payload requires only account_id and initial_cash_usd")
            return 201, service.open_account(body["account_id"], body["initial_cash_usd"])
        if path == "/v1/trading/paper-orders":
            allowed = {"account_id", "symbol", "side", "quantity", "price_usd", "fees_usd", "idempotency_key"}
            if set(body) - allowed or allowed - set(body):
                raise ValueError("paper-order payload has missing or unsupported fields")
            return 201, service.paper_order(
                body["account_id"], body["symbol"], body["side"], body["quantity"],
                body["price_usd"], body["fees_usd"], body["idempotency_key"],
            )
        return 404, {"error": "Not found."}
    except Exception as exc:
        return _failure(exc)
