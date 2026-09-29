import types

from moneymaker.config import Config
from moneymaker.executor import Executor, parse
from moneymaker.risk import Order

FILLED = lambda sz: {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"filled": {"totalSz": str(sz), "avgPx": "100", "oid": 1}}]}}}
RESTING = {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"resting": {"oid": 2}}]}}}
ERR = {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"error": "Order has invalid price."}]}}}


class FakeEx:
    def __init__(self, entry, triggers):
        self.entry, self.triggers, self.orders, self.closed = entry, list(triggers), [], []
    def update_leverage(self, *a, **k): return {}
    def market_open(self, *a, **k): return self.entry
    def order(self, coin, is_buy, sz, px, ot, reduce_only=False):
        self.orders.append((ot["trigger"]["tpsl"], sz, reduce_only)); return self.triggers.pop(0)
    def market_close(self, coin): self.closed.append(coin); return {"status": "ok"}


def make(entry, triggers):
    e = object.__new__(Executor)
    e.cfg, e.ex = Config(live=True), FakeEx(entry, triggers)
    return e


O = Order("BTC", True, 1.0, 100.0, 96.0, 108.0, 3)


def test_happy_path_protected():
    e = make(FILLED(1.0), [RESTING, RESTING])
    assert e.open(O, 3) is True
    assert [o[0] for o in e.ex.orders] == ["sl", "tp"] and all(o[2] for o in e.ex.orders) and not e.ex.closed


def test_stop_loss_rejected_closes_position():
    e = make(FILLED(1.0), [ERR])
    assert e.open(O, 3) is False
    assert e.ex.closed == ["BTC"]                       # never leave a position unprotected


def test_take_profit_rejected_keeps_position():
    e = make(FILLED(1.0), [RESTING, ERR])
    assert e.open(O, 3) is True and not e.ex.closed


def test_entry_rejected_inside_ok_status():
    e = make(ERR, [])
    assert e.open(O, 3) is False and e.ex.orders == [] and not e.ex.closed


def test_partial_fill_protects_only_filled_size():
    e = make(FILLED(0.4), [RESTING, RESTING])
    assert e.open(O, 3) is True and all(o[1] == 0.4 for o in e.ex.orders)


def test_parse_handles_garbage():
    assert parse(None)[0] is False and parse({"status": "err", "response": "x"})[0] is False
    assert parse({"status": "ok", "response": {}})[0] is False
