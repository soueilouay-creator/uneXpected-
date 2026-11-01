from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .models import as_decimal, validate_symbol


def _serialized(method):
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class PaperPortfolio:
    """Append-only SQLite ledger for simulated long-only fills; never connects to a broker."""

    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self._lock = threading.RLock()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=5, isolation_level=None, check_same_thread=False)
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=5000")
        if self.path != ":memory:":
            self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS paper_accounts (
                account_id TEXT PRIMARY KEY,
                initial_cash_usd TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_orders (
                order_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL REFERENCES paper_accounts(account_id),
                idempotency_key TEXT NOT NULL UNIQUE,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL CHECK(side IN ('buy','sell')),
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                price_usd TEXT NOT NULL,
                fees_usd TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS paper_orders_no_update
            BEFORE UPDATE ON paper_orders BEGIN
                SELECT RAISE(ABORT, 'paper order ledger is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS paper_orders_no_delete
            BEFORE DELETE ON paper_orders BEGIN
                SELECT RAISE(ABORT, 'paper order ledger is append-only');
            END;
        """)

    @_serialized
    def open_account(self, account_id: str, initial_cash_usd):
        if not isinstance(account_id, str) or not account_id.strip() or len(account_id) > 64:
            raise ValueError("account_id must contain 1 to 64 characters")
        initial_cash = as_decimal(initial_cash_usd, "initial_cash_usd")
        if initial_cash <= 0:
            raise ValueError("initial_cash_usd must be positive")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                "INSERT INTO paper_accounts(account_id, initial_cash_usd, created_at) VALUES(?,?,?)",
                (account_id.strip(), str(initial_cash), datetime.now(timezone.utc).isoformat()),
            )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        return self.snapshot(account_id.strip())

    def _snapshot_locked(self, account_id: str):
        account = self.connection.execute(
            "SELECT initial_cash_usd FROM paper_accounts WHERE account_id=?", (account_id,)
        ).fetchone()
        if not account:
            raise ValueError("paper account does not exist")
        cash = Decimal(account[0])
        positions = {}
        orders = self.connection.execute(
            "SELECT symbol, side, quantity, price_usd, fees_usd FROM paper_orders WHERE account_id=? ORDER BY rowid",
            (account_id,),
        ).fetchall()
        for symbol, side, quantity, price_text, fee_text in orders:
            quantity = int(quantity)
            price = Decimal(price_text)
            fee = Decimal(fee_text)
            position = positions.setdefault(symbol, {"quantity": 0, "average_price": Decimal("0")})
            if side == "buy":
                new_qty = position["quantity"] + quantity
                total_cost = position["average_price"] * position["quantity"] + price * quantity
                position["quantity"] = new_qty
                position["average_price"] = total_cost / Decimal(new_qty)
                cash -= price * quantity + fee
            else:
                position["quantity"] -= quantity
                cash += price * quantity - fee
                if position["quantity"] == 0:
                    position["average_price"] = Decimal("0")
        positions = {
            symbol: {"quantity": value["quantity"], "average_price": value["average_price"]}
            for symbol, value in positions.items() if value["quantity"] > 0
        }
        return {"account_id": account_id, "cash_usd": cash, "positions": positions}

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
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self.connection.execute(
                "SELECT order_id, account_id, symbol, side, quantity, price_usd, fees_usd FROM paper_orders WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                same = existing[1:] == (account_id, symbol, side, quantity, str(price), str(fees))
                if not same:
                    raise ValueError("idempotency_key was already used for a different paper order")
                self.connection.execute("COMMIT")
                return {"order_id": existing[0], "duplicate": True, "side": side, "symbol": symbol, "quantity": quantity}
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
                "INSERT INTO paper_orders(order_id, account_id, idempotency_key, symbol, side, quantity, price_usd, fees_usd, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (order_id, account_id, idempotency_key, symbol, side, quantity, str(price), str(fees), datetime.now(timezone.utc).isoformat()),
            )
            self.connection.execute("COMMIT")
            return {"order_id": order_id, "duplicate": False, "side": side, "symbol": symbol, "quantity": quantity}
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def buy(self, account_id, symbol, quantity, price_usd, fees_usd, idempotency_key):
        return self._apply(account_id, symbol, "buy", quantity, price_usd, fees_usd, idempotency_key)

    def sell(self, account_id, symbol, quantity, price_usd, fees_usd, idempotency_key):
        return self._apply(account_id, symbol, "sell", quantity, price_usd, fees_usd, idempotency_key)

    @_serialized
    def integrity_check(self):
        return self.connection.execute("PRAGMA integrity_check").fetchone()[0]

    @_serialized
    def backup(self, destination: str | Path):
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        if str(target.resolve()) == str(Path(self.path).resolve()) if self.path != ":memory:" else False:
            raise ValueError("backup destination must differ from the active database")
        backup_db = sqlite3.connect(str(target), timeout=5)
        try:
            self.connection.backup(backup_db)
            result = backup_db.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError("backup integrity check failed")
        finally:
            backup_db.close()
        return {"path": str(target), "integrity": "ok"}

    @_serialized
    def close(self):
        self.connection.close()
