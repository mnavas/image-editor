"""Command registry — one self-describing table that drives the UI *and* agents.

Modelled on PhotoCraft (ArtCraft's Rust editor): "every action is a command", so
the same engine is reachable from the Qt UI, a CLI, or an MCP server. Each command
is a `CommandSpec` with an id, an agent-readable parameter schema, an `enabled`
predicate (can it run in the current state?), and a `run(doc, params) -> result`.

Zero Qt imports: this binds to a `core.document.Document` and nothing else, so it
can back a headless/MCP process unchanged. The three entry points mirror the
PhotoCraft MCP tool surface:

    command_list(doc)            -> discover ids, params and current enabled state
    run_command(doc, id, params) -> run one command
    run_batch(doc, steps)        -> run an ordered list (not an atomic transaction)

History: a command that mutates is responsible for recording its own undo step
(via ``doc.push_history()`` or ``doc.add_layer()``), exactly as the existing code
does. ``journal`` is honest metadata for the command list, not a hidden push.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any, Callable

import cv2

from .document import Document
from .layers import Layer
from . import ops

# ---------------------------------------------------------------------------
# Spec + registry
# ---------------------------------------------------------------------------

# value-based adjustment ops: all take a single scalar. exposure's arg is "stops",
# every other op's arg is "value" (matches AppController._recipe).
ADJUST_KEYS = [
    "exposure", "brightness", "contrast", "saturation", "vibrance",
    "temperature", "tint", "shadows", "highlights",
    "clarity", "texture", "sharpen", "dehaze", "vignette", "grain",
]


@dataclass
class CommandSpec:
    id: str                                             # e.g. "image.rotate"
    label: str                                          # human-facing
    run: Callable[[Document, dict], Any]                # JSON-able params -> JSON-able result
    params: dict = field(default_factory=dict)          # {name: {"type","doc",...}} — agent-readable
    menu: tuple = ()                                     # e.g. ("Image", "Rotate") for UI generation
    shortcut: str = ""                                   # Qt key sequence, e.g. "Ctrl+Z"
    enabled: Callable[[Document], bool] = lambda d: True
    disabled_reason: Callable[[Document], str] = lambda d: ""
    journal: bool = False                               # does a successful run add a history entry?
    query: bool = False                                 # read-only + idempotent (safe to retry)


REGISTRY: dict[str, CommandSpec] = {}


def register(spec: CommandSpec) -> CommandSpec:
    if spec.id in REGISTRY:
        raise ValueError(f"duplicate command id: {spec.id}")
    REGISTRY[spec.id] = spec
    return spec


# ---------------------------------------------------------------------------
# Entry points (mirror the PhotoCraft MCP tools)
# ---------------------------------------------------------------------------

def command_list(doc: Document | None, filter: str | None = None,
                 enabled_only: bool = False) -> list[dict]:
    """Discover commands: ids, params and *current* enabled state. Like `command_list`."""
    out = []
    for spec in REGISTRY.values():
        if filter and filter not in spec.id and filter not in spec.label.lower():
            continue
        ok = doc is not None and spec.enabled(doc)
        if enabled_only and not ok:
            continue
        out.append({
            "id": spec.id,
            "label": spec.label,
            "menu": list(spec.menu),
            "shortcut": spec.shortcut,
            "params": spec.params,
            "enabled": ok,
            "disabledReason": "" if ok else (
                "no document" if doc is None else spec.disabled_reason(doc)),
            "journal": spec.journal,
            "query": spec.query,
        })
    return out


def run_command(doc: Document, id: str, params: dict | None = None) -> dict:
    """Run one command by id. Returns an envelope: {id, ok, result} | {id, ok, error}."""
    spec = REGISTRY.get(id)
    if spec is None:
        return {"id": id, "ok": False, "error": f"unknown command: {id}"}
    if doc is None:
        return {"id": id, "ok": False, "error": "no document"}
    if not spec.enabled(doc):
        return {"id": id, "ok": False, "error": spec.disabled_reason(doc) or "disabled"}
    try:
        result = spec.run(doc, params or {})
        return {"id": id, "ok": True, "result": result}
    except Exception as e:                                # surface, don't crash the host
        return {"id": id, "ok": False, "error": f"{type(e).__name__}: {e}"}


def run_batch(doc: Document, steps: list[dict], stop_on_error: bool = True) -> dict:
    """Run ordered steps [{id, params}]. NOT atomic: earlier successes stay applied.

    Faithful to PhotoCraft's `command_batch` — no rollback; inspect history to recover.
    """
    results, completed = [], 0
    for step in steps:
        res = run_command(doc, step.get("id", ""), step.get("params"))
        results.append(res)
        if res["ok"]:
            completed += 1
        elif stop_on_error:
            break
    return {"completed": completed, "total": len(steps), "results": results}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _num(params: dict, key: str, default: float = 0.0) -> float:
    v = params.get(key, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ValueError(f"`{key}` must be a number")


def _int(params: dict, key: str) -> int:
    if key not in params:
        raise ValueError(f"`{key}` is required")
    try:
        return int(params[key])
    except (TypeError, ValueError):
        raise ValueError(f"`{key}` must be an integer")


def _layer_at(doc: Document, params: dict) -> Layer:
    i = _int(params, "index")
    if not (0 <= i < len(doc.layers)):
        raise ValueError(f"layer index {i} out of range (0..{len(doc.layers) - 1})")
    return doc.layers[i]


def _rotate_rect_cw(rect):
    """Rotate a normalised crop rect 90° clockwise (mirror of AppController)."""
    x, y, w, h = rect
    return (1.0 - y - h, x, h, w)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

# -- queries ----------------------------------------------------------------

def _run_inspect(doc: Document, _p: dict) -> dict:
    h, w = doc.base.shape[:2]
    return {
        "size": {"width": int(w), "height": int(h)},
        "rotation": doc.rotation,
        "crop": doc.crop_rect,
        "layers": [
            {"index": i, "kind": l.kind, "name": l.name,
             "visible": l.visible, "opacity": round(float(l.opacity), 3),
             "blend": l.blend_mode, "hasMask": l.mask is not None and not l.mask.is_empty()}
            for i, l in enumerate(doc.layers)
        ],
        "history": {"undo": len(doc._undo), "redo": len(doc._redo)},
    }


register(CommandSpec(
    id="doc.inspect", label="Inspect Document", menu=(), query=True, run=_run_inspect,
    params={}, ))


def _run_preview(doc: Document, p: dict) -> dict:
    """Bounded PNG of the composited result, base64 — the agent's image round-trip."""
    max_side = int(p.get("max_side", 1024))
    max_side = max(16, min(max_side, 2048))
    scale = doc.proxy_scale(max_side)
    img = doc.render(scale)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG encode failed")
    h, w = img.shape[:2]
    return {"format": "png", "width": int(w), "height": int(h),
            "base64": base64.b64encode(buf.tobytes()).decode("ascii")}


