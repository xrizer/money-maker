"""Deterministic risk layer. Claude proposes; this module disposes."""
from dataclasses import dataclass
from typing import Optional

from .config import Config


@dataclass
class Decision:
    action: str  # open_long | open_short | close | hold
    coin: str
    confidence: float = 0.0
    stop_loss_pct: float = 0.0    # distance from entry, e.g. 0.02 = 2%
    take_profit_pct: float = 0.0
    rationale: str = ""


@dataclass
class Order:
    coin: str
    is_buy: bool
    size: float          # in coin units
    entry_px: float
    stop_px: float
    take_profit_px: Optional[float]
    leverage: int


class Rejected(Exception):
    pass


def size_order(d: Decision, cfg: Config, equity: float, px: float,
               total_exposure: float, daily_pnl: float,
               monthly_pnl: float = 0.0) -> Order:
    """Validate a decision and compute a size that respects every limit."""
    if d.coin not in cfg.coins:
        raise Rejected(f"{d.coin} not in allowed coins")
    if d.confidence < cfg.min_confidence:
        raise Rejected(f"confidence {d.confidence:.2f} < {cfg.min_confidence}")
    if equity <= 0:
        raise Rejected("no equity")
    if daily_pnl <= -cfg.max_daily_loss_pct * equity:
        raise Rejected("daily loss limit hit (kill switch)")
    if monthly_pnl <= -cfg.max_monthly_loss_pct * equity:
        raise Rejected("monthly loss limit hit (kill switch)")
    if daily_pnl >= cfg.daily_profit_target_pct * equity:
        raise Rejected("daily profit target reached, done for the day")
    if not 0.002 <= d.stop_loss_pct <= 0.10:
        raise Rejected("stop_loss_pct must be within 0.2%..10% (stop is mandatory)")

    risk_usd = cfg.max_risk_per_trade_pct * equity
    notional = risk_usd / d.stop_loss_pct           # loss at stop == risk_usd
    notional = min(notional, cfg.max_position_pct * equity)
    notional = min(notional, cfg.max_total_exposure_pct * equity - total_exposure)
    if notional < 11:                               # Hyperliquid min order ~$10
        raise Rejected("resulting notional below minimum / exposure cap reached")

    is_buy = d.action == "open_long"
    sgn = 1 if is_buy else -1
    tp = px * (1 + sgn * d.take_profit_pct) if d.take_profit_pct > 0 else None
    return Order(d.coin, is_buy, notional / px, px, px * (1 - sgn * d.stop_loss_pct),
                 tp, cfg.max_leverage)
