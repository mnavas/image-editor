"""Command-registry tests — pure arrays, no Qt. Run: .venv/bin/python -m pytest tests"""
import base64
import numpy as np
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.document import Document
from core import commands


def _doc(h=64, w=96):
    rng = np.random.default_rng(0)
    return Document(base=rng.integers(0, 256, (h, w, 3), dtype=np.uint8))


def test_command_list_is_self_describing():
    doc = _doc()
    listing = commands.command_list(doc)
    ids = {c["id"] for c in listing}
    assert {"doc.inspect", "adjust.apply", "image.rotate", "edit.undo"} <= ids
    # every command advertises params + enabled state (the agent-readable contract)
    for c in listing:
        assert "params" in c and "enabled" in c and "journal" in c


def test_enabled_predicate_reflects_state():
    doc = _doc()
    # nothing to undo, no crop set yet
    by_id = {c["id"]: c for c in commands.command_list(doc)}
    assert by_id["edit.undo"]["enabled"] is False
    assert by_id["image.clearCrop"]["enabled"] is False
    commands.run_command(doc, "image.setCrop", {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5})
    by_id = {c["id"]: c for c in commands.command_list(doc)}
    assert by_id["edit.undo"]["enabled"] is True        # the crop is undoable
    assert by_id["image.clearCrop"]["enabled"] is True


def test_adjust_apply_adds_layer_and_changes_render():
    doc = _doc()
    before = doc.render(1.0).copy()
    res = commands.run_command(doc, "adjust.apply", {"exposure": 1.0, "contrast": 40})
    assert res["ok"] and res["result"]["steps"] == 2
    assert len(doc.layers) == 1
    assert not np.array_equal(before, doc.render(1.0))  # the look actually changed


def test_adjust_apply_rejects_unknown_key():
    doc = _doc()
    res = commands.run_command(doc, "adjust.apply", {"sharpness": 10})
    assert not res["ok"] and "unknown" in res["error"]


def test_undo_restores_previous_state():
    doc = _doc()
    commands.run_command(doc, "adjust.apply", {"saturation": 50})
    assert len(doc.layers) == 1
    assert commands.run_command(doc, "edit.undo", {})["result"]["undone"] is True
    assert len(doc.layers) == 0


def test_render_preview_round_trips_png():
    doc = _doc(h=400, w=600)
    res = commands.run_command(doc, "doc.renderPreview", {"max_side": 128})
    assert res["ok"]
    out = res["result"]
    assert out["format"] == "png" and max(out["width"], out["height"]) == 128
    assert len(base64.b64decode(out["base64"])) > 0


def test_batch_is_not_atomic():
    doc = _doc()
    steps = [
        {"id": "adjust.apply", "params": {"exposure": 0.5}},   # ok
        {"id": "adjust.apply", "params": {"bogus": 1}},        # fails
        {"id": "adjust.apply", "params": {"contrast": 20}},    # not reached
    ]
    report = commands.run_batch(doc, steps, stop_on_error=True)
    assert report["completed"] == 1
    assert len(doc.layers) == 1            # the first success stays applied — no rollback


def test_unknown_command_is_an_error_not_a_crash():
    doc = _doc()
    res = commands.run_command(doc, "does.notExist", {})
    assert not res["ok"] and "unknown command" in res["error"]
