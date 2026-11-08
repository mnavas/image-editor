"""AgentToast — a transient, non-modal banner announcing what the agent just did.

When the MCP bridge drives the live app, sliders move and the canvas changes on
their own; this is the feedback that tells the user *why*. It floats near the top
of its parent, never takes focus or mouse events, and fades itself out.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QLabel, QWidget


class AgentToast(QLabel):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet(
            "background-color: rgba(30, 74, 30, 235); color: #d8f5d8; "
            "border: 1px solid #3a7a3a; border-radius: 6px; "
            "padding: 8px 14px; font-size: 13px;")
        self.setVisible(False)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, msec: int = 2800, icon: str = "🤖") -> None:
        self.setText(f"{icon}  {text}" if icon else text)
        self.adjustSize()
        self._reposition()
        self.setVisible(True)
        self.raise_()
        self._timer.start(msec)

    def _reposition(self) -> None:
        p = self.parentWidget()
        if p is None:
            return
        x = (p.width() - self.width()) // 2
        self.move(max(8, x), 14)
