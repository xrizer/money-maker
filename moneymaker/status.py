"""Writes ui/status.json each cycle and serves the ui/ folder (localhost only) for the dashboard."""
import hmac
import json
import threading
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .control import ACTIONS

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


class Reporter:
    def __init__(self, cfg, control=None, path: Path = UI_DIR / "status.json"):
        self.cfg, self.control, self.path = cfg, control, path
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
            "paused": bool(self.control and self.control.paused), "token": self.control.token if self.control else "",
            **fields, "events": self.events, "history": self.history,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(self.path)  # atomic: the page never reads a half-written file


LOCAL_HOSTS = ("127.0.0.1", "localhost")


def make_handler(control):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(UI_DIR), **k)

        def log_message(self, *a):
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _host_ok(self) -> bool:
            # Blocks DNS-rebinding: a hostile site resolving to 127.0.0.1 would send its own Host header.
            return self.headers.get("Host", "").rsplit(":", 1)[0] in LOCAL_HOSTS

        def _reply(self, code: int, body: dict):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self._host_ok():
                return self._reply(403, {"error": "bad host"})
            super().do_GET()

        def do_POST(self):
            if self.path != "/api/control":
                return self._reply(404, {"error": "not found"})
            origin = self.headers.get("Origin")
            if not self._host_ok() or (origin and origin != f"http://{self.headers.get('Host')}"):
                return self._reply(403, {"error": "forbidden origin"})
            if not hmac.compare_digest(self.headers.get("X-Token", ""), control.token):
                return self._reply(403, {"error": "bad token"})  # cross-site pages cannot read the token
            try:
                n = int(self.headers.get("Content-Length", 0))
                action = json.loads(self.rfile.read(min(n, 1024)))["action"]
                if action not in ACTIONS:
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                return self._reply(400, {"error": "bad request"})
            self._reply(200, control.apply(action))

    return Handler


def serve(port: int, control):
    """Bind 127.0.0.1 only: the dashboard is never exposed to the network."""
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(control))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
