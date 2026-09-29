import pytest

from moneymaker.backtest import WARMUP, run_backtest
from moneymaker.config import Config
from moneymaker.risk import Decision

T0 = 1_700_006_400_000  # 2023-11-15 00:00 UTC, so test days align with candles


def mk(prices, wick=0.001):
    out = []
    for i, p in enumerate(prices):
        out.append({"t": T0 + i * 3600_000, "o": p, "h": p * (1 + wick), "l": p * (1 - wick), "c": p, "v": 1})
    return out


class Scripted:
    def __init__(self, d): self.d, self.done = d, False
    def decide(self, snap):
        if self.done: return Decision("hold", "BTC")
        self.done = True
        return self.d


CFG = Config(coins=("BTC",), daily_profit_target_pct=10.0, max_monthly_loss_pct=10.0)
LONG = Decision("open_long", "BTC", 0.9, 0.02, 0.04)


def test_flat_market_loses_only_fees():
    r = run_backtest(CFG, {"BTC": mk([100] * 200)}, Scripted(LONG), 1)
    assert r.fees > 0 and r.end_equity < r.start_equity and r.start_equity - r.end_equity < 2


def test_take_profit_hit_is_profitable():
    prices = [100] * (WARMUP + 2) + [105] * 50
    r = run_backtest(CFG, {"BTC": mk(prices)}, Scripted(LONG), 1)
    assert r.end_equity > r.start_equity and r.trades and r.trades[0] > 0


def test_stop_loss_hit_loses_about_risk_budget():
    cs = mk([100] * (WARMUP + 2) + [99] * 50)
    cs[WARMUP + 2]["l"] = 97.0  # candle opens above the 98 stop and trades through it (no gap)
    r = run_backtest(CFG, {"BTC": cs}, Scripted(LONG), 1)
    loss = r.start_equity - r.end_equity
    assert 0.008 * 300 < loss < 0.02 * 300  # ~1% risk plus fees/slippage


def test_gap_through_stop_loses_more_than_budget():
    # Stop orders cannot protect against gaps: fill is at the gapped open. Simulator must show that.
    r = run_backtest(CFG, {"BTC": mk([100] * (WARMUP + 2) + [90] * 50)}, Scripted(LONG), 1)
    assert r.start_equity - r.end_equity > 0.02 * 300


def test_no_lookahead_in_snapshot():
    seen = []
    class Spy:
        def decide(self, snap):
            seen.append(snap["coins"]["BTC"]["candles_1h_ohlcv"][-1][3]); return Decision("hold", "BTC")
    prices = list(range(100, 100 + WARMUP + 10))
    run_backtest(CFG, {"BTC": mk(prices)}, Spy(), 1)
    # decision at candle i may only see closes up to candle i-1
    assert seen[0] == prices[WARMUP - 1]


def test_daily_target_flattens_and_stops():
    cfg = Config(coins=("BTC",), daily_profit_target_pct=0.001, max_monthly_loss_pct=10.0)
    prices = [100] * (WARMUP + 2) + [103] * 10
    r = run_backtest(cfg, {"BTC": mk(prices)}, Scripted(LONG), 1)
    assert r.days_target_hit >= 1
