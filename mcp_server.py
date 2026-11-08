"""MCP server for Image Editor — drive the editor's engine from Claude.

This is the *headless* half of PhotoCraft's two-mode design (see
~/Code/photocraft/docs/mcp.md): it owns an in-process `core.document.Document`
and exposes the same command registry the Qt UI uses. Nothing here imports Qt, so
the agent and the desktop app run the identical engine.

Tool surface (mirrors PhotoCraft's `command_list` / `command_run` / `command_batch`
/ `doc_inspect` / `render_preview`):

  doc_open        — load an image file as the current document
  doc_save        — render full-resolution and write the result
  command_list    — discover engine ids, params and current enabled state
  command_run     — run one command by id with JSON params
  command_batch   — run an ordered list (NOT atomic; earlier steps stay applied)
  doc_inspect     — layer tree, geometry, history, selection
  render_preview  — a bounded base64 PNG of the composited result

Run standalone (optionally sandbox file access to a folder):
  python mcp_server.py --read-root ~/Pictures --write-root ~/Pictures/out

Register with Claude Code:
  claude mcp add image-editor -- python /path/to/image-editor/mcp_server.py \
      --read-root /work/project --write-root /work/project/out

A client has the full rights of the roots it is given. Prefer a dedicated output
folder as the write root over a whole project.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import img_io
from core.document import Document
from core import commands

from mcp.server.fastmcp import FastMCP

server = FastMCP("image-editor")

# Default location the running desktop app advertises its control port+token
# (mirrors control_server.INFO_PATH).
_CONTROL_INFO = Path.home() / ".cache" / "image-editor" / "control.json"

# Formats OpenCV can encode here — doc_save refuses anything else so an agent can
# never overwrite source code or a .env by pointing an export at it.
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}

# ---------------------------------------------------------------------------
# Session + filesystem authority
# ---------------------------------------------------------------------------

_state: dict = {"doc": None}
_roots: dict = {"read": None, "write": None}
_bridge: dict = {"client": None}            # set in bridge mode -> forward to live app


class BridgeClient:
    """Talks the JSON-lines control protocol to a running image-editor app."""

    def __init__(self, host: str, port: int, token: str):
        self.host, self.port, self.token = host, port, token
        self._conn = None
        self._f = None

    def _connect(self):
        self._conn = socket.create_connection((self.host, self.port), timeout=130)
        self._f = self._conn.makefile("rwb")

    def call(self, op: str, **kw) -> dict:
        req = {"token": self.token, "op": op, **kw}
        for attempt in (1, 2):                  # one reconnect on a dropped socket
            try:
                if self._f is None:
                    self._connect()
                self._f.write((json.dumps(req) + "\n").encode("utf-8"))
                self._f.flush()
                line = self._f.readline()
                if not line:
                    raise ConnectionError("control server closed the connection")
                reply = json.loads(line.decode("utf-8"))
                break
            except (OSError, ValueError):
                self._f = None
                if attempt == 2:
                    raise
        if not reply.get("ok", False):
            raise RuntimeError(reply.get("error", "bridge error"))
        return reply.get("result", {})


def _load_bridge(port: int | None, token: str | None, token_file: str | None) -> BridgeClient:
    """Resolve the live app's control endpoint from flags, else the info file."""
    host = "127.0.0.1"
    if token_file:
        token = Path(token_file).expanduser().read_text().strip()
    if port is None or token is None:
        info = json.loads(_CONTROL_INFO.read_text())    # written by the running app
        host = info.get("host", host)
        port = port if port is not None else int(info["port"])
        token = token if token is not None else info["token"]
    return BridgeClient(host, int(port), token)


def _doc() -> Document:
    doc = _state["doc"]
    if doc is None:
        raise RuntimeError("No document open. Call doc_open first.")
    return doc


def _resolve(path: str, which: str) -> Path:
    """Resolve `path` and, if a root is configured, confine it beneath that root."""
    root = _roots[which]
    p = Path(path).expanduser()
    if root is not None and not p.is_absolute():
        p = root / p
    p = p.resolve()
    if root is not None:
        try:
            p.relative_to(root)
        except ValueError:
            raise PermissionError(f"path escapes the {which} root ({root}): {p}")
    return p


# ---------------------------------------------------------------------------
# File tools
# ---------------------------------------------------------------------------

@server.tool()
def doc_open(path: str) -> dict:
    """Open an image file as the current document (replaces any open document).

    Args:
        path: Path to the image (absolute, or relative to the read root).
    """
    if _bridge["client"]:
        return _bridge["client"].call("open", path=path)
    p = _resolve(path, "read")
    img = img_io.imread(str(p))
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {p}")
    _state["doc"] = Document(base=img)
    return commands.run_command(_state["doc"], "doc.inspect", {})["result"]


