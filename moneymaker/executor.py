import logging

import eth_account
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

from .config import Config
from .hl import EMPTY_SPOT
from .risk import Order

log = logging.getLogger("executor")


def parse(res) -> tuple:
    """(ok, status_or_error). Hyperliquid answers status "ok" even when the single order inside was rejected."""
    try:
        if res.get("status") != "ok":
            return False, str(res)
        st = res["response"]["data"]["statuses"][0]
    except (AttributeError, KeyError, IndexError, TypeError):
        return False, f"unexpected response: {res}"
    return ("error" not in st), (st["error"] if "error" in st else st)


def _px(x: float) -> float:
    return float(f"{x:.5g}")  # Hyperliquid: max 5 significant figures


class Executor:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        url = constants.MAINNET_API_URL if cfg.network == "mainnet" else constants.TESTNET_API_URL
        self.url = url
        wallet = eth_account.Account.from_key(cfg.secret_key)
        self.ex = Exchange(wallet, url, account_address=cfg.account_address or None, spot_meta=EMPTY_SPOT)

    def open(self, o: Order, sz_decimals: int) -> bool:
        """Open a position with a mandatory stop-loss. Returns True only if the position exists AND is protected."""
        size = round(o.size, sz_decimals)
        if not self.cfg.live:
            log.info("[DRY RUN] would open %s", o)
            return True
        self.ex.update_leverage(o.leverage, o.coin, is_cross=False)
        res = self.ex.market_open(o.coin, o.is_buy, size, slippage=0.01)
        log.info("entry: %s", res)
        ok, st = parse(res)
        if not ok or "filled" not in st:
            log.error("ENTRY FAILED, no position opened: %s", st)
            return False
        size = float(st["filled"]["totalSz"])  # may be a partial fill: protect what we actually hold
        # Protective reduce-only trigger orders. No confirmed stop-loss => no position.
        ok, msg = parse(self._trigger(o, size, o.stop_px, "sl"))
        if not ok:
            log.critical("STOP-LOSS REJECTED (%s): closing the position immediately", msg)
            log.info("emergency close: %s", self.ex.market_close(o.coin))
            return False
        if o.take_profit_px:
            ok, msg = parse(self._trigger(o, size, o.take_profit_px, "tp"))
            if not ok:
                log.warning("take-profit rejected (%s); position is still protected by its stop-loss", msg)
        return True

    def _trigger(self, o: Order, size: float, trig: float, tpsl: str):
        trig = _px(trig)
        limit = _px(trig * (0.97 if not o.is_buy else 1.03)) if tpsl == "sl" else trig
        res = self.ex.order(
            o.coin, not o.is_buy, size, limit,
            {"trigger": {"triggerPx": trig, "isMarket": tpsl == "sl", "tpsl": tpsl}},
            reduce_only=True,
        )
        log.info("%s order: %s", tpsl, res)
        return res

    def close(self, coin: str):
        if not self.cfg.live:
            log.info("[DRY RUN] would close %s", coin)
            return
        log.info("close: %s", self.ex.market_close(coin))

    def flatten(self, info, positions):
        """Cancel all resting/trigger orders and close every position."""
        if not self.cfg.live:
            log.info("[DRY RUN] would cancel orders and close %s", [p["coin"] for p in positions])
            return
        for o in info.open_orders(self.cfg.account_address):
            self.ex.cancel(o["coin"], o["oid"])
        for p in positions:
            self.close(p["coin"])
