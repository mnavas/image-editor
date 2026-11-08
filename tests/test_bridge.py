"""Bridge tests — the control server + MCP bridge client driving a LIVE window.

Uses a socketpair so the full wire path (BridgeClient <-> ControlServer._serve <->
queued GUI-thread dispatch <-> engine <-> live document) is exercised without
binding a TCP port. Run: QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests
"""
import os
import socket
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from config import Config
from core.document import Document


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _window(app):
    from widgets.main_window import MainWindow
    win = MainWindow(Config())
    win.ctl.doc = Document(base=np.full((120, 160, 3), 100, np.uint8))
    return win


def _pump_until(app, predicate, timeout=10.0):
    deadline = time.time() + timeout
    while not predicate() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.003)


def test_menubar_is_generated_from_registry(app):
    win = _window(app)
    menus = {a.text(): a for a in win.menuBar().actions()}
    assert {"Edit", "Image", "Layer"} <= set(menus)
    edit = [a.text() for a in menus["Edit"].menu().actions()]
    assert "Undo" in edit and "Redo" in edit


def test_dispatch_runs_on_gui_thread(app):
    """A request emitted from a worker thread is handled on the GUI thread."""
    from control_server import ControlServer, _Call
    win = _window(app)
    srv = ControlServer(win, autostart=False)
    gui_thread = threading.current_thread()
    seen = {}

    def worker():
        call = _Call({"op": "doc_inspect", "token": srv.token})
        seen["ran_on"] = None
        orig = srv._handle
        def spy(req):
            seen["ran_on"] = threading.current_thread()
            return orig(req)
        srv._handle = spy
        srv._dispatch.emit(call)
        call.done.wait(timeout=5)
        seen["result"] = call.result

    t = threading.Thread(target=worker)
    t.start()
    _pump_until(app, lambda: "result" in seen)
    t.join(timeout=5)
    assert seen["ran_on"] is gui_thread          # handled on the GUI thread
    assert seen["result"]["ok"] and seen["result"]["result"]["rotation"] == 0


def test_bridge_client_drives_live_document(app):
    """Full path: MCP BridgeClient -> ControlServer._serve -> live window."""
    from control_server import ControlServer
    import mcp_server as M

    win = _window(app)
    srv = ControlServer(win, autostart=False)

    sa, sb = socket.socketpair()                 # no bind/listen needed
    threading.Thread(target=srv._serve, args=(sa,), daemon=True).start()

    client = M.BridgeClient("x", 0, srv.token)   # inject the pre-connected socket
    client._conn = sb
    client._f = sb.makefile("rwb")

    out = {}

    def drive():
        try:
            out["ping"] = client.call("ping")
            out["adjust"] = client.call("command_run", id="adjust.apply",
                                        params={"exposure": 1.0, "contrast": 25})
            out["rotate"] = client.call("command_run", id="image.rotate",
                                        params={"direction": "cw"})
            out["inspect"] = client.call("doc_inspect")
            out["preview"] = client.call("render_preview", max_side=64)
            out["badtoken"] = "n/a"
        except Exception as e:                   # pragma: no cover
            out["error"] = repr(e)
        finally:
            out["done"] = True

    threading.Thread(target=drive, daemon=True).start()
    _pump_until(app, lambda: out.get("done"))

    assert "error" not in out, out.get("error")
    assert out["ping"]["hasDocument"] is True
    assert out["adjust"]["result"]["steps"] == 2
    assert out["inspect"]["rotation"] == 90
    assert out["preview"]["format"] == "png" and max(
        out["preview"]["width"], out["preview"]["height"]) == 64
    # the bridge mutated the REAL window's document, not a copy
    assert len(win.ctl.doc.layers) == 1 and win.ctl.doc.rotation == 90


def test_bridge_rejects_bad_token(app):
    from control_server import ControlServer
    import mcp_server as M

    win = _window(app)
    srv = ControlServer(win, autostart=False)
    sa, sb = socket.socketpair()
    threading.Thread(target=srv._serve, args=(sa,), daemon=True).start()

    client = M.BridgeClient("x", 0, "WRONG-TOKEN")
    client._conn = sb
    client._f = sb.makefile("rwb")

    out = {}

    def drive():
        try:
            client.call("doc_inspect")
        except RuntimeError as e:
            out["err"] = str(e)
        finally:
            out["done"] = True

    threading.Thread(target=drive, daemon=True).start()
    _pump_until(app, lambda: out.get("done"))
    assert "bad token" in out.get("err", "")
