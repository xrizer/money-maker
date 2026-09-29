import json

from moneymaker.state import load_baselines


def test_baseline_survives_restart(tmp_path):
    p = tmp_path / "s.json"
    a = load_baselines(300.0, p)
    b = load_baselines(310.0, p)  # "restart" later same day, equity changed
    assert b["day_start_equity"] == 300.0 == b["month_start_equity"]
    json.loads(p.read_text())


def test_changing_context_resets_baselines(tmp_path):
    p = tmp_path / "s.json"
    load_baselines(300.0, p, ctx="testnet|0x0|paper")
    b = load_baselines(61.7, p, ctx="testnet|0x0|real")   # e.g. user forgot PAPER_EQUITY
    assert b["month_start_equity"] == 61.7                  # no fake -238 USD "loss"
    same = load_baselines(70.0, p, ctx="testnet|0x0|real")
    assert same["month_start_equity"] == 61.7
