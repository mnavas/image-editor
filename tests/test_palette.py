"""Command palette + agent toast tests (image-editor).

Run: QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget

from core import commands
from core.document import Document
from widgets.agent_toast import AgentToast
from widgets.command_palette import CommandPalette


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _doc():
    return Document(np.full((40, 60, 3), 120, np.uint8))


def _rows(pal):
    return [pal._list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(pal._list.count())]


def test_palette_lists_registry_commands(app):
    pal = CommandPalette(None, commands.command_list(_doc()), on_choose=lambda cid: None)
    assert "image.rotate" in _rows(pal)
    assert "edit.undo" in _rows(pal)


def test_substring_match_ranks_first(app):
    pal = CommandPalette(None, commands.command_list(_doc()), on_choose=lambda cid: None)
    pal._repopulate("rotate")
    # image.rotate (label substring) must be the first/selected row, not a
    # scattered subsequence like layer.setOpacity
    assert _rows(pal)[0] == "image.rotate"
    assert pal._list.currentRow() == 0


def test_enter_runs_selected_command(app):
    chosen = {}
    pal = CommandPalette(None, commands.command_list(_doc()),
                         on_choose=lambda cid: chosen.setdefault("id", cid))
    pal._repopulate("rotate")                    # rotate is enabled in a fresh doc
    pal._run_current()
    assert chosen["id"] == "image.rotate"


def test_disabled_command_does_not_run(app):
    # edit.undo is disabled in a fresh doc; activating it must be a no-op.
    chosen = {}
    pal = CommandPalette(None, commands.command_list(_doc()),
                         on_choose=lambda cid: chosen.setdefault("id", cid))
    pal._repopulate("undo")
    pal._run_current()
    assert chosen == {}


def test_disabled_command_is_greyed_with_reason(app):
    # clearCrop is disabled when no crop is set — it should be non-selectable and
    # carry its reason as a tooltip.
    pal = CommandPalette(None, commands.command_list(_doc()), on_choose=lambda cid: None)
    pal._repopulate("clear crop")
    it = pal._list.item(0)
    assert not (it.flags() & Qt.ItemFlag.ItemIsEnabled)
    assert "crop" in it.toolTip().lower()


def test_agent_toast_sets_text(app):
    host = QWidget()
    host.resize(640, 480)
    toast = AgentToast(host)
    toast.show_message("Claude: Rotate")
    assert "Rotate" in toast.text()
