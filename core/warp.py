"""Liquify / reshape — a push-brush warp (like phone "Reshape/Slim" tools).

A WarpField holds a smooth displacement map (fx, fy) in NORMALISED units
(fraction of width / height) on a small grid sized to the image aspect. Dragging
the brush accumulates a Gaussian-falloff push into the field; `apply` resizes the
field to the target resolution and warps the image with cv2.remap — so the same
field drives both the proxy preview and the full-resolution export.

To slim: push the body's edge inward. The field is stored (not the warped pixels),
keeping the edit non-destructive.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

GRID_LONG = 256          # longest side of the displacement grid


@dataclass
class WarpField:
    fx: np.ndarray = None    # normalised x-displacement (fraction of width),  (GH,GW)
    fy: np.ndarray = None    # normalised y-displacement (fraction of height), (GH,GW)

    @staticmethod
    def for_aspect(h: int, w: int) -> "WarpField":
        if w >= h:
            gw = GRID_LONG
            gh = max(2, round(GRID_LONG * h / w))
        else:
            gh = GRID_LONG
            gw = max(2, round(GRID_LONG * w / h))
        return WarpField(fx=np.zeros((gh, gw), np.float32),
                         fy=np.zeros((gh, gw), np.float32))

    def is_empty(self) -> bool:
        return self.fx is None or (not self.fx.any() and not self.fy.any())

    def push(self, nx: float, ny: float, dnx: float, dny: float,
             radius: float, strength: float = 1.0) -> None:
        """Add a push at normalised (nx,ny) moving by (dnx,dny) — all in [0,1]
        fractions of width/height. `radius` is a fraction of the grid diagonal."""
        gh, gw = self.fx.shape
        cx, cy = nx * gw, ny * gh
        diag = (gw * gw + gh * gh) ** 0.5
        r = max(2.0, radius * diag)
        yy, xx = np.mgrid[0:gh, 0:gw].astype(np.float32)
        d2 = (xx - cx) ** 2 + (yy - cy) ** 2
        fall = np.exp(-d2 / (2.0 * (r * 0.45) ** 2)).astype(np.float32)
        fall[d2 > r * r] = 0.0
        self.fx += (strength * dnx) * fall
        self.fy += (strength * dny) * fall


def apply(img: np.ndarray, fx: np.ndarray, fy: np.ndarray) -> np.ndarray:
    """Warp `img` (BGR) by the normalised displacement field. Returns BGR uint8."""
    if fx is None or (not fx.any() and not fy.any()):
        return img
    h, w = img.shape[:2]
    FX = cv2.resize(fx, (w, h), interpolation=cv2.INTER_LINEAR)
    FY = cv2.resize(fy, (w, h), interpolation=cv2.INTER_LINEAR)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    # a pixel in the output samples from (x - displacement) in the source, so the
    # region under the brush moves WITH the drag direction
    map_x = (xx - FX * w).astype(np.float32)
    map_y = (yy - FY * h).astype(np.float32)
    return cv2.remap(img, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
