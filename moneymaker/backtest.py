"""Replay historical 1h candles through the real risk engine, with fees and slippage.

Limitations (be honest with yourself about these):
- No historical funding / open interest, so those fields are omitted from the snapshot.
- Funding payments are not simulated.
- If a candle touches both stop and take-profit, the stop is assumed to hit first (conservative).
- A good backtest does not guarantee future profit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import journal
from .config import Config
from .risk import Decision, Rejected, size_order

TAKER_FEE = 0.00045
MAKER_FEE = 0.00015
SLIPPAGE = 0.0002
WARMUP = 48


@dataclass
class Pos:
    coin: str
    is_buy: bool
    size: float
    entry: float
    stop: float
    tp: float | None
    entry_fee: float
    meta: dict | None = None


@dataclass
class Result:
    start_equity: float
    end_equity: float
    max_drawdown: float
    trades: list
    fees: float
    daily_equity: list
    days_target_hit: int
    months_killed: int
    buy_hold_return: float
    trade_log: list = field(default_factory=list)

    def summary(self) -> str:
        pnls = [t for t in self.trades]
        wins = [t for t in pnls if t > 0]
        losses = [t for t in pnls if t <= 0]
        gross_w, gross_l = sum(wins), -sum(losses)
        pf = gross_w / gross_l if gross_l else float("inf") if gross_w else 0.0
        rets = [b / a - 1 for a, b in zip(self.daily_equity, self.daily_equity[1:]) if a > 0]
        if len(rets) > 1:
            m = sum(rets) / len(rets)
            sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
            sharpe = m / sd * math.sqrt(365) if sd else 0.0
        else:
            sharpe = 0.0
        ret = self.end_equity / self.start_equity - 1
        return "\n".join([
            f"Start equity        : {self.start_equity:,.2f} USD",
            f"End equity          : {self.end_equity:,.2f} USD ({ret:+.2%})",
            f"Buy&hold (equal wt) : {self.buy_hold_return:+.2%}   <- compare!",
            f"Max drawdown        : {self.max_drawdown:.2%}",
            f"Trades              : {len(pnls)}  win rate {len(wins) / len(pnls):.0%}" if pnls else "Trades              : 0",
            f"Profit factor       : {pf:.2f}   (>1.3 after fees is decent)",
            f"Sharpe (daily, ann.): {sharpe:.2f}",
            f"Fees paid           : {self.fees:,.2f} USD",
            f"Days daily-target hit: {self.days_target_hit}   monthly kill switch: {self.months_killed}",
        ])


class RuleBrain:
    """Momentum rule found by backtesting (train/hold-out split, 200 days, BTC/ETH/SOL 1h):
    trade the coin with the strongest 12h move if it agrees with its 24h-average trend,
    long or short, 4% stop / 8% take-profit (2:1). Deterministic and free (no API calls)."""

    def __init__(self, lookback=12, ema=24, sl=0.04, tp=0.08, min_move=0.01,
                 max_move=None, sides="both", skip_coins=()):
        self.lb, self.ema, self.sl, self.tp, self.mm = lookback, ema, sl, tp, min_move
        self.max_move, self.sides, self.skip = max_move, sides, tuple(skip_coins)

    def decide(self, snap: dict) -> Decision:
        best, best_move = None, 0.0
        for coin, c in snap["coins"].items():
            if coin in self.skip:
                continue
            cl = [k[3] for k in c["candles_1h_ohlcv"]]
            move = cl[-1] / cl[-1 - self.lb] - 1
            trend = cl[-1] / (sum(cl[-self.ema:]) / self.ema) - 1
            if self.sides != "both" and (move > 0) != (self.sides == "long"):
                continue
            if self.max_move is not None and abs(move) > self.max_move:
                continue  # move already exhausted
            if move * trend > 0 and abs(move) > abs(best_move) and abs(move) > self.mm:
                best, best_move = coin, move
        if best is None:
            return Decision("hold", next(iter(snap["coins"])))
        return Decision("open_long" if best_move > 0 else "open_short", best, 0.7, self.sl, self.tp, "momentum")


class CachedBrain:
    """Wraps a brain, caching decisions on disk so re-runs cost nothing."""

    def __init__(self, inner, model: str, max_calls: int, path="data/decision_cache.json"):
        self.inner, self.model, self.max_calls = inner, model, max_calls
        self.path = Path(path)
        self.cache = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.calls = 0

    def decide(self, snap: dict) -> Decision:
        key = hashlib.sha256((self.model + json.dumps(snap, sort_keys=True)).encode()).hexdigest()
        if key not in self.cache:
            if self.calls >= self.max_calls:
                raise SystemExit(f"--max-calls {self.max_calls} reached; raise it to continue (cached decisions are kept).")
            d = self.inner.decide(snap)
            self.calls += 1
            self.cache[key] = d.__dict__
            self.path.parent.mkdir(exist_ok=True)
            self.path.write_text(json.dumps(self.cache))
        return Decision(**self.cache[key])


def _snap(candles, i, equity, positions, opens):
    coins = {}
    for coin, cs in candles.items():
        window = cs[i - WARMUP:i]  # only candles closed before decision time: no lookahead
        coins[coin] = {
            "mid": opens[coin],
            "prev_day_px": float(cs[i - 24]["o"]),
            "candles_1h_ohlcv": [[float(k["o"]), float(k["h"]), float(k["l"]), float(k["c"]), float(k["v"])]
                                 for k in window],
        }
    return {"coins": coins, "equity": equity, "positions": [
        {"coin": p.coin, "size": p.size if p.is_buy else -p.size, "entry_px": p.entry,
         "unrealized_pnl": (opens[p.coin] - p.entry) * p.size * (1 if p.is_buy else -1),
         "notional": p.size * opens[p.coin]} for p in positions]}


def run_backtest(cfg: Config, candles: dict, brain, step_hours=4, start_equity=300.0,
                 taker=TAKER_FEE, maker=MAKER_FEE, slip=SLIPPAGE) -> Result:
    coins = list(candles)
    n = min(len(v) for v in candles.values())
    cash, positions, trades, fees = start_equity, [], [], 0.0
    trade_log, cur = [], {}
    daily_eq, peak, max_dd = [start_equity], start_equity, 0.0
    day = month = None
    day_start = month_start = start_equity
    target_hit_today, days_hit, months_killed, killed_month = False, 0, 0, None

    def unreal(prices):
        return sum((prices[p.coin] - p.entry) * p.size * (1 if p.is_buy else -1) for p in positions)

    def close(p, px, rate, reason="other"):
        nonlocal cash, fees
        pnl = (px - p.entry) * p.size * (1 if p.is_buy else -1)
        fee = p.size * px * rate
        cash += pnl - fee
        fees += fee
        trades.append(pnl - fee - p.entry_fee)
        m = p.meta or {}
        trade_log.append({
            "source": "backtest", "coin": p.coin, "side": "long" if p.is_buy else "short",
            "open_t": m.get("open_t"), "close_t": cur["ts"].isoformat(), "entry": p.entry, "exit": px,
            "stop": p.stop, "tp": p.tp, "size": p.size, "pnl_net": pnl - fee - p.entry_fee,
            "fees": fee + p.entry_fee, "exit_reason": reason, "features": m.get("features"),
            "rationale": m.get("rationale"), "confidence": m.get("confidence")})
        positions.remove(p)

    for i in range(WARMUP, n):
        ts = datetime.fromtimestamp(candles[coins[0]][i]["t"] / 1000, timezone.utc)
        cur["ts"] = ts
        opens = {c: float(candles[c][i]["o"]) for c in coins}
        equity = cash + unreal(opens)
        if ts.strftime("%Y-%m-%d") != day:
            if day is not None:
                daily_eq.append(equity)
            day, day_start, target_hit_today = ts.strftime("%Y-%m-%d"), equity, False
        if ts.strftime("%Y-%m") != month:
            month, month_start = ts.strftime("%Y-%m"), equity
        daily_pnl, monthly_pnl = equity - day_start, equity - month_start

        def flatten():
            for p in list(positions):
                exit_px = opens[p.coin] * (1 - slip if p.is_buy else 1 + slip)
                close(p, exit_px, taker, "flatten")

        if monthly_pnl <= -cfg.max_monthly_loss_pct * month_start:
            if killed_month != month:
                killed_month, months_killed = month, months_killed + 1
            flatten()
        elif cfg.daily_profit_target_pct > 0 and daily_pnl >= cfg.daily_profit_target_pct * day_start:
            if not target_hit_today:
                target_hit_today, days_hit = True, days_hit + 1
            flatten()
        elif (i - WARMUP) % step_hours == 0:
            snap = _snap(candles, i, equity, positions, opens)
            d = brain.decide(snap)
            if d.action == "close":
                for p in [p for p in positions if p.coin == d.coin]:
                    close(p, opens[p.coin] * (1 - slip if p.is_buy else 1 + slip), taker, "signal_close")
            elif d.action in ("open_long", "open_short") and not any(p.coin == d.coin for p in positions):
                exposure = sum(p.size * opens[p.coin] for p in positions)
                try:
                    o = size_order(d, cfg, equity, opens[d.coin], exposure, daily_pnl, monthly_pnl)
                except Rejected:
                    o = None
                if o:
                    entry = o.entry_px * (1 + slip if o.is_buy else 1 - slip)
                    fee = o.size * entry * taker
                    cash -= fee
                    fees += fee
                    positions.append(Pos(o.coin, o.is_buy, o.size, entry, o.stop_px, o.take_profit_px, fee, {
                        "open_t": ts.isoformat(), "features": journal.features(snap["coins"][d.coin], ts.hour),
                        "rationale": d.rationale, "confidence": d.confidence}))

        # Intra-candle stop / take-profit. Stop is checked first (conservative).
        for p in list(positions):
            hi, lo, op = (float(candles[p.coin][i][k]) for k in ("h", "l", "o"))
            if p.is_buy:
                if lo <= p.stop:
                    close(p, min(p.stop, op) * (1 - slip), taker, "stop")
                elif p.tp and hi >= p.tp:
                    close(p, p.tp, maker, "take_profit")
            else:
                if hi >= p.stop:
                    close(p, max(p.stop, op) * (1 + slip), taker, "stop")
                elif p.tp and lo <= p.tp:
                    close(p, p.tp, maker, "take_profit")

        closes = {c: float(candles[c][i]["c"]) for c in coins}
        eq_close = cash + unreal(closes)
        peak = max(peak, eq_close)
        max_dd = max(max_dd, (peak - eq_close) / peak)

    closes = {c: float(candles[c][n - 1]["c"]) for c in coins}
    end_equity = cash + unreal(closes)
    daily_eq.append(end_equity)
    bh = sum(float(candles[c][n - 1]["c"]) / float(candles[c][WARMUP]["o"]) - 1 for c in coins) / len(coins)
    return Result(start_equity, end_equity, max_dd, trades, fees, daily_eq, days_hit, months_killed, bh, trade_log)


def fetch_candles(coins, days, cache_dir="data") -> dict:
    """Real mainnet 1h candles (Hyperliquid serves at most the latest 5000 = ~208 days). Cached on disk."""
    from hyperliquid.utils import constants

    from .hl import make_info
    if (days + 2) * 24 > 5000:
        raise SystemExit("--days must be <= 205")
    info = make_info(constants.MAINNET_API_URL)
    end = int(time.time() * 1000)
    start = end - (days * 24 + WARMUP) * 3600_000
    out = {}
    for coin in coins:
        path = Path(cache_dir) / f"{coin}_1h_{days}d_{datetime.now(timezone.utc):%Y%m%d}.json"
        if path.exists():
            out[coin] = json.loads(path.read_text())
            continue
        out[coin] = info.candles_snapshot(coin, "1h", start, end)
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(out[coin]))
    common = set.intersection(*(set(k["t"] for k in v) for v in out.values()))
    return {c: sorted((k for k in v if k["t"] in common), key=lambda k: k["t"]) for c, v in out.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--step-hours", type=int, default=4, help="how often the brain decides")
    ap.add_argument("--brain", choices=["rule", "claude"], default="rule")
    ap.add_argument("--equity", type=float, default=300.0, help="USD (5,000,000 IDR ~ 300)")
    ap.add_argument("--max-calls", type=int, default=300, help="cap on paid Claude API calls")
    ap.add_argument("--last-days", type=int, default=0, help="only simulate the most recent N days")
    ap.add_argument("--journal-out", default="", help="write the simulated trades as a journal (jsonl)")
    a = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    cfg = Config.from_env(require_keys=False)
    candles = fetch_candles(cfg.coins, a.days)
    if a.last_days:
        candles = {c: v[-(a.last_days * 24 + WARMUP):] for c, v in candles.items()}
    if a.brain == "claude":
        from .brain import Brain
        n_calls = a.days * 24 // a.step_hours
        print(f"Claude brain: up to ~{n_calls} API calls (cached ones are free, cap {a.max_calls}).")
        brain = CachedBrain(Brain(cfg.model), cfg.model, a.max_calls)
    else:
        brain = RuleBrain()
    res = run_backtest(cfg, candles, brain, a.step_hours, a.equity)
    print(res.summary())
    if a.journal_out:
        Path(a.journal_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.journal_out).write_text("".join(json.dumps(t) + "\n" for t in res.trade_log))
        print(f"journal: {len(res.trade_log)} trades -> {a.journal_out}")


if __name__ == "__main__":
    main()