@server.tool()
def doc_save(path: str, jpeg_quality: int = 95) -> str:
    """Render the document at full resolution and write it to `path`.

    The format is taken from the extension. Refuses any non-image extension so an
    agent cannot overwrite source files. Writes atomically via a temp file.

    Args:
        path: Destination (absolute, or relative to the write root).
        jpeg_quality: 1..100, used for .jpg/.jpeg/.webp outputs.
    """
    if _bridge["client"]:
        return str(_bridge["client"].call("save", path=path))
    doc = _doc()
    p = _resolve(path, "write")
    suffix = p.suffix.lower()
    if suffix not in _IMAGE_EXT:
        raise ValueError(f"refusing to write a non-image extension: {suffix or '(none)'}")
    img = doc.render(1.0)

    p.parent.mkdir(parents=True, exist_ok=True)
    params = None
    if suffix in (".jpg", ".jpeg"):
        import cv2
        params = [cv2.IMWRITE_JPEG_QUALITY, max(1, min(100, int(jpeg_quality)))]
    elif suffix == ".webp":
        import cv2
        params = [cv2.IMWRITE_WEBP_QUALITY, max(1, min(100, int(jpeg_quality)))]

    tmp_fd, tmp_name = tempfile.mkstemp(suffix=suffix, dir=p.parent)
    os.close(tmp_fd)
    if not img_io.imwrite(tmp_name, img, params):
        Path(tmp_name).unlink(missing_ok=True)
        raise RuntimeError(f"Could not encode the image for extension: {suffix}")
    shutil.move(tmp_name, str(p))
    return f"Saved {img.shape[1]}x{img.shape[0]} to {p}"


# ---------------------------------------------------------------------------
# Engine tools (thin pass-through to the shared command registry)
# ---------------------------------------------------------------------------

@server.tool()
def command_list(filter: str | None = None, enabled_only: bool = False) -> list:
    """Discover engine commands: ids, labels, params and current enabled state.

    Args:
        filter: Keep only commands whose id or label contains this text.
        enabled_only: Keep only commands runnable in the current state.
    """
    if _bridge["client"]:
        return _bridge["client"].call("command_list", filter=filter, enabled_only=enabled_only)
    return commands.command_list(_state["doc"], filter=filter, enabled_only=enabled_only)


@server.tool()
def command_run(id: str, params: dict | None = None) -> dict:
    """Run one engine command by id. Returns {id, ok, result} or {id, ok, error}.

    Discover ids and their params with command_list. Undoable edits can be reverted
    with command_run("edit.undo").

    Args:
        id: Command id, e.g. "adjust.apply", "image.rotate", "layer.setOpacity".
        params: Command-specific parameters (see command_list).
    """
    if _bridge["client"]:
        return _bridge["client"].call("command_run", id=id, params=params)
    return commands.run_command(_doc(), id, params)


@server.tool()
def command_batch(steps: list, stop_on_error: bool = True) -> dict:
    """Run an ordered list of commands. NOT atomic: earlier successes stay applied.

    Args:
        steps: [{"id": ..., "params": {...}}, ...] in order.
        stop_on_error: Stop at the first failure (default true).
    """
    if _bridge["client"]:
        return _bridge["client"].call("command_batch", steps=steps, stop_on_error=stop_on_error)
    return commands.run_batch(_doc(), steps, stop_on_error=stop_on_error)


@server.tool()
def doc_inspect() -> dict:
    """Return the document's geometry, layer tree, selection and history depth."""
    if _bridge["client"]:
        return _bridge["client"].call("doc_inspect")
    return commands.run_command(_doc(), "doc.inspect", {})["result"]


@server.tool()
def render_preview(max_side: int = 1024) -> dict:
    """Return a bounded PNG (base64) of the composited result, for the agent to see.

    Args:
        max_side: Longest side of the returned PNG (<= 2048).
    """
    if _bridge["client"]:
        return _bridge["client"].call("render_preview", max_side=max_side)
    return commands.run_command(_doc(), "doc.renderPreview", {"max_side": max_side})["result"]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_args(argv):
    ap = argparse.ArgumentParser(description="Image Editor MCP server.")
    ap.add_argument("--read-root", default=os.environ.get("IMAGE_EDITOR_READ_ROOT"))
    ap.add_argument("--write-root", default=os.environ.get("IMAGE_EDITOR_WRITE_ROOT"))
    # Bridge mode: forward tools to a running desktop app instead of a headless doc.
    ap.add_argument("--bridge", action="store_true",
                    help="drive the live desktop app (reads ~/.cache/image-editor/control.json)")
    ap.add_argument("--control-port", type=int,
                    default=os.environ.get("IMAGE_EDITOR_CONTROL_PORT"))
    ap.add_argument("--control-token", default=os.environ.get("IMAGE_EDITOR_CONTROL_TOKEN"))
    ap.add_argument("--control-token-file",
                    default=os.environ.get("IMAGE_EDITOR_CONTROL_TOKEN_FILE"))
    return ap.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    if args.bridge:
        # In bridge mode the desktop app owns filesystem authority; root flags here
        # would be misleading, so reject them (as PhotoCraft does).
        if args.read_root or args.write_root:
            raise SystemExit("--read-root/--write-root are not used with --bridge "
                             "(configure roots on the desktop app)")
        _bridge["client"] = _load_bridge(args.control_port, args.control_token,
                                         args.control_token_file)
    else:
        if args.read_root:
            _roots["read"] = Path(args.read_root).expanduser().resolve()
        if args.write_root:
            _roots["write"] = Path(args.write_root).expanduser().resolve()
    server.run()


if __name__ == "__main__":
    main()
