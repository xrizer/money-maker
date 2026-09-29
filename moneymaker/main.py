import logging
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from hyperliquid.info import Info

from .brain import Brain
from .config import Config
from .executor import Executor
from .market import snapshot
from .risk import Rejected, size_order

log = logging.getLogger("main")


def run():
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    cfg = Config.from_env()
    ex = Executor(cfg)
    info = Info(ex.url, skip_ws=True)
    brain = Brain(cfg.model)
    sz_dec = {m["name"]: m["szDecimals"] for m in info.meta()["universe"]}
    log.info("network=%s live=%s coins=%s", cfg.network, cfg.live, cfg.coins)
    if cfg.network == "mainnet" and cfg.live:
        log.warning("LIVE MAINNET TRADING ENABLED")

    day, start_equity = None, None
    while True:
        try:
            snap = snapshot(info, cfg.account_address, cfg.coins)
            today = datetime.now(timezone.utc).date()
            if day != today:
                day, start_equity = today, snap["equity"]
            daily_pnl = snap["equity"] - start_equity
            exposure = sum(p["notional"] for p in snap["positions"])

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
                                       exposure, daily_pnl)
                        ex.open(o, sz_dec[d.coin])
                    except Rejected as e:
                        log.info("REJECTED by risk engine: %s", e)
        except Exception:
            log.exception("cycle failed")
        time.sleep(cfg.loop_seconds)


if __name__ == "__main__":
    run()
