from __future__ import annotations

import re
import threading
import uuid
from decimal import Decimal
from datetime import datetime, timezone

from .models import as_decimal, validate_symbol


def _serialized(method):
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class PostgresPaperPortfolio:
    """Managed-Postgres append-only paper-fill ledger; never connects to a broker."""

    def __init__(self, database_url: str, schema: str = "unexpected_trading"):
        if not isinstance(database_url, str) or not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("a PostgreSQL connection URL is required")
        if not isinstance(schema, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
            raise ValueError("schema must be a safe PostgreSQL identifier")
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL support requires the psycopg[binary] dependency") from exc
        self._lock = threading.RLock()
        self.schema = schema
        self.backend = "postgresql"
        self.connection = psycopg.connect(
            database_url,
            autocommit=True,
            connect_timeout=10,
            row_factory=dict_row,
            application_name="uneXpected-trading-engine",
        )
        try:
            self.connection.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            self.connection.execute(f'SET search_path TO "{schema}"')
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS paper_accounts (
                    account_id TEXT PRIMARY KEY,
                    initial_cash_usd NUMERIC(24, 8) NOT NULL CHECK(initial_cash_usd > 0),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
                )
            """)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS paper_orders (
                    journal_sequence BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
                    order_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES paper_accounts(account_id),
                    idempotency_key TEXT NOT NULL UNIQUE,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
                    quantity BIGINT NOT NULL CHECK(quantity > 0),
                    price_usd NUMERIC(24, 8) NOT NULL CHECK(price_usd > 0),
                    fees_usd NUMERIC(24, 8) NOT NULL CHECK(fees_usd >= 0),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
                )
            """)
            self.connection.execute("""
                CREATE OR REPLACE FUNCTION prevent_paper_order_mutation()
                RETURNS trigger
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    RAISE EXCEPTION 'paper order ledger is append-only';
                END;
                $$
            """)
            self.connection.execute("DROP TRIGGER IF EXISTS paper_orders_no_update ON paper_orders")
            self.connection.execute("DROP TRIGGER IF EXISTS paper_orders_no_delete ON paper_orders")
            self.connection.execute("""
                CREATE TRIGGER paper_orders_no_update
                BEFORE UPDATE ON paper_orders
                FOR EACH ROW EXECUTE FUNCTION prevent_paper_order_mutation()
            """)
            self.connection.execute("""
                CREATE TRIGGER paper_orders_no_delete
                BEFORE DELETE ON paper_orders
                FOR EACH ROW EXECUTE FUNCTION prevent_paper_order_mutation()
            """)
        except Exception:
            self.connection.close()
            raise

    def _snapshot_locked(self, account_id: str):
        account = self.connection.execute(
            "SELECT initial_cash_usd FROM paper_accounts WHERE account_id=%s",
            (account_id,),
        ).fetchone()
        if not account:
            raise ValueError("paper account does not exist")
        cash = Decimal(account["initial_cash_usd"])
        realized_pnl = Decimal("0")
        positions = {}
        orders = self.connection.execute(
            "SELECT symbol, side, quantity, price_usd, fees_usd "
            "FROM paper_orders WHERE account_id=%s ORDER BY journal_sequence",
            (account_id,),
        ).fetchall()
        for order in orders:
            symbol = order["symbol"]
            side = order["side"]
            quantity = int(order["quantity"])
            price = Decimal(order["price_usd"])
            fees = Decimal(order["fees_usd"])
            position = positions.setdefault(
                symbol, {"quantity": 0, "average_cost": Decimal("0")}
            )
            if side == "buy":
                new_quantity = position["quantity"] + quantity
                total_cost = (
                    position["average_cost"] * position["quantity"]
                    + price * quantity + fees
                )
                position["quantity"] = new_quantity
                position["average_cost"] = total_cost / Decimal(new_quantity)
                cash -= price * quantity + fees
            else:
                if quantity > position["quantity"]:
                    raise RuntimeError("paper ledger contains a sell exceeding its long position")
                realized_pnl += (
                    price * quantity - fees
                    - position["average_cost"] * quantity
                )
                position["quantity"] -= quantity
                cash += price * quantity - fees
                if position["quantity"] == 0:
                    position["average_cost"] = Decimal("0")
        visible_positions = {
            symbol: {
                "quantity": value["quantity"],
                "average_cost_per_share_usd": value["average_cost"],
            }
            for symbol, value in positions.items() if value["quantity"] > 0
        }
        return {
            "account_id": account_id,
            "cash_usd": cash,
            "positions": visible_positions,
            "realized_pnl_usd": realized_pnl,
        }

    @_serialized
    def open_account(self, account_id: str, initial_cash_usd):
        if not isinstance(account_id, str) or not account_id.strip() or len(account_id) > 64:
            raise ValueError("account_id must contain 1 to 64 characters")
        account_id = account_id.strip()
        initial_cash = as_decimal(initial_cash_usd, "initial_cash_usd")
        if initial_cash <= 0:
            raise ValueError("initial_cash_usd must be positive")
        with self.connection.transaction():
            self.connection.execute(
                "INSERT INTO paper_accounts(account_id, initial_cash_usd) VALUES(%s,%s)",
                (account_id, initial_cash),
            )
        return self.snapshot(account_id)

    @_serialized
    def snapshot(self, account_id: str):
        return self._snapshot_locked(account_id)

    @_serialized
    def _apply(self, account_id, symbol, side, quantity, price_usd, fees_usd, idempotency_key):
        symbol = validate_symbol(symbol)
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("quantity must be a positive integer")
        price = as_decimal(price_usd, "price_usd")
        fees = as_decimal(fees_usd, "fees_usd")
        if price <= 0 or fees < 0:
            raise ValueError("price must be positive and fees cannot be negative")
        if not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > 128:
            raise ValueError("idempotency_key must contain 1 to 128 characters")
        with self.connection.transaction():
            account = self.connection.execute(
                "SELECT account_id FROM paper_accounts WHERE account_id=%s FOR UPDATE",
                (account_id,),
            ).fetchone()
            if not account:
                raise ValueError("paper account does not exist")
            existing = self.connection.execute(
                "SELECT order_id, account_id, symbol, side, quantity, price_usd, fees_usd "
                "FROM paper_orders WHERE idempotency_key=%s",
                (idempotency_key,),
            ).fetchone()
            if existing:
                same = (
                    existing["account_id"] == account_id
                    and existing["symbol"] == symbol
                    and existing["side"] == side
                    and int(existing["quantity"]) == quantity
                    and Decimal(existing["price_usd"]) == price
                    and Decimal(existing["fees_usd"]) == fees
                )
                if not same:
                    raise ValueError("idempotency_key was already used for a different paper order")
                return {
                    "order_id": existing["order_id"], "duplicate": True,
                    "record_type": "SIMULATED_FILL", "side": side,
                    "symbol": symbol, "quantity": quantity,
                }
            snapshot = self._snapshot_locked(account_id)
            if side == "buy":
                total = price * quantity + fees
                if total > snapshot["cash_usd"]:
                    raise ValueError("paper order exceeds available cash")
            else:
                available = snapshot["positions"].get(symbol, {}).get("quantity", 0)
                if quantity > available:
                    raise ValueError("paper sell would create a short position")
            order_id = uuid.uuid4().hex
            self.connection.execute(
                "INSERT INTO paper_orders(order_id, account_id, idempotency_key, symbol, side, "
                "quantity, price_usd, fees_usd) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (order_id, account_id, idempotency_key, symbol, side,
                 quantity, price, fees),
            )
            return {
                "order_id": order_id, "duplicate": False,
                "record_type": "SIMULATED_FILL", "side": side,
                "symbol": symbol, "quantity": quantity,
            }

    def buy(self, account_id, symbol, quantity, price_usd, fees_usd, idempotency_key):
        return self._apply(account_id, symbol, "buy", quantity, price_usd, fees_usd, idempotency_key)

    def sell(self, account_id, symbol, quantity, price_usd, fees_usd, idempotency_key):
        return self._apply(account_id, symbol, "sell", quantity, price_usd, fees_usd, idempotency_key)

    @_serialized
    def journal(self, account_id: str):
        account = self.connection.execute(
            "SELECT 1 FROM paper_accounts WHERE account_id=%s", (account_id,)
        ).fetchone()
        if not account:
            raise ValueError("paper account does not exist")
        rows = self.connection.execute(
            "SELECT order_id, idempotency_key, symbol, side, quantity, price_usd, fees_usd, created_at "
            "FROM paper_orders WHERE account_id=%s ORDER BY journal_sequence",
            (account_id,),
        ).fetchall()
        return [
            {
                "record_type": "SIMULATED_FILL",
                "order_id": row["order_id"],
                "idempotency_key": row["idempotency_key"],
                "symbol": row["symbol"],
                "side": row["side"],
                "quantity": int(row["quantity"]),
                "price_usd": Decimal(row["price_usd"]),
                "fees_usd": Decimal(row["fees_usd"]),
                "created_at": row["created_at"].astimezone(timezone.utc).isoformat(),
            }
            for row in rows
        ]

    @_serialized
    def integrity_check(self):
        self.connection.execute("SELECT 1").fetchone()
        self.connection.execute(
            "SELECT COUNT(*) FROM paper_accounts"
        ).fetchone()
        self.connection.execute(
            "SELECT COUNT(*) FROM paper_orders"
        ).fetchone()
        return "ok"

    @_serialized
    def close(self):
        self.connection.close()
