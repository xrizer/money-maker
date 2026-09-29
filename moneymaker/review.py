"""Weekly review: journal -> stats -> Claude's analysis -> proposals -> out-of-sample backtest verdict.

Nothing here changes the bot. It prints/writes a report; you decide what to adopt.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from . import journal
from .backtest import WARMUP, RuleBrain, fetch_candles, run_backtest
from .config import Config

ALLOWED = {"lookback": int, "ema": int, "sl": float, "tp": float, "min_move": float,
           "max_move": float, "sides": str, "skip_coins": list}


def _group(trades, keyfn):
    out = {}
    for t in trades:
        out.setdefault(keyfn(t), []).append(t["pnl_net"])
    rows = {}
    for k, v in sorted(out.items(), key=lambda kv: str(kv[0])):
        w, l = sum(x for x in v if x > 0), -sum(x for x in v if x <= 0)
        rows[str(k)] = {"n": len(v), "win_rate": round(sum(x > 0 for x in v) / len(v), 2),
                        "pnl": round(sum(v), 2), "profit_factor": round(w / l, 2) if l else None}
    return rows


def stats(trades: list) -> dict:
    f = lambda t: t.get("features") or {}
    return {
        "overall": _group(trades, lambda t: "all"),
        "by_side": _group(trades, lambda t: t["side"]),
        "by_coin": _group(trades, lambda t: t["coin"]),
        "by_exit": _group(trades, lambda t: t["exit_reason"]),
        "by_abs_move_12h": _group(trades, lambda t: "<2%" if abs(f(t).get("move_12h", 0)) < .02 else "2-4%" if abs(f(t).get("move_12h", 0)) < .04 else ">=4%"),
        "by_utc_hour": _group(trades, lambda t: "00-08" if f(t).get("hour_utc", 0) < 8 else "08-16" if f(t).get("hour_utc", 0) < 16 else "16-24"),
    }


TOOL = {
    "name": "submit_review",
    "description": "Submit the review of the trade journal.",
    "input_schema": {"type": "object", "required": ["summary", "findings", "proposals"], "properties": {
        "summary": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "object", "required": ["text", "evidence"],
                     "properties": {"text": {"type": "string"}, "evidence": {"type": "string"}}}},
        "proposals": {"type": "array", "maxItems": 3, "items": {"type": "object", "required": ["name", "why", "params"],
                      "properties": {"name": {"type": "string"}, "why": {"type": "string"},
                                     "params": {"type": "object", "properties": {
                                         "lookback": {"type": "integer"}, "ema": {"type": "integer"},
                                         "sl": {"type": "number"}, "tp": {"type": "number"},
                                         "min_move": {"type": "number"}, "max_move": {"type": "number"},
                                         "sides": {"type": "string", "enum": ["both", "long", "short"]},
                                         "skip_coins": {"type": "array", "items": {"type": "string"}}}}}}}}},
}

SYSTEM = """You review the trade journal of a small automated crypto perpetuals bot (momentum rules:
strongest 12h move that agrees with the 24h trend, long or short, 4% stop / 8% take-profit).
Be a skeptical quant. Rules:
- Sample sizes are small. A group with fewer than ~15 trades is noise; say so instead of drawing conclusions.
- Separate what the data shows from speculation. Quote the numbers as evidence.
- Propose at most 3 changes, ONLY using the allowed parameters (lookback, ema, sl, tp, min_move, max_move,
  sides, skip_coins). Each proposal will be backtested on data it was not derived from; most should fail.
