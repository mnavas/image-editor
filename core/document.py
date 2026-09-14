"""Document — the non-destructive editing model (base image + layer stack).

The SAME render() drives the live proxy (scale < 1) and the full-resolution
export (scale = 1), so what the user sees is exactly what gets saved. Geometry
(rotation, crop) is applied first; then each visible layer top of stack last.

Zero Qt imports — this can back a headless/MCP process unchanged.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

import cv2
import numpy as np

from .layers import Layer


def _rotate(img, degrees):
    d = degrees % 360
    if d == 0:
        return img
    if d == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if d == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if d == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


def _crop(img, rect):
    ih, iw = img.shape[:2]
    x, y, w, h = rect
    x0, y0 = max(0, int(x * iw)), max(0, int(y * ih))
    x1, y1 = min(iw, int((x + w) * iw)), min(ih, int((y + h) * ih))
    if x1 <= x0 or y1 <= y0:
        return img
    return img[y0:y1, x0:x1]


@dataclass
class Document:
    base: np.ndarray                       # immutable original, BGR uint8, full res
    layers: list[Layer] = field(default_factory=list)
    crop_rect: tuple | None = None         # (x,y,w,h) normalised, post-rotation
    rotation: int = 0
    # undo/redo of the (layers, crop, rotation) triple
    _undo: list = field(default_factory=list, repr=False)
    _redo: list = field(default_factory=list, repr=False)

    # --- geometry ----------------------------------------------------------

    def _geometry(self, img):
        out = _rotate(img, self.rotation)
        if self.crop_rect is not None:
            out = _crop(out, self.crop_rect)
        return out

    # --- rendering ---------------------------------------------------------

    def render(self, scale: float = 1.0) -> np.ndarray:
        """Render the composited result. scale<1 → fast proxy; 1.0 → full res."""
        img = self.base
        if scale != 1.0:
            h, w = img.shape[:2]
            img = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))),
                             interpolation=cv2.INTER_AREA)
        out = self._geometry(img)
        for layer in self.layers:
            out = layer.render_onto(out)
        return out

    def proxy_scale(self, max_side: int) -> float:
        """Scale factor so the base's longest side is <= max_side."""
        h, w = self.base.shape[:2]
        long = max(h, w)
        return 1.0 if long <= max_side else max_side / long

    # --- editing + history -------------------------------------------------

    def _snapshot(self):
        return (copy.deepcopy(self.layers), self.crop_rect, self.rotation)

    def _restore(self, snap):
        self.layers, self.crop_rect, self.rotation = snap

    def push_history(self):
        """Call BEFORE a mutating change so it can be undone."""
        self._undo.append(self._snapshot())
        self._redo.clear()

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())
        return True

    def add_layer(self, layer: Layer) -> Layer:
        self.push_history()
        self.layers.append(layer)
        return layer

    def remove_layer(self, layer: Layer):
        if layer in self.layers:
            self.push_history()
            self.layers.remove(layer)
