"""Start/stop control shared between the dashboard's HTTP thread and the trading loop."""
import json
import secrets
import threading
from pathlib import Path

ACTIONS = ("pause", "resume", "flatten")


class Control:
    """paused: no NEW trades (open positions keep their exchange stop-loss/take-profit).
    flatten: close every position now, and stay paused. The paused flag survives restarts."""

    def __init__(self, path: Path = Path("data/control.json"), start_paused: bool = False):
        self.path = path
        self.token = secrets.token_urlsafe(16)  # per run; required by the HTTP API
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._flatten = False
        try:
            self._paused = bool(json.loads(path.read_text()).get("paused", start_paused))
        except (FileNotFoundError, ValueError):
            self._paused = start_paused
        self._save()

    @property
    def paused(self) -> bool:
        return self._paused

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"paused": self._paused}))

    def apply(self, action: str) -> dict:
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action!r}")
        with self._lock:
            self._paused = action != "resume"
            if action == "flatten":
                self._flatten = True
            self._save()
            paused = self._paused
        self._wake.set()  # wake the trading loop now instead of at the next hourly cycle
        return {"paused": paused}

    def take_flatten(self) -> bool:
        with self._lock:
            f, self._flatten = self._flatten, False
            return f

    def wait(self, seconds: float):
        self._wake.wait(seconds)
        self._wake.clear()
