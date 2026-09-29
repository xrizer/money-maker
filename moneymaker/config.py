import os
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
    max_position_pct: float = 0.20
    max_total_exposure_pct: float = 0.50
    max_risk_per_trade_pct: float = 0.01
    max_daily_loss_pct: float = 0.03
    daily_profit_target_pct: float = 0.02
    min_confidence: float = 0.6
    loop_seconds: int = 900

    @classmethod
    def from_env(cls):
        return cls(
            account_address=os.environ["HL_ACCOUNT_ADDRESS"],
            secret_key=os.environ["HL_SECRET_KEY"],
            network=os.getenv("HL_NETWORK", "testnet"),
            live=os.getenv("LIVE", "false").lower() == "true",
            model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
            coins=tuple(c.strip() for c in os.getenv("COINS", "BTC,ETH,SOL").split(",")),
            max_leverage=int(_f("MAX_LEVERAGE", 3)),
            max_position_pct=_f("MAX_POSITION_PCT", 0.20),
            max_total_exposure_pct=_f("MAX_TOTAL_EXPOSURE_PCT", 0.50),
            max_risk_per_trade_pct=_f("MAX_RISK_PER_TRADE_PCT", 0.01),
            max_daily_loss_pct=_f("MAX_DAILY_LOSS_PCT", 0.03),
            daily_profit_target_pct=_f("DAILY_PROFIT_TARGET_PCT", 0.02),
            min_confidence=_f("MIN_CONFIDENCE", 0.6),
            loop_seconds=int(_f("LOOP_SECONDS", 900)),
        )