- Prefer no proposal over a weak one. An empty proposals list is a good answer when the data is inconclusive.
- You can never change risk limits (risk per trade, leverage, loss stops)."""


def ask_claude(model: str, st: dict, trades: list, client=None) -> dict:
    import anthropic
    client = client or anthropic.Anthropic()
    worst = sorted(trades, key=lambda t: t["pnl_net"])[:8]
    slim = [{k: t.get(k) for k in ("coin", "side", "exit_reason", "pnl_net", "features")} for t in worst]
    resp = client.messages.create(
        model=model, max_tokens=2000, system=SYSTEM, tools=[TOOL],
        tool_choice={"type": "tool", "name": "submit_review"},
        messages=[{"role": "user", "content": json.dumps({"n_trades": len(trades), "stats": st, "worst_trades": slim})}])
    return next(b for b in resp.content if b.type == "tool_use").input


def clean_params(p: dict) -> dict:
    """Only whitelisted parameters with correct types survive; anything else (e.g. risk limits) is dropped."""
    out = {}
    for k, v in p.items():
        if k in ALLOWED and isinstance(v, (int, float, str, list)):
            try:
                out[k] = ALLOWED[k](v) if ALLOWED[k] is not list else list(v)
            except (TypeError, ValueError):
                pass
    return out


def _pf(trades):
    w, l = sum(x for x in trades if x > 0), -sum(x for x in trades if x <= 0)
    return w / l if l else float("inf") if w else 0.0


def validate(proposals: list, cfg: Config, candles: dict, first_trade_iso: str, step_hours=4) -> list:
    """Backtest baseline vs each proposal on candles BEFORE the journal period (out-of-sample for the
    proposal, which was derived from the journal) and on the journal period itself (in-sample, for reference)."""
    first_ms = int(datetime.fromisoformat(first_trade_iso).timestamp() * 1000)
    coins = list(candles)
    idx = next((i for i, k in enumerate(candles[coins[0]]) if k["t"] >= first_ms), len(candles[coins[0]]))
    A = {c: v[:idx] for c, v in candles.items()}
    B = {c: v[max(0, idx - WARMUP):] for c, v in candles.items()}
    if idx < WARMUP + 24 * 30:
        return [{"name": p["name"], "verdict": "cannot validate: fewer than 30 days of data before the journal period"} for p in proposals]
    base = RuleBrain()
    ba, bb = run_backtest(cfg, A, base, step_hours), run_backtest(cfg, B, base, step_hours)
    out = []
    for p in proposals:
        params = clean_params(p.get("params", {}))
        brain = RuleBrain(**params)  # clean_params only lets constructor arguments through
        ra, rb = run_backtest(cfg, A, brain, step_hours), run_backtest(cfg, B, brain, step_hours)
        d_oos = ra.end_equity - ba.end_equity
        ok = d_oos > 0.01 * ba.start_equity and len(ra.trades) >= 15 and _pf(ra.trades) >= _pf(ba.trades)
        out.append({"name": p["name"], "params": params,
                    "oos": {"baseline_ret": ba.end_equity / ba.start_equity - 1, "proposal_ret": ra.end_equity / ra.start_equity - 1,
                            "trades": len(ra.trades), "pf": _pf(ra.trades), "baseline_pf": _pf(ba.trades)},
                    "journal_period": {"baseline_ret": bb.end_equity / bb.start_equity - 1, "proposal_ret": rb.end_equity / rb.start_equity - 1},
                    "verdict": "CANDIDATE (passed out-of-sample check; still test on testnet)" if ok else "REJECT (did not beat baseline out-of-sample)"})
    return out


def render(trades, st, review, results) -> str:
    L = [f"# Trade review {datetime.now(timezone.utc):%Y-%m-%d}", "", f"Trades analysed: {len(trades)}", "", "## Stats", "```", json.dumps(st, indent=1), "```"]
    if review:
        L += ["", "## Claude's review", review["summary"], ""] + [f"- {f['text']}  \n  _evidence: {f['evidence']}_" for f in review["findings"]]
    L += ["", "## Proposals (validated out-of-sample)"]
    if not results:
        L.append("None. Inconclusive data is a valid outcome: keep the current rules.")
    for r in results:
        L.append(f"- **{r['name']}** {r.get('params', '')} -> {r['verdict']}")
        if "oos" in r:
            o, j = r["oos"], r["journal_period"]
            L.append(f"  - out-of-sample: baseline {o['baseline_ret']:+.1%} vs proposal {o['proposal_ret']:+.1%} "
                     f"({o['trades']} trades, PF {o['pf']:.2f} vs {o['baseline_pf']:.2f})")
            L.append(f"  - journal period (in-sample, biased): baseline {j['baseline_ret']:+.1%} vs proposal {j['proposal_ret']:+.1%}")
    L += ["", "Nothing was changed. To adopt a candidate, edit the RuleBrain defaults, run the backtest, then testnet first."]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--journal", default=str(journal.PATH))
    ap.add_argument("--min-trades", type=int, default=20)
    ap.add_argument("--days", type=int, default=200, help="candle history used for validation")
    ap.add_argument("--proposals", default="", help="JSON file of proposals; skips the Claude call")
    ap.add_argument("--no-llm", action="store_true", help="stats + validation of --proposals only")
    a = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    cfg = Config.from_env(require_keys=False)
    trades = journal.load(Path(a.journal))
    if len(trades) < a.min_trades:
        raise SystemExit(f"Only {len(trades)} closed trades in the journal; need {a.min_trades}+ before a review means anything.")
    st = stats(trades)
    review, proposals = None, []
    if a.proposals:
        proposals = json.loads(Path(a.proposals).read_text())
    elif not a.no_llm:
        review = ask_claude(cfg.model, st, trades)
        proposals = review["proposals"]
    first = min(t["open_t"] for t in trades)
    results = validate(proposals, cfg, fetch_candles(cfg.coins, a.days), first) if proposals else []
    report = render(trades, st, review, results)
    out = Path("data/reviews") / f"review_{datetime.now(timezone.utc):%Y%m%d_%H%M}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)
    print(report, f"\n\nSaved: {out}")


if __name__ == "__main__":
    main()
