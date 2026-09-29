import http.client
import json

import pytest

from moneymaker.control import Control
from moneymaker.status import serve


def test_pause_resume_persist_and_flatten_once(tmp_path):
    p = tmp_path / "c.json"
    c = Control(p)
    assert not c.paused
    c.apply("pause")
    assert Control(p).paused                       # survives restart
    c.apply("flatten")
    assert c.take_flatten() and not c.take_flatten()   # consumed exactly once
    assert c.paused                                # flatten leaves trading paused
    c.apply("resume")
    assert not c.paused and not Control(p).paused
    with pytest.raises(ValueError):
        c.apply("rm -rf")


def test_start_paused_only_applies_without_saved_state(tmp_path):
    assert Control(tmp_path / "a.json", start_paused=True).paused
    c = Control(tmp_path / "b.json")
    c.apply("resume")
    assert not Control(tmp_path / "b.json", start_paused=True).paused   # saved state wins


@pytest.fixture
def server(tmp_path):
    c = Control(tmp_path / "c.json")
    srv = serve(0, c)
    yield c, srv.server_address[1]
    srv.shutdown()


def req(port, method, path, body=None, headers=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.putrequest(method, path, skip_host=True)
    conn.putheader("Host", host or f"127.0.0.1:{port}")
    for k, v in (headers or {}).items():
        conn.putheader(k, v)
    data = json.dumps(body).encode() if body is not None else b""
    conn.putheader("Content-Length", str(len(data)))
    conn.endheaders(data)
    r = conn.getresponse()
    return r.status, r.read()


def test_api_requires_token_local_host_and_same_origin(server):
    c, port = server
    ok = {"X-Token": c.token}
    assert req(port, "POST", "/api/control", {"action": "pause"})[0] == 403                       # no token
    assert req(port, "POST", "/api/control", {"action": "pause"}, {"X-Token": "wrong"})[0] == 403
    assert req(port, "POST", "/api/control", {"action": "pause"}, ok, host="evil.com")[0] == 403   # DNS rebinding
    assert req(port, "POST", "/api/control", {"action": "pause"},
               {**ok, "Origin": "http://evil.com"})[0] == 403                                       # cross-site page
    assert not c.paused                                                                             # nothing got through
    assert req(port, "POST", "/api/control", {"action": "nope"}, ok)[0] == 400
    assert req(port, "POST", "/api/control", {"action": "pause"}, {**ok, "Origin": f"http://127.0.0.1:{port}"})[0] == 200
    assert c.paused


def test_pages_refuse_foreign_host_header(server):
    _, port = server
    assert req(port, "GET", "/dashboard.html")[0] == 200
    assert req(port, "GET", "/dashboard.html", host="evil.com")[0] == 403
