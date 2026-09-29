"""Persist day/month baselines so restarting the bot each day keeps limits meaningful."""
import json
from datetime import datetime, timezone
from pathlib import Path

PATH = Path("state.json")


def load_baselines(equity: float, path: Path = PATH, ctx: str = "") -> dict:
    """Return {day_start_equity, month_start_equity, target_hit}, rolling over UTC day/month.

    ctx identifies what is being measured (network + account + paper/real). If it changes, the baselines are
    reset, so a paper balance can never be compared with a real one (that produced a fake -80% "loss").
    """
    now = datetime.now(timezone.utc)
    day, month = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")
    try:
        st = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        st = {}
    if st.get("ctx", "") != ctx:
        st = {"ctx": ctx}
    if st.get("month") != month:
        st.update(month=month, month_start_equity=equity)
    if st.get("day") != day:
        st.update(day=day, day_start_equity=equity, target_hit=False)
    path.write_text(json.dumps(st))
    return st


def mark_target_hit(path: Path = PATH):
    st = json.loads(path.read_text())
    st["target_hit"] = True
    path.write_text(json.dumps(st))
