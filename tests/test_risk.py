import pytest

from moneymaker.config import Config
from moneymaker.risk import Decision, Rejected, size_order

CFG = Config()


def d(**k):
    base = dict(action="open_long", coin="BTC", confidence=0.8, stop_loss_pct=0.02, take_profit_pct=0.04)
    return Decision(**{**base, **k})


def test_sizes_to_risk_budget():
    o = size_order(d(), CFG, 10_000, 50_000, 0, 0)
    assert o.size * 50_000 == pytest.approx(5_000)  # 1% risk / 2% stop, at the 50% position cap
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
        size_order(d(), CFG, 10_000, 100, 9_990, 0)


def test_profit_target_stops_trading():
    with pytest.raises(Rejected):
        size_order(d(), Config(daily_profit_target_pct=0.02), 10_200, 100, 0, 250)


def test_monthly_kill_switch():
    with pytest.raises(Rejected):
        size_order(d(), CFG, 10_000, 100, 0, 0, monthly_pnl=-900)


def test_key_and_address_validation():
    from moneymaker.config import valid_address, valid_key
    assert valid_key("0x" + "a" * 64) and valid_key("b" * 64)
    assert not valid_key("0xYourApiAgentPrivateKey") and not valid_key("")
    assert valid_address("0x" + "1" * 40) and not valid_address("0xYourMainAccountAddress")


def test_drawdown_derisk_scales_and_floors():
    from moneymaker.risk import risk_scale
    c = Config(dd_derisk_pct=0.08, min_risk_scale=0.25)
    assert risk_scale(c, 300, 300) == 1.0
    assert risk_scale(c, 288, 300) == pytest.approx(0.5)       # 4% drawdown -> half size
    assert risk_scale(c, 200, 300) == 0.25                      # deep drawdown -> floor, never zero
    assert risk_scale(Config(dd_derisk_pct=0), 200, 300) == 1.0


def test_scale_shrinks_order_and_position_cap():
    full = size_order(d(), CFG, 10_000, 100, 0, 0)
    half = size_order(d(), CFG, 10_000, 100, 0, 0, scale=0.5)
    assert half.size == pytest.approx(full.size / 2)
    with pytest.raises(Rejected):
        size_order(d(), Config(max_positions=1), 10_000, 100, 0, 0, n_positions=1)
