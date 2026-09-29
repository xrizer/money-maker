"""Hyperliquid SDK helpers.

The bot only trades perpetuals. The SDK's constructors also download spot metadata and can crash on it
(IndexError in Info.__init__ when spot listings change), so we hand them an empty spot universe.
"""
from hyperliquid.info import Info

EMPTY_SPOT = {"universe": [], "tokens": []}


def make_info(url: str) -> Info:
    return Info(url, skip_ws=True, spot_meta=EMPTY_SPOT)
