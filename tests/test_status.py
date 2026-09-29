import json

from moneymaker.config import Config
from moneymaker.status import Reporter


def test_reporter_writes_valid_json_and_bounds_history(tmp_path):
    p = tmp_path / "status.json"
    r = Reporter(Config(), path=p)
    for i in range(350):
        r.event("hold", f"e{i}")
        r.write(state="trading", equity=300 + i)
    d = json.loads(p.read_text())
    assert len(d["history"]) == 300 and len(d["events"]) == 40
    assert d["limits"]["max_monthly_loss_pct"] == 0.08 and d["state"] == "trading"
    assert not (tmp_path / "status.tmp").exists()


def test_reporter_resumes_previous_history(tmp_path):
    p = tmp_path / "status.json"
    Reporter(Config(), path=p).write(state="trading", equity=300)
    assert len(Reporter(Config(), path=p).history) == 1
