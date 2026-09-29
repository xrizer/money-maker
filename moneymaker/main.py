import logging
import os
import time

from dotenv import load_dotenv
from hyperliquid.info import Info

from . import journal
from .brain import Brain
from .config import Config
from .executor import Executor
from .market import snapshot
from .risk import Rejected, size_order
from .state import load_baselines, mark_target_hit
from .status import Reporter, serve

log = logging.getLogger("main")


def run():
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    cfg = Config.from_env()
    ex = Executor(cfg)
    info = Info(ex.url, skip_ws=True)
    if cfg.strategy == "claude":
        brain = Brain(cfg.model)
    else:
        from .backtest import RuleBrain
        brain = RuleBrain()
    sz_dec = {m["name"]: m["szDecimals"] for m in info.meta()["universe"]}
    rep = Reporter(cfg)
    ot = journal.OpenTrades()
    port = int(os.getenv("UI_PORT", "8080"))
    if port:
        serve(port)
        log.info("dashboard: http://127.0.0.1:%d/dashboard.html", port)
    log.info("network=%s live=%s coins=%s", cfg.network, cfg.live, cfg.coins)
    if cfg.network == "mainnet" and cfg.live:
        log.warning("LIVE MAINNET TRADING ENABLED")

    last_decision, last_open = None, None
    while True:
        state, fields = "trading", {}
        try:
            snap = snapshot(info, cfg.account_address, cfg.coins)
            if not cfg.live and cfg.paper_equity > 0:
                snap["equity"], snap["positions"] = cfg.paper_equity, []
            if cfg.live:
                journal.reconcile(info, cfg.account_address, snap["positions"], ot)
            st = load_baselines(snap["equity"])
            start_equity = st["day_start_equity"]
            daily_pnl = snap["equity"] - start_equity
            monthly_pnl = snap["equity"] - st["month_start_equity"]
            exposure = sum(p["notional"] for p in snap["positions"])
            fields = dict(equity=snap["equity"], day_start=start_equity, month_start=st["month_start_equity"],
                          daily_pnl=daily_pnl, monthly_pnl=monthly_pnl, positions=snap["positions"],
                          prices={c: v["mid"] for c, v in snap["coins"].items()})

            if monthly_pnl <= -cfg.max_monthly_loss_pct * st["month_start_equity"]:
                state = "monthly_stop"
                log.warning("MONTHLY LOSS LIMIT hit (%.2f USD). Flattening; no trading until next month.", monthly_pnl)
                if snap["positions"]:
                    rep.event("kill", f"Monthly loss limit hit ({monthly_pnl:+.2f} USD): closing all positions")
                    ex.flatten(info, snap["positions"])
            elif cfg.daily_profit_target_pct > 0 and daily_pnl >= cfg.daily_profit_target_pct * start_equity:
                state = "daily_target"
                if not st["target_hit"]:
                    log.info("DAILY TARGET REACHED: %+.2f USD. Flattening; stopping until next UTC day.", daily_pnl)
                    rep.event("target", f"Daily target reached ({daily_pnl:+.2f} USD): closing all, stopping for today")
                    ex.flatten(info, snap["positions"])
                    mark_target_hit()
            else:
                d = brain.decide(snap)
                log.info("decision: %s", d)
                last_decision = {"action": d.action, "coin": d.coin, "confidence": d.confidence,
                                 "stop_loss_pct": d.stop_loss_pct, "take_profit_pct": d.take_profit_pct,
                                 "rationale": d.rationale, "t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                if d.action == "close":
                    rep.event("close", f"Close {d.coin}")
                    ex.close(d.coin)
                elif d.action in ("open_long", "open_short"):
                    if any(p["coin"] == d.coin for p in snap["positions"]):
                        log.info("already positioned in %s, skipping", d.coin)
                    else:
                        try:
                            o = size_order(d, cfg, snap["equity"], snap["coins"][d.coin]["mid"],
                                           exposure, daily_pnl, monthly_pnl)
                            side = "LONG" if o.is_buy else "SHORT"
                            mode = "" if cfg.live else "[dry run] "
                            if cfg.live or last_open != (o.coin, side):  # dry run: don't repeat the same line every cycle
                                rep.event("open", f"{mode}{side} {o.coin} ~{o.size * o.entry_px:,.0f} USD, "
                                                  f"stop {o.stop_px:,.4g}, take-profit {o.take_profit_px:,.4g}")
                            last_open = (o.coin, side)
                            ex.open(o, sz_dec[d.coin])
                            if cfg.live:
                                ot.add(o.coin, {"source": "live", "coin": o.coin, "side": "long" if o.is_buy else "short",
                                                "open_t": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
                                                "open_ms": int(time.time() * 1000), "entry": o.entry_px, "stop": o.stop_px,
                                                "tp": o.take_profit_px, "size": o.size, "rationale": d.rationale,
                                                "confidence": d.confidence,
                                                "features": journal.features(snap["coins"][d.coin], time.gmtime().tm_hour)})
                        except Rejected as e:
                            log.info("REJECTED by risk engine: %s", e)
                            rep.event("rejected", f"{d.coin}: {e}")
                else:
                    last_open = None
                    rep.event("hold", "No clear edge: holding")
        except Exception as e:
            state = "error"
            log.exception("cycle failed")
            rep.event("error", f"Cycle failed: {type(e).__name__}: {e}")
        finally:
            rep.write(state=state, last_decision=last_decision, **fields)
        if os.getenv("ONCE") == "true":
            return
        time.sleep(cfg.loop_seconds)


if __name__ == "__main__":
    run()
