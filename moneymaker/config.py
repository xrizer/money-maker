import os
import re
from dataclasses import dataclass, field


def _f(name, default):
    return float(os.getenv(name, default))


@dataclass(frozen=True)
class Config:
    account_address: str = ""
    secret_key: str = ""
    network: str = "testnet"
    live: bool = False
    model: str = "claude-sonnet-5-5"
    coins: tuple = ("BTC", "ETH", "SOL")
    max_leverage: int = 3
    max_position_pct: float = 0.50
    max_total_exposure_pct: float = 1.00
    max_risk_per_trade_pct: float = 0.01
    max_daily_loss_pct: float = 0.03
    daily_profit_target_pct: float = 0.0  # 0 = disabled (backtests: daily targets hurt)
    max_positions: int = 3            # concurrent positions (BTC/ETH/SOL crash together)
    dd_derisk_pct: float = 0.08       # 0 = off. Risk shrinks linearly to min_risk_scale as drawdown from peak equity reaches this
    min_risk_scale: float = 0.25
    paper_equity: float = 0.0  # dry-run only: pretend this many USD instead of reading the account
    strategy: str = "rule"  # rule | claude
    max_monthly_loss_pct: float = 0.08
    min_confidence: float = 0.6
    loop_seconds: int = 3600

    @classmethod
    def from_env(cls, require_keys: bool = True):
        return cls(
            account_address=os.environ["HL_ACCOUNT_ADDRESS"] if require_keys else os.getenv("HL_ACCOUNT_ADDRESS", ""),
            secret_key=os.environ["HL_SECRET_KEY"] if require_keys else os.getenv("HL_SECRET_KEY", ""),
            network=os.getenv("HL_NETWORK", "testnet"),
            live=os.getenv("LIVE", "false").lower() == "true",
            model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
            coins=tuple(c.strip() for c in os.getenv("COINS", "BTC,ETH,SOL").split(",")),
            max_leverage=int(_f("MAX_LEVERAGE", 3)),
            max_position_pct=_f("MAX_POSITION_PCT", 0.50),
            max_total_exposure_pct=_f("MAX_TOTAL_EXPOSURE_PCT", 1.00),
            max_risk_per_trade_pct=_f("MAX_RISK_PER_TRADE_PCT", 0.01),
            max_daily_loss_pct=_f("MAX_DAILY_LOSS_PCT", 0.03),
            daily_profit_target_pct=_f("DAILY_PROFIT_TARGET_PCT", 0.0),
            strategy=os.getenv("STRATEGY", "rule"),
            paper_equity=_f("PAPER_EQUITY", 0.0),
            max_positions=int(_f("MAX_POSITIONS", 3)),
            dd_derisk_pct=_f("DD_DERISK_PCT", 0.08),
            min_risk_scale=_f("MIN_RISK_SCALE", 0.25),
            max_monthly_loss_pct=_f("MAX_MONTHLY_LOSS_PCT", 0.08),
            min_confidence=_f("MIN_CONFIDENCE", 0.6),
            loop_seconds=int(_f("LOOP_SECONDS", 3600)),
        )


def valid_key(k: str) -> bool:
    return bool(re.fullmatch(r"(0x)?[0-9a-fA-F]{64}", k or ""))


def valid_address(a: str) -> bool:
    return bool(re.fullmatch(r"0x[0-9a-fA-F]{40}", a or ""))
