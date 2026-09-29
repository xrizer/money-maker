"""Writes ui/status.json each cycle and serves the ui/ folder (localhost only) for the dashboard."""
import functools
import json
import threading
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


class Reporter:
    def __init__(self, cfg, path: Path = UI_DIR / "status.json"):
        self.cfg, self.path = cfg, path
        self.events, self.history = [], []
        try:
            old = json.loads(path.read_text())
            self.events, self.history = old.get("events", []), old.get("history", [])
        except (FileNotFoundError, ValueError):
            pass

    def event(self, kind: str, text: str):
        self.events.append({"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind, "text": text})
        self.events = self.events[-40:]

    def write(self, **fields):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if fields.get("equity") is not None:
            self.history = (self.history + [[now, fields["equity"]]])[-300:]
        c = self.cfg
        data = {
            "updated": now, "loop_seconds": c.loop_seconds, "network": c.network, "live": c.live,
            "paper": (not c.live and c.paper_equity > 0), "strategy": c.strategy,
            "limits": {
                "risk_per_trade_pct": c.max_risk_per_trade_pct, "max_leverage": c.max_leverage,
                "max_position_pct": c.max_position_pct, "max_daily_loss_pct": c.max_daily_loss_pct,
                "max_monthly_loss_pct": c.max_monthly_loss_pct, "daily_profit_target_pct": c.daily_profit_target_pct,
                "coins": list(c.coins),
            },
            **fields, "events": self.events, "history": self.history,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(self.path)  # atomic: the page never reads a half-written file


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def serve(port: int):
    """Bind 127.0.0.1 only: the dashboard is never exposed to the network."""
    handler = functools.partial(_Quiet, directory=str(UI_DIR))
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
