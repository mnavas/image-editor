"""Live-preview params flow (image-editor).

A param command previews on the canvas as the dialog's values change, then
commits one history step on OK (or none on Cancel) — the live trials must not
pile up undo entries. We drive the flow by faking the modal dialog so it fires
`on_change` a few times (the live preview) and then returns OK/Cancel.

Run: QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

import widgets.main_window as MW
from config import Config
from core import commands


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _window_with_image(app):
    win = MW.MainWindow(Config.load())
    path = os.path.join(tempfile.mkdtemp(), "t.png")
    cv2.imwrite(path, np.full((40, 60, 3), 120, np.uint8))
    assert win.open_path(path)
    return win


def test_preview_trials_collapse_to_one_commit(app, monkeypatch):
    win = _window_with_image(app)
    doc = win.ctl.doc
    before = len(doc.layers)

    def fake_dialog(parent, spec, on_change=None):
        if on_change:                       # three live previews
            on_change({"exposure": 0.5})
            on_change({"exposure": 1.0})
            on_change({"exposure": 1.5})
        return {"exposure": 1.5}            # OK

    monkeypatch.setattr(MW, "_params_dialog", fake_dialog)
    win._run_menu_command(commands.REGISTRY["adjust.apply"])
    assert len(doc.layers) == before + 1   # one adjustment layer, not three
    assert len(doc._undo) == 1             # one undo step


def test_preview_cancel_leaves_no_change(app, monkeypatch):
    win = _window_with_image(app)
    doc = win.ctl.doc
    before = len(doc.layers)

    def fake_cancel(parent, spec, on_change=None):
        if on_change:
            on_change({"exposure": 2.0})
            on_change({"exposure": 2.5})
        return None                         # Cancel

    monkeypatch.setattr(MW, "_params_dialog", fake_cancel)
    win._run_menu_command(commands.REGISTRY["adjust.apply"])
    assert len(doc.layers) == before        # trials were reverted
