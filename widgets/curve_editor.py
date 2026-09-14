"""CurveEditor — a draggable tone-curve widget (master + per-channel R/G/B).

Emits `changed` whenever the curve is edited. `get_all()` returns the control
points per channel (or None for an untouched identity channel), ready to pass to
core.curves. Uses the same monotone spline for its own preview line, so what you
draw is exactly what the pipeline applies.
"""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from core.curves import _pchip_lut

_IDENT = [(0.0, 0.0), (255.0, 255.0)]
_CH_COLORS = {"master": QColor(230, 230, 230), "r": QColor(235, 90, 90),
              "g": QColor(90, 210, 110), "b": QColor(110, 150, 240)}


class CurveEditor(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(240, 240)
        self._pts = {ch: list(_IDENT) for ch in ("master", "r", "g", "b")}
        self._channel = "master"
        self._drag = None          # index of point being dragged
        self._m = 10               # margin px

    # --- public API --------------------------------------------------------

    def set_channel(self, ch: str):
        self._channel = ch
        self.update()

    def reset(self):
        self._pts = {ch: list(_IDENT) for ch in ("master", "r", "g", "b")}
        self.update()
        self.changed.emit()

    def get_all(self) -> dict:
        out = {}
        for ch, pts in self._pts.items():
            out[ch] = None if pts == _IDENT else list(pts)
        return out

    def set_all(self, curves: dict):
        """Load control points per channel (None/absent = identity)."""
        for ch in ("master", "r", "g", "b"):
            pts = curves.get(ch)
            self._pts[ch] = [tuple(p) for p in pts] if pts else list(_IDENT)
        self.update()

    # --- coordinate mapping ------------------------------------------------

    def _plot_rect(self) -> QRectF:
        m = self._m
        return QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)

    def _to_px(self, x, y):
        r = self._plot_rect()
        return QPointF(r.x() + x / 255.0 * r.width(),
                       r.y() + (1.0 - y / 255.0) * r.height())

    def _to_val(self, px, py):
        r = self._plot_rect()
        x = (px - r.x()) / r.width() * 255.0
        y = (1.0 - (py - r.y()) / r.height()) * 255.0
        return max(0.0, min(255.0, x)), max(0.0, min(255.0, y))

    # --- painting ----------------------------------------------------------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self._plot_rect()
        p.fillRect(self.rect(), QColor(30, 30, 30))
        p.setPen(QPen(QColor(70, 70, 70), 1))
        for i in range(1, 4):                        # grid
            p.drawLine(QPointF(r.x() + i / 4 * r.width(), r.y()),
                       QPointF(r.x() + i / 4 * r.width(), r.bottom()))
            p.drawLine(QPointF(r.x(), r.y() + i / 4 * r.height()),
                       QPointF(r.right(), r.y() + i / 4 * r.height()))
        p.setPen(QPen(QColor(90, 90, 90), 1, Qt.PenStyle.DashLine))
        p.drawLine(self._to_px(0, 0), self._to_px(255, 255))

        pts = self._pts[self._channel]
        lut = _pchip_lut(pts)
        color = _CH_COLORS[self._channel]
        p.setPen(QPen(color, 2))
        prev = None
        for x in range(256):
            cur = self._to_px(x, float(lut[x]))
            if prev is not None:
                p.drawLine(prev, cur)
            prev = cur
        p.setBrush(color)
        p.setPen(QPen(QColor(20, 20, 20), 1))
        for (x, y) in pts:
            c = self._to_px(x, y)
            p.drawEllipse(c, 5, 5)

    # --- interaction -------------------------------------------------------

    def _hit(self, pos):
        for i, (x, y) in enumerate(self._pts[self._channel]):
            if (self._to_px(x, y) - pos).manhattanLength() < 12:
                return i
        return None

    def mousePressEvent(self, event):
        pts = self._pts[self._channel]
        i = self._hit(QPointF(event.position()))
        if event.button() == Qt.MouseButton.RightButton:
            if i is not None and 0 < i < len(pts) - 1:   # can't delete endpoints
                del pts[i]
                self.update()
                self.changed.emit()
            return
        if i is None:                                    # add a new point
            x, y = self._to_val(event.position().x(), event.position().y())
            pts.append((x, y))
            pts.sort(key=lambda pt: pt[0])
            i = pts.index(next(pt for pt in pts if pt[0] == x))
        self._drag = i
        self.update()

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        pts = self._pts[self._channel]
        x, y = self._to_val(event.position().x(), event.position().y())
        # endpoints keep their x; middle points stay strictly between neighbours
        if self._drag == 0:
            x = 0.0
        elif self._drag == len(pts) - 1:
            x = 255.0
        else:
            lo = pts[self._drag - 1][0] + 1
            hi = pts[self._drag + 1][0] - 1
            x = max(lo, min(hi, x))
        pts[self._drag] = (x, y)
        self.update()
        self.changed.emit()

    def mouseReleaseEvent(self, event):
        self._drag = None