register(CommandSpec(
    id="doc.renderPreview", label="Render Preview", query=True, run=_run_preview,
    params={"max_side": {"type": "int", "default": 1024, "max": 2048,
                         "doc": "longest side of the returned PNG"}}, ))


register(CommandSpec(
    id="layer.list", label="List Layers", query=True,
    run=lambda d, _p: _run_inspect(d, _p)["layers"], params={}))


# -- history ----------------------------------------------------------------

register(CommandSpec(
    id="edit.undo", label="Undo", menu=("Edit",), shortcut="Ctrl+Z", journal=False,
    enabled=lambda d: len(d._undo) > 0, disabled_reason=lambda d: "nothing to undo",
    run=lambda d, _p: {"undone": d.undo()}, params={}))

register(CommandSpec(
    id="edit.redo", label="Redo", menu=("Edit",), shortcut="Ctrl+Shift+Z", journal=False,
    enabled=lambda d: len(d._redo) > 0, disabled_reason=lambda d: "nothing to redo",
    run=lambda d, _p: {"redone": d.redo()}, params={}))


# -- geometry ---------------------------------------------------------------

def _run_rotate(doc: Document, p: dict) -> dict:
    direction = str(p.get("direction", "cw")).lower()
    if direction not in ("cw", "ccw"):
        raise ValueError("`direction` must be 'cw' or 'ccw'")
    doc.push_history()
    step = 90 if direction == "cw" else 270
    doc.rotation = (doc.rotation + step) % 360
    if doc.crop_rect is not None:
        r = doc.crop_rect
        # rotating CCW is three CW turns of the crop rect
        for _ in range(1 if direction == "cw" else 3):
            r = _rotate_rect_cw(r)
        doc.crop_rect = r
    return {"rotation": doc.rotation}


register(CommandSpec(
    id="image.rotate", label="Rotate", menu=("Image", "Rotate"), journal=True,
    run=_run_rotate,
    params={"direction": {"type": "enum", "values": ["cw", "ccw"], "default": "cw"}}, ))


