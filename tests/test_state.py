import json

from moneymaker.state import load_baselines


def test_baseline_survives_restart(tmp_path):
    p = tmp_path / "s.json"
    a = load_baselines(300.0, p)
    b = load_baselines(310.0, p)  # "restart" later same day, equity changed
    assert b["day_start_equity"] == 300.0 == b["month_start_equity"]
    json.loads(p.read_text())
