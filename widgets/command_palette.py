"""Command palette — a fuzzy-searchable launcher over the command registry.

Ctrl+K opens it. It lists every registry command with its menu path, shortcut and
*current* enabled-state (disabled ones are greyed, with the reason as a tooltip),
filters as you type, and hands the chosen id back to the host's own runner — the
same path a menu click takes, so params dialogs and history behave identically.

It is registry-driven: it shows whatever `entries` it is handed (the output of
commands.command_list), so a new command appears here the moment it is registered.
The `params_dialog` helper lives here too, so a host with no dialog code of its
own can still run commands that take parameters.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QLineEdit, QListWidget, QListWidgetItem, QSpinBox, QVBoxLayout,
)


def _score(needle: str, e: dict) -> int | None:
    """Rank a command against the query; None means "no match" (hidden).

    Higher is better. A substring hit in the id or label beats a scattered
    subsequence match, so "rotate" surfaces image.rotate above commands that
    merely happen to contain r…o…t…a…t…e in order.
    """
    idl = e["id"].lower()
    label = e["label"].lower()
    hay = f"{idl} {label} {' '.join(m.lower() for m in e.get('menu', []))}"
    if needle in label:
        return 100 - label.index(needle)
    if needle in idl:
        return 80 - idl.index(needle)
    if _subseq(needle, hay):
        return 10
    return None


def _subseq(needle: str, hay: str) -> bool:
    """Fuzzy: every char of `needle` appears in `hay`, in order."""
    it = iter(hay)
    return all(ch in it for ch in needle)


class CommandPalette(QDialog):
    def __init__(self, parent, entries, on_choose):
        """entries: list of dicts from commands.command_list (id/label/menu/
        shortcut/enabled/disabledReason). on_choose: callable(command_id)."""
        super().__init__(parent)
        self._entries = list(entries)
        self._on_choose = on_choose
        self.setWindowTitle("Commands")
        self.setModal(True)
        self.resize(480, 380)

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search commands…   (↑↓ move · Enter run · Esc close)")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._repopulate)
        self._search.installEventFilter(self)       # route ↑↓/Enter to the list
        v.addWidget(self._search)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.itemActivated.connect(lambda _it: self._run_current())
        v.addWidget(self._list, 1)

        self._repopulate("")
        self._search.setFocus()

    # --- filtering ---------------------------------------------------------

    def _repopulate(self, text: str) -> None:
        q = "".join(text.split()).lower()
        self._list.clear()
        if q:
            scored = [(s, e) for e in self._entries
                      if (s := _score(q, e)) is not None]
            scored.sort(key=lambda se: -se[0])        # best match first; stable within
            matches = [e for _s, e in scored]
        else:
            matches = self._entries
        for e in matches:
            it = QListWidgetItem(self._format(e))
            it.setData(Qt.ItemDataRole.UserRole, e["id"])
            if not e.get("enabled", True):
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                it.setToolTip(e.get("disabledReason") or "unavailable")
            self._list.addItem(it)
        self._select_first_enabled()

    def _select_first_enabled(self) -> None:
        for i in range(self._list.count()):
            if self._list.item(i).flags() & Qt.ItemFlag.ItemIsEnabled:
                self._list.setCurrentRow(i)
                return

    @staticmethod
    def _format(e: dict) -> str:
        menu = " › ".join(e.get("menu", []))
        prefix = f"{menu} › " if menu else ""
        shortcut = f"    [{e['shortcut']}]" if e.get("shortcut") else ""
        reason = "" if e.get("enabled", True) else f"   — {e.get('disabledReason', '')}"
        return f"{prefix}{e['label']}{shortcut}{reason}"

    # --- keyboard ----------------------------------------------------------

    def eventFilter(self, obj, event):
        if obj is self._search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self._move(1 if key == Qt.Key.Key_Down else -1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._run_current()
                return True
        return super().eventFilter(obj, event)

    def _move(self, step: int) -> None:
        n = self._list.count()
        if not n:
            return
        row = self._list.currentRow()
        for _ in range(n):                           # skip disabled rows
            row = (row + step) % n
            if self._list.item(row).flags() & Qt.ItemFlag.ItemIsEnabled:
                self._list.setCurrentRow(row)
                return

    def _run_current(self) -> None:
        it = self._list.currentItem()
        if it is None or not (it.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        cid = it.data(Qt.ItemDataRole.UserRole)
        self.accept()
        self._on_choose(cid)


def params_dialog(parent, spec) -> dict | None:
    """Build an input dialog from a command's `params` schema; values or None.

    The widget for each field follows its declared type, so the same
    agent-readable schema that documents the command for Claude also lays out the
    human form — no per-command dialog code.
    """
    if not spec.params:
        return {}
    dlg = QDialog(parent)
    dlg.setWindowTitle(spec.label)
    form = QFormLayout(dlg)
    getters = {}
    for name, meta in spec.params.items():
        meta = meta or {}
        kind = meta.get("type", "float")
        if kind == "enum":
            w = QComboBox()
            values = meta.get("values")
            if values is None and meta.get("values_fn"):     # late-bound value list
                values = _resolve_values(meta["values_fn"])
            w.addItems([str(v) for v in (values or [])])
            if meta.get("default") is not None:
                w.setCurrentText(str(meta["default"]))
            getters[name] = w.currentText
        elif kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(meta.get("default", False)))
            getters[name] = w.isChecked
        elif kind == "int":
            w = QSpinBox()
            w.setRange(-100000, 100000)
            w.setValue(int(meta.get("default", 0)))
            getters[name] = w.value
        elif kind == "float":
            w = QDoubleSpinBox()
            lo, hi = (meta.get("range") or [-1000, 1000])[:2]
            w.setRange(float(lo), float(hi))
            w.setDecimals(2)
            w.setValue(float(meta.get("default", 0.0)))
            getters[name] = w.value
        else:
            w = QLineEdit(str(meta.get("default", "")))
            getters[name] = w.text
        if meta.get("doc"):
            w.setToolTip(meta["doc"])
        form.addRow(f"{name}:", w)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    form.addRow(buttons)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return {name: get() for name, get in getters.items()}


def _resolve_values(name: str) -> list:
    """Resolve a late-bound enum value list referenced by name in a param schema."""
    try:
        import commands as _cmd                     # image_selector flat layout
    except ImportError:
        from core import commands as _cmd           # image-editor package layout
    if name == "filters" and hasattr(_cmd, "_filter_names"):
        return _cmd._filter_names()
    return []
