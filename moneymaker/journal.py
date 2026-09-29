"""Trade journal: one JSON line per closed trade, with the market features seen at entry."""
from __future__ import annotations

import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

PATH = Path("data/journal.jsonl")
OPEN_PATH = Path("data/open_trades.json")


def features(coin_snap: dict, hour_utc: int) -> dict:
    """What the market looked like when the trade was opened (from the last 48 hourly candles)."""
    cl = [k[3] for k in coin_snap["candles_1h_ohlcv"]]
    rets = [cl[i] / cl[i - 1] - 1 for i in range(-24, 0)]
    return {
        "move_12h": cl[-1] / cl[-13] - 1,
        "trend_24h": cl[-1] / (sum(cl[-24:]) / 24) - 1,
        "vol_24h": statistics.pstdev(rets),
        "hour_utc": hour_utc,
    }


def append(rec: dict, path: Path = PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def load(path: Path = PATH) -> list:
    try:
        return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    except FileNotFoundError:
        return []


class OpenTrades:
    """Live trades awaiting their exit (stops/take-profits fire on the exchange, not in this process)."""

    def __init__(self, path: Path = OPEN_PATH):
        self.path = path
        try:
            self.d = json.loads(path.read_text())
        except (FileNotFoundError, ValueError):
            self.d = {}

    def add(self, coin: str, rec: dict):
        self.d[coin] = rec
        self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.d))


def _reason(exit_px: float, rec: dict) -> str:
    if rec.get("stop") and abs(exit_px - rec["stop"]) / rec["stop"] < 0.005:
        return "stop"
    if rec.get("tp") and abs(exit_px - rec["tp"]) / rec["tp"] < 0.005:
        return "take_profit"
    return "other"


def reconcile(info, address: str, positions: list, ot: OpenTrades, journal_path: Path = PATH,
              now_ms: int | None = None):
    """Turn trades whose position has disappeared into journal records, using real fills (incl. fees)."""
    now_ms = now_ms or int(time.time() * 1000)
    held = {p["coin"] for p in positions}
    fills = None
    for coin, rec in list(ot.d.items()):
        if coin in held:
            continue
        fills = info.user_fills(address) if fills is None else fills
        mine = [f for f in fills if f["coin"] == coin and f["time"] >= rec["open_ms"]]
        closes = [f for f in mine if f["dir"].startswith("Close")]
        if not closes:
            if now_ms - rec["open_ms"] > 15 * 60_000:  # entry never filled
                del ot.d[coin]
                ot._save()
            continue
        sz = sum(float(f["sz"]) for f in closes)
        exit_px = sum(float(f["px"]) * float(f["sz"]) for f in closes) / sz
        fees = sum(float(f["fee"]) for f in mine)
        pnl = sum(float(f["closedPnl"]) for f in closes) - fees
        out = {**rec, "close_t": datetime.fromtimestamp(max(f["time"] for f in closes) / 1000, timezone.utc).isoformat(),
               "exit": exit_px, "pnl_net": pnl, "fees": fees, "exit_reason": _reason(exit_px, rec)}
        out.pop("open_ms", None)
        append(out, journal_path)
        del ot.d[coin]
        ot._save()