def _run_set_crop(doc: Document, p: dict) -> dict:
    x, y, w, h = (_num(p, "x"), _num(p, "y"), _num(p, "w"), _num(p, "h"))
    if w <= 0 or h <= 0:
        raise ValueError("`w` and `h` must be > 0")
    doc.push_history()
    doc.crop_rect = (x, y, w, h)
    return {"crop": doc.crop_rect}


register(CommandSpec(
    id="image.setCrop", label="Crop", menu=("Image", "Crop"), journal=True,
    run=_run_set_crop,
    params={k: {"type": "float", "doc": "normalised 0..1, post-rotation"}
            for k in ("x", "y", "w", "h")}, ))


def _run_clear_crop(doc: Document, _p: dict) -> dict:
    doc.push_history()
    doc.crop_rect = None
    return {"crop": None}


register(CommandSpec(
    id="image.clearCrop", label="Clear Crop", menu=("Image",), journal=True,
    enabled=lambda d: d.crop_rect is not None, disabled_reason=lambda d: "no crop set",
    run=_run_clear_crop, params={}))


# -- adjustments (non-destructive: adds a whole-image adjustment layer) ------

def _run_adjust_apply(doc: Document, p: dict) -> dict:
    """Add a whole-image adjustment layer from scalar params (exposure, contrast, …).

    A global adjustment is just a maskless `adjust_set` layer — the exact model the
    UI's local edits already use, so it round-trips through .iedit unchanged.
    """
    recipe = []
    unknown = [k for k in p if k not in ADJUST_KEYS]
    if unknown:
        raise ValueError(f"unknown adjustment(s): {', '.join(unknown)}; "
                         f"supported: {', '.join(ADJUST_KEYS)}")
    for k in ADJUST_KEYS:
        if k in p and _num(p, k) != 0.0:
            arg = "stops" if k == "exposure" else "value"
            recipe.append((k, {arg: _num(p, k)}))
    if not recipe:
        raise ValueError("no non-zero adjustments given")
    name = p.get("name") or "Adjust"
    layer = doc.add_layer(Layer(kind="adjust_set", name=str(name),
                                params={"recipe": recipe}))
    return {"added": True, "name": layer.name, "steps": len(recipe),
            "index": len(doc.layers) - 1}


register(CommandSpec(
    id="adjust.apply", label="Apply Adjustment", menu=("Image", "Adjustments"),
    journal=True, run=_run_adjust_apply,
    params={k: {"type": "float", "doc": "amount; 0 = skip"} for k in ADJUST_KEYS}, ))


# -- layer management -------------------------------------------------------

def _run_layer_visible(doc: Document, p: dict) -> dict:
    layer = _layer_at(doc, p)
    doc.push_history()
    layer.visible = bool(p.get("visible", True))
    return {"index": _int(p, "index"), "visible": layer.visible}


register(CommandSpec(
    id="layer.setVisible", label="Toggle Layer", menu=("Layer",), journal=True,
    enabled=lambda d: len(d.layers) > 0, disabled_reason=lambda d: "no layers",
    run=_run_layer_visible,
    params={"index": {"type": "int"}, "visible": {"type": "bool", "default": True}}, ))


def _run_layer_opacity(doc: Document, p: dict) -> dict:
    layer = _layer_at(doc, p)
    doc.push_history()
    layer.opacity = max(0.0, min(1.0, _num(p, "opacity", 1.0)))
    return {"index": _int(p, "index"), "opacity": layer.opacity}


register(CommandSpec(
    id="layer.setOpacity", label="Layer Opacity", menu=("Layer",), journal=True,
    enabled=lambda d: len(d.layers) > 0, disabled_reason=lambda d: "no layers",
    run=_run_layer_opacity,
    params={"index": {"type": "int"}, "opacity": {"type": "float", "range": [0, 1]}}, ))


def _run_layer_remove(doc: Document, p: dict) -> dict:
    layer = _layer_at(doc, p)
    doc.remove_layer(layer)                              # pushes history itself
    return {"removed": True, "remaining": len(doc.layers)}


register(CommandSpec(
    id="layer.remove", label="Delete Layer", menu=("Layer",), journal=True,
    enabled=lambda d: len(d.layers) > 0, disabled_reason=lambda d: "no layers",
    run=_run_layer_remove, params={"index": {"type": "int"}}, ))
