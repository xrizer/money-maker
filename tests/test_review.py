import json
from types import SimpleNamespace

import pytest

from moneymaker import journal, review
from moneymaker.backtest import RuleBrain

T = lambda pnl, side="long", reason="stop", mv=0.03, hr=10, coin="BTC": {
    "coin": coin, "side": side, "exit_reason": reason, "pnl_net": pnl, "open_t": "2026-01-01T00:00:00+00:00",
    "features": {"move_12h": mv, "hour_utc": hr}}


def test_features_shape():
    cs = {"candles_1h_ohlcv": [[1, 1, 1, 100 + i, 1] for i in range(48)]}
    f = journal.features(cs, 7)
    assert f["hour_utc"] == 7 and f["move_12h"] > 0 and f["trend_24h"] > 0 and f["vol_24h"] >= 0


def test_stats_groups():
    st = review.stats([T(5), T(-2, "short"), T(-2, "short", "take_profit")])
    assert st["by_side"]["short"]["n"] == 2 and st["by_side"]["long"]["win_rate"] == 1.0
    assert st["overall"]["all"]["pnl"] == 1.0


def test_clean_params_drops_risk_limits_and_bad_types():
    p = review.clean_params({"sl": "0.05", "max_risk_per_trade_pct": 0.5, "leverage": 50, "sides": "long", "tp": "abc"})
    assert p == {"sl": 0.05, "sides": "long"}


def test_rule_brain_filters():
    def snap(closes): return {"coins": {"BTC": {"candles_1h_ohlcv": [[c, c, c, c, 1] for c in closes]}}}
    up = snap([100] * 36 + [100 + i for i in range(1, 13)] + [])  # +12% in 12h, above avg
    up = snap([100] * 36 + [100 + 1.0 * i for i in range(1, 13)])
    assert RuleBrain().decide(up).action == "open_long"
    assert RuleBrain(max_move=0.05).decide(up).action == "hold"      # exhausted move skipped
    assert RuleBrain(sides="short").decide(up).action == "hold"
    assert RuleBrain(skip_coins=("BTC",)).decide(up).action == "hold"


class FakeInfo:
    def __init__(self, fills): self.fills = fills
    def user_fills(self, addr): return self.fills


def test_reconcile_closed_trade_uses_real_fills_and_labels_stop(tmp_path):
    ot = journal.OpenTrades(tmp_path / "o.json")
    ot.add("BTC", {"coin": "BTC", "side": "long", "open_ms": 1000, "open_t": "x", "stop": 98.0, "tp": 104.0, "entry": 100.0})
    fills = [{"coin": "BTC", "time": 1500, "dir": "Open Long", "px": "100", "sz": "1", "fee": "0.05", "closedPnl": "0"},
             {"coin": "BTC", "time": 9000, "dir": "Close Long", "px": "98.05", "sz": "1", "fee": "0.05", "closedPnl": "-1.95"}]
    jp = tmp_path / "j.jsonl"
    journal.reconcile(FakeInfo(fills), "0x", [], ot, jp, now_ms=10_000)
    rec = journal.load(jp)[0]
    assert rec["exit_reason"] == "stop" and rec["pnl_net"] == pytest.approx(-2.05) and ot.d == {}


def test_reconcile_keeps_open_position_and_drops_unfilled_entry(tmp_path):
    ot = journal.OpenTrades(tmp_path / "o.json")
    ot.add("BTC", {"coin": "BTC", "open_ms": 0})
    journal.reconcile(FakeInfo([]), "0x", [{"coin": "BTC"}], ot, tmp_path / "j.jsonl", now_ms=10**9)
    assert "BTC" in ot.d                                               # still held: untouched
    journal.reconcile(FakeInfo([]), "0x", [], ot, tmp_path / "j.jsonl", now_ms=10**9)
    assert ot.d == {}                                                  # entry never filled: dropped


def test_ask_claude_parses_forced_tool_call():
    payload = {"summary": "s", "findings": [], "proposals": []}
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **k: SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input=payload)])))
    assert review.ask_claude("m", {}, [T(1)], client=client) == payload


def test_validate_refuses_without_history():
    from moneymaker.config import Config
    c = [{"t": 1_700_000_000_000 + i * 3600_000, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1} for i in range(100)]
    out = review.validate([{"name": "x", "params": {}}], Config(coins=("BTC",)), {"BTC": c}, "2023-11-14T22:00:00+00:00")
    assert "cannot validate" in out[0]["verdict"]
