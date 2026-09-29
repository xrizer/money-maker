import logging
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from hyperliquid.info import Info

from .brain import Brain
from .config import Config
from .executor import Executor
from .market import snapshot
from .state import load_baselines, mark_target_hit
from .risk import Rejected, size_order

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
    log.info("network=%s live=%s coins=%s", cfg.network, cfg.live, cfg.coins)
    if cfg.network == "mainnet" and cfg.live:
        log.warning("LIVE MAINNET TRADING ENABLED")

    while True:
        try:
            snap = snapshot(info, cfg.account_address, cfg.coins)
            st = load_baselines(snap["equity"])
            start_equity = st["day_start_equity"]
            daily_pnl = snap["equity"] - start_equity
            monthly_pnl = snap["equity"] - st["month_start_equity"]
            exposure = sum(p["notional"] for p in snap["positions"])

            if monthly_pnl <= -cfg.max_monthly_loss_pct * st["month_start_equity"]:
                log.warning("MONTHLY LOSS LIMIT hit (%.2f USD). Flattening; no trading until next month.", monthly_pnl)
                if snap["positions"]:
                    ex.flatten(info, snap["positions"])
                time.sleep(cfg.loop_seconds)
                continue

            target = cfg.daily_profit_target_pct * start_equity
            if cfg.daily_profit_target_pct > 0 and daily_pnl >= target:
                if not st["target_hit"]:
                    log.info("DAILY TARGET REACHED: %+.2f USD (%.2f%%). Flattening; stopping until next UTC day.",
                             daily_pnl, 100 * daily_pnl / start_equity)
                    ex.flatten(info, snap["positions"])
                    mark_target_hit()
                time.sleep(cfg.loop_seconds)
                continue

            d = brain.decide(snap)
            log.info("decision: %s", d)
            if d.action == "close":
                ex.close(d.coin)
            elif d.action in ("open_long", "open_short"):
                if any(p["coin"] == d.coin for p in snap["positions"]):
                    log.info("already positioned in %s, skipping", d.coin)
                else:
                    try:
                        o = size_order(d, cfg, snap["equity"], snap["coins"][d.coin]["mid"],
                                       exposure, daily_pnl, monthly_pnl)
                        ex.open(o, sz_dec[d.coin])
                    except Rejected as e:
                        log.info("REJECTED by risk engine: %s", e)
        except Exception:
            log.exception("cycle failed")
        time.sleep(cfg.loop_seconds)


if __name__ == "__main__":
    run()
