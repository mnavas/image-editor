"""Canvas — zoom/pan image preview with an optional brush overlay.

Ported from image_selector/preview_widget.py (QPainter zoom/pan), extended so a
tool can paint a brush mask directly on the image. Brush points are reported to
the controller in NORMALISED image coordinates so they survive zoom/pan and the
proxy→full-res transition.
"""
from __future__ import annotations

import cv2
import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QWidget


def ndarray_to_pixmap(img: np.ndarray) -> QPixmap:
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    rgb = np.ascontiguousarray(rgb)
    h, w, ch = rgb.shape
    qi = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qi.copy())


class Canvas(QWidget):
    # normalised (x,y) in [0,1] of the displayed image, and stroke lifecycle
    brush_moved = pyqtSignal(float, float)
    brush_started = pyqtSignal(float, float)
    brush_ended = pyqtSignal()
    warp_dragged = pyqtSignal(float, float, float, float)   # x0,y0 -> x1,y1 (normalised)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._pixmap: QPixmap | None = None
        self._overlay: QPixmap | None = None   # faint tint, only while brushing
        self._sel_contours: list = []          # selection outline, normalised coords
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._tool = "hand"                     # "hand" | "brush" | "crop"
        self.brush_radius_px = 40
        self._crop_rect = None                  # normalised (x,y,w,h) of the image
        self._crop_start = None
        self._warp_last = None                  # last normalised point during a warp drag

    # --- image / overlay ---------------------------------------------------

    def set_array(self, img: np.ndarray, reset: bool = False) -> None:
        self._pixmap = ndarray_to_pixmap(img)
        if reset:
            self.reset_zoom()
        self.update()

    def set_overlay(self, mask: np.ndarray | None, filled: bool = False) -> None:
        """Show the selection.

        mask: float32 HxW in [0,1], or None to clear.
        The selection is drawn as a bright OUTLINE so the edited result stays
        visible underneath. A faint tint is added only when `filled=True` (i.e.
        while the user is actively brushing), then dropped to outline-only.
        """
        if mask is None:
            self._overlay = None
            self._sel_contours = []
            self.update()
            return

        h, w = mask.shape
        # outline: contours of the mask, stored in normalised coords (zoom/pan safe)
        binary = (mask > 0.5).astype(np.uint8)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        self._sel_contours = [c.reshape(-1, 2).astype(np.float32) / (w, h)
                              for c in contours if len(c) >= 2]

        if filled:
            rgba = np.zeros((h, w, 4), np.uint8)
            rgba[:, :, 0] = 255
            rgba[:, :, 3] = (mask * 60).astype(np.uint8)   # faint, non-obscuring
            rgba = np.ascontiguousarray(rgba)
            qi = QImage(rgba.data, w, h, 4 * w, QImage.Format.Format_RGBA8888)
            self._overlay = QPixmap.fromImage(qi.copy())
        else:
            self._overlay = None
        self.update()

    def set_tool(self, tool: str) -> None:
        self._tool = tool
        if tool != "crop":
            self._crop_rect = None
        self.setCursor(Qt.CursorShape.CrossCursor if tool in ("brush", "crop", "warp")
                       else Qt.CursorShape.ArrowCursor)
        self.update()

    def get_crop_rect(self):
        return self._crop_rect

    def reset_zoom(self) -> None:
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.update()

    # --- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.GlobalColor.black)
        if self._pixmap is None:
            return
        rect = self._draw_rect()
        p.drawPixmap(rect.toRect(), self._pixmap)
        if self._overlay is not None:
            p.drawPixmap(rect.toRect(), self._overlay)
        if self._tool == "crop" and self._crop_rect is not None:
            cx, cy, cw, ch = self._crop_rect
            cr = QRectF(rect.x() + cx * rect.width(), rect.y() + cy * rect.height(),
                        cw * rect.width(), ch * rect.height())
            dark = QColor(0, 0, 0, 130)                # dim everything outside crop
            p.fillRect(QRectF(rect.x(), rect.y(), rect.width(), cr.y() - rect.y()), dark)
            p.fillRect(QRectF(rect.x(), cr.bottom(), rect.width(), rect.bottom() - cr.bottom()), dark)
            p.fillRect(QRectF(rect.x(), cr.y(), cr.x() - rect.x(), cr.height()), dark)
            p.fillRect(QRectF(cr.right(), cr.y(), rect.right() - cr.right(), cr.height()), dark)
            p.setPen(QPen(QColor(255, 255, 255, 230), 1.5))
            p.drawRect(cr)

        if self._sel_contours:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            # bright dashed outline so it reads over any image content
            for color, width, dash in ((QColor(0, 0, 0, 200), 2.5, [4, 4]),
                                       (QColor(255, 255, 255, 230), 1.3, [4, 4])):
                pen = QPen(color)
                pen.setWidthF(width)
                pen.setDashPattern(dash)
                p.setPen(pen)
                for c in self._sel_contours:
                    poly = QPolygonF([QPointF(rect.x() + nx * rect.width(),
                                              rect.y() + ny * rect.height())
                                      for nx, ny in c])
                    p.drawPolygon(poly)

    def _draw_rect(self) -> QRectF:
        pw, ph = self._pixmap.width(), self._pixmap.height()
        ww, wh = self.width(), self.height()
        fit = min(ww / pw, wh / ph)
        dw, dh = pw * fit * self._zoom, ph * fit * self._zoom
        cx = (ww - dw) / 2 + self._pan.x()
        cy = (wh - dh) / 2 + self._pan.y()
        return QRectF(cx, cy, dw, dh)

    def _to_norm(self, pos: QPointF):
        rect = self._draw_rect()
        if rect.width() == 0 or rect.height() == 0:
            return None
        nx = (pos.x() - rect.x()) / rect.width()
        ny = (pos.y() - rect.y()) / rect.height()
        if 0 <= nx <= 1 and 0 <= ny <= 1:
            return nx, ny
        return None

    # --- events ------------------------------------------------------------

    def wheelEvent(self, event) -> None:
        if self._pixmap is None:
            return
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        new_zoom = max(0.1, min(12.0, self._zoom * factor))
        if new_zoom == self._zoom:
            return
        pos = QPointF(event.position())
        rect = self._draw_rect()
        rx = (pos.x() - rect.x()) / rect.width()
        ry = (pos.y() - rect.y()) / rect.height()
        self._zoom = new_zoom
        pw, ph = self._pixmap.width(), self._pixmap.height()
        ww, wh = self.width(), self.height()
        fit = min(ww / pw, wh / ph)
        dw, dh = pw * fit * self._zoom, ph * fit * self._zoom
        self._pan = QPointF(pos.x() - rx * dw - (ww - dw) / 2,
                            pos.y() - ry * dh - (wh - dh) / 2)
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        self.reset_zoom()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._tool == "brush":
            n = self._to_norm(QPointF(event.position()))
            if n:
                self.brush_started.emit(*n)
        elif self._tool == "crop":
            n = self._to_norm(QPointF(event.position()))
            self._crop_start = n
            if n:
                self._crop_rect = (n[0], n[1], 0.0, 0.0)
                self.update()
        elif self._tool == "warp":
            self._warp_last = self._to_norm(QPointF(event.position()))
        else:
            self._drag_start = QPointF(event.position())
            self._drag_pan = QPointF(self._pan)

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if self._tool == "brush":
            n = self._to_norm(QPointF(event.position()))
            if n:
                self.brush_moved.emit(*n)
        elif self._tool == "crop" and self._crop_start is not None:
            n = self._to_norm(QPointF(event.position()))
            if n:
                x0, y0 = self._crop_start
                x1, y1 = n
                self._crop_rect = (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
                self.update()
        elif self._tool == "warp" and self._warp_last is not None:
            n = self._to_norm(QPointF(event.position()))
            if n:
                self.warp_dragged.emit(self._warp_last[0], self._warp_last[1], n[0], n[1])
                self._warp_last = n
        elif hasattr(self, "_drag_start"):
            self._pan = self._drag_pan + (QPointF(event.position()) - self._drag_start)
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._tool == "brush":
            self.brush_ended.emit()
        elif self._tool == "crop":
            self._crop_start = None
        elif self._tool == "warp":
            self._warp_last = None
        if hasattr(self, "_drag_start"):
            del self._drag_start
