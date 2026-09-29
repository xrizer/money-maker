import time

from hyperliquid.info import Info


def snapshot(info: Info, address: str, coins) -> dict:
    """Compact, LLM-friendly market + account snapshot."""
    mids = info.all_mids()
    meta, ctxs = info.meta_and_asset_ctxs()
    ctx_by_coin = {m["name"]: c for m, c in zip(meta["universe"], ctxs)}
    now = int(time.time() * 1000)
    out = {"coins": {}, "positions": []}
    for coin in coins:
        candles = info.candles_snapshot(coin, "1h", now - 48 * 3600_000, now)
        c = ctx_by_coin[coin]
        out["coins"][coin] = {
            "mid": float(mids[coin]),
            "funding_hourly": float(c["funding"]),
            "open_interest": float(c["openInterest"]),
            "day_volume_usd": float(c["dayNtlVlm"]),
            "prev_day_px": float(c["prevDayPx"]),
            "candles_1h_ohlcv": [
                [float(k["o"]), float(k["h"]), float(k["l"]), float(k["c"]), float(k["v"])]
                for k in candles[-48:]
            ],
        }
    st = info.user_state(address)
    out["equity"] = float(st["marginSummary"]["accountValue"])
    for p in st["assetPositions"]:
        pos = p["position"]
        out["positions"].append({
            "coin": pos["coin"], "size": float(pos["szi"]),
            "entry_px": float(pos["entryPx"]), "unrealized_pnl": float(pos["unrealizedPnl"]),
            "notional": abs(float(pos["positionValue"])),
        })
    return out
