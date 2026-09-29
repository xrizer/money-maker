import pytest

from moneymaker.config import Config
from moneymaker.risk import Decision, Rejected, size_order

CFG = Config()


def d(**k):
    base = dict(action="open_long", coin="BTC", confidence=0.8, stop_loss_pct=0.02, take_profit_pct=0.04)
    return Decision(**{**base, **k})


def test_sizes_to_risk_budget():
    o = size_order(d(), CFG, 10_000, 50_000, 0, 0)
    assert o.size * 50_000 == pytest.approx(5_000 * 0.4, rel=1e-6) or o.size * 50_000 <= 2_000
    assert o.stop_px == pytest.approx(49_000)
    assert o.take_profit_px == pytest.approx(52_000)


def test_short_stop_above_entry():
    o = size_order(d(action="open_short"), CFG, 10_000, 100, 0, 0)
    assert o.stop_px > 100 and o.take_profit_px < 100


@pytest.mark.parametrize("kw", [
    dict(coin="DOGE"), dict(confidence=0.3), dict(stop_loss_pct=0), dict(stop_loss_pct=0.5),
])
def test_rejects(kw):
    with pytest.raises(Rejected):
        size_order(d(**kw), CFG, 10_000, 100, 0, 0)


def test_kill_switch():
    with pytest.raises(Rejected):
        size_order(d(), CFG, 10_000, 100, 0, -400)


def test_exposure_cap():
    with pytest.raises(Rejected):
        size_order(d(), CFG, 10_000, 100, 4_990, 0)


def test_profit_target_stops_trading():
    with pytest.raises(Rejected):
        size_order(d(), CFG, 10_200, 100, 0, 250)


def test_monthly_kill_switch():
    with pytest.raises(Rejected):
        size_order(d(), CFG, 10_000, 100, 0, 0, monthly_pnl=-900)
