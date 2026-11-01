from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR

from .models import as_decimal, validate_symbol


@dataclass(frozen=True)
class RiskRequest:
    symbol: str
    equity_usd: Decimal
    cash_available_usd: Decimal
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    max_loss_usd: Decimal
    max_position_pct: Decimal
    existing_exposure_usd: Decimal = Decimal("0")
    current_daily_loss_usd: Decimal = Decimal("0")
    max_daily_loss_usd: Decimal | None = None

    def __post_init__(self):
        object.__setattr__(self, "symbol", validate_symbol(self.symbol))
        positive = ("equity_usd", "cash_available_usd", "entry_price",
                    "target_price", "max_loss_usd", "max_position_pct")
        for field in positive:
            value = as_decimal(getattr(self, field), field)
            if value <= 0:
                raise ValueError(f"{field} must be positive")
            object.__setattr__(self, field, value)
        stop = as_decimal(self.stop_price, "stop_price")
        if stop <= 0:
            raise ValueError("stop_price must be positive")
        object.__setattr__(self, "stop_price", stop)
        for field in ("existing_exposure_usd", "current_daily_loss_usd"):
            value = as_decimal(getattr(self, field), field)
            if value < 0:
                raise ValueError(f"{field} cannot be negative")
            object.__setattr__(self, field, value)
        if self.max_daily_loss_usd is not None:
            value = as_decimal(self.max_daily_loss_usd, "max_daily_loss_usd")
            if value <= 0:
                raise ValueError("max_daily_loss_usd must be positive")
            object.__setattr__(self, "max_daily_loss_usd", value)
        if self.max_position_pct > 100:
            raise ValueError("max_position_pct cannot exceed 100")


@dataclass(frozen=True)
class RiskResult:
    symbol: str
    approved: bool
    quantity: int
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    risk_per_share_usd: Decimal
    planned_loss_usd: Decimal
    notional_usd: Decimal
    reward_risk: Decimal
    reason: str

    def to_dict(self):
        return {key: (str(value) if isinstance(value, Decimal) else value)
                for key, value in self.__dict__.items()}


def _floor_quantity(amount: Decimal, price: Decimal) -> int:
    return int((amount / price).to_integral_value(rounding=ROUND_FLOOR))


def evaluate_risk(request: RiskRequest) -> RiskResult:
    if not isinstance(request, RiskRequest):
        raise TypeError("request must be a RiskRequest")
    if request.stop_price >= request.entry_price:
        raise ValueError("long-only stop_price must be below entry_price")
    if request.target_price <= request.entry_price:
        raise ValueError("long-only target_price must be above entry_price")
    risk_per_share = request.entry_price - request.stop_price
    risk_budget = request.max_loss_usd
    if request.max_daily_loss_usd is not None:
        remaining_daily = request.max_daily_loss_usd - request.current_daily_loss_usd
        risk_budget = min(risk_budget, max(Decimal("0"), remaining_daily))
    position_limit = request.equity_usd * request.max_position_pct / Decimal("100")
    remaining_position = max(Decimal("0"), position_limit - request.existing_exposure_usd)
    quantity = min(
        _floor_quantity(risk_budget, risk_per_share),
        _floor_quantity(remaining_position, request.entry_price),
        _floor_quantity(request.cash_available_usd, request.entry_price),
    )
    planned_loss = risk_per_share * quantity
    notional = request.entry_price * quantity
    reward_risk = (request.target_price - request.entry_price) / risk_per_share
    reason = "risk, cash and position limits satisfied" if quantity else "limits leave no whole share available"
    if request.max_daily_loss_usd is not None and request.current_daily_loss_usd >= request.max_daily_loss_usd:
        reason = "daily loss limit reached"
    return RiskResult(
        symbol=request.symbol, approved=quantity > 0, quantity=quantity,
        entry_price=request.entry_price, stop_price=request.stop_price,
        target_price=request.target_price, risk_per_share_usd=risk_per_share,
        planned_loss_usd=planned_loss, notional_usd=notional,
        reward_risk=reward_risk, reason=reason,
    )
