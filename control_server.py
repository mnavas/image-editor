"""Loopback control server — the *bridge* half of the agent interface.

The running desktop app hosts this server on 127.0.0.1 so an MCP process (see
mcp_server.py --bridge) can drive the **live** document the user is looking at,
not a headless copy. This is PhotoCraft's two-mode design: the same command
registry (core/commands.py) backs both the headless engine and this bridge.

Wire protocol: JSON-lines (one compact JSON object per line) over TCP. Every
request carries the shared token. Requests:

    {"token","op":"ping"}
    {"token","op":"command_list","filter":?,"enabled_only":?}
    {"token","op":"command_run","id":...,"params":{...}}
    {"token","op":"command_batch","steps":[...],"stop_on_error":true}
    {"token","op":"doc_inspect"}
    {"token","op":"render_preview","max_side":1024}
    {"token","op":"open","path":...}        # opens a file in the live app
    {"token","op":"save","path":...}        # saves the live render

Thread safety: sockets are served on background threads, but the document is
only ever touched on the Qt GUI thread. Each request is marshalled across with a
queued signal + an Event the socket thread blocks on, so the engine sees exactly
the serialized, main-thread access the UI already relies on.
"""
from __future__ import annotations

import json
import secrets
import socket
import threading
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from core import commands

# Where the server advertises its port+token, so the bridge client can find a
# running app with no flags. Same dir the app already uses for caches.
INFO_PATH = Path.home() / ".cache" / "image-editor" / "control.json"


def _describe_run(res: dict) -> str:
    """One-line human summary of a command result, for the agent toast."""
    cid = res.get("id", "")
    label = commands.REGISTRY[cid].label if cid in commands.REGISTRY else cid
    if res.get("ok"):
        return f"Claude: {label}"
    return f"Claude: {label} failed — {res.get('error', '')}"


class _Call:
    """One request shuttled from a socket thread to the GUI thread and back."""
    __slots__ = ("req", "result", "done")

    def __init__(self, req: dict):
        self.req = req
        self.result: dict | None = None
        self.done = threading.Event()


class ControlServer(QObject):
    # emitted from a socket thread; delivered (queued) on the GUI thread
    _dispatch = pyqtSignal(object)

    def __init__(self, window, host: str = "127.0.0.1", port: int = 0,
                 token: str | None = None, *, autostart: bool = True):
        super().__init__()
        self.window = window
        self.token = token or secrets.token_hex(16)
        # ControlServer lives in the GUI thread, so this cross-thread emit is a
        # QueuedConnection: _run_on_gui runs on the GUI thread.
        self._dispatch.connect(self._run_on_gui)
        self._sock = None
        self.host, self.port = host, port
        self._closed = False
        if autostart:
            self.start(host, port)

    def start(self, host: str = "127.0.0.1", port: int = 0) -> int:
        """Bind the loopback socket and begin accepting. Returns the bound port."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.listen(8)
        self.host, self.port = self._sock.getsockname()
        threading.Thread(target=self._accept_loop, name="control-accept", daemon=True).start()
        self._write_info()
        return self.port

    # --- lifecycle ---------------------------------------------------------

    def _write_info(self):
        try:
            INFO_PATH.parent.mkdir(parents=True, exist_ok=True)
            INFO_PATH.write_text(json.dumps(
                {"host": self.host, "port": self.port, "token": self.token}))
            INFO_PATH.chmod(0o600)                      # token is a credential
        except OSError:
            pass

    def close(self):
        self._closed = True
        try:
            self._sock.close()
        except OSError:
            pass
        try:
            if INFO_PATH.exists():
                INFO_PATH.unlink()
        except OSError:
            pass

    # --- socket side (background threads) ----------------------------------

    def _accept_loop(self):
        while not self._closed:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            threading.Thread(target=self._serve, args=(conn,),
                             name="control-conn", daemon=True).start()

    def _serve(self, conn: socket.socket):
        with conn, conn.makefile("rwb") as f:
            for raw in f:
                try:
                    req = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    self._write(f, {"ok": False, "error": "invalid JSON"})
                    continue
                if not secrets.compare_digest(str(req.get("token", "")), self.token):
                    self._write(f, {"ok": False, "error": "bad token"})
                    continue
                call = _Call(req)
                self._dispatch.emit(call)               # -> GUI thread
                if not call.done.wait(timeout=120):
                    self._write(f, {"ok": False, "error": "engine timeout"})
                    continue
                self._write(f, call.result)

    @staticmethod
    def _write(f, obj: dict):
        f.write((json.dumps(obj) + "\n").encode("utf-8"))
        f.flush()

    # --- GUI side (main thread) --------------------------------------------

    def _run_on_gui(self, call: _Call):
        try:
            call.result = self._handle(call.req)
        except Exception as e:                           # never kill the GUI thread
            call.result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        finally:
            call.done.set()

    def _notify(self, text: str):
        """Surface agent activity in the UI, if the window supports it."""
        note = getattr(self.window, "note_agent_action", None)
        if callable(note):
            note(text)

    def _handle(self, req: dict) -> dict:
        op = req.get("op")
        ctl = self.window.ctl
        doc = ctl.doc

        if op == "ping":
            return {"ok": True, "result": {"app": "image-editor", "hasDocument": doc is not None}}
        if op == "command_list":
            return {"ok": True, "result": commands.command_list(
                doc, filter=req.get("filter"), enabled_only=bool(req.get("enabled_only")))}
        if op == "doc_inspect":
            if doc is None:
                return {"ok": True, "result": {"document": None}}
            return {"ok": True, "result": commands.run_command(doc, "doc.inspect", {})["result"]}
        if op == "render_preview":
            if doc is None:
                return {"ok": False, "error": "no document"}
            return {"ok": True, "result": commands.run_command(
                doc, "doc.renderPreview", {"max_side": req.get("max_side", 1024)})["result"]}
        if op == "command_run":
            if doc is None:
                return {"ok": False, "error": "no document"}
            res = commands.run_command(doc, req.get("id", ""), req.get("params"))
            self.window.refresh_from_engine()            # repaint the live canvas
            self._notify(_describe_run(res))
            return {"ok": True, "result": res}
        if op == "command_batch":
            if doc is None:
                return {"ok": False, "error": "no document"}
            rep = commands.run_batch(doc, req.get("steps", []),
                                     stop_on_error=req.get("stop_on_error", True))
            self.window.refresh_from_engine()
            self._notify(f"Claude ran {rep['completed']}/{rep['total']} commands")
            return {"ok": True, "result": rep}
        if op == "open":
            ok = self.window.open_path(req.get("path", ""))
            return {"ok": bool(ok), "result": {"opened": bool(ok)}}
        if op == "save":
            if doc is None:
                return {"ok": False, "error": "no document"}
            ok = ctl.save(req.get("path", ""))
            return {"ok": bool(ok), "result": {"saved": bool(ok)}}
        return {"ok": False, "error": f"unknown op: {op}"}
