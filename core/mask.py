"""Masks — resolution-independent recipes rasterized on demand.

A Mask is a stack of MaskSource recipes stored in NORMALISED coordinates
(x, y in [0,1] of width/height; radii as a fraction of the image diagonal).
`resolve(h, w, guide)` rasterizes to a float32 HxW array in [0,1] at any
resolution, so the same mask drives both the proxy preview and the full-res
export. This is what keeps edits non-destructive and resolution-safe.

Feathering: a Gaussian blur (cheap) or an edge-aware guided filter that snaps
the mask edge to image edges (needs opencv-contrib's ximgproc).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


def _diag(h, w):
    return (h * h + w * w) ** 0.5


# ---------------------------------------------------------------------------
# Mask sources — each rasterizes into a float32 HxW array in [0, 1]
# ---------------------------------------------------------------------------

@dataclass
class BrushStroke:
    # polyline of normalised points; radius as fraction of image diagonal
    points: list[tuple[float, float]] = field(default_factory=list)
    radius: float = 0.03
    op: str = "add"            # "add" | "subtract"

    def render(self, h, w, guide=None):
        m = np.zeros((h, w), np.float32)
        r = max(1, int(self.radius * _diag(h, w)))
        pts = [(int(x * w), int(y * h)) for x, y in self.points]
        if len(pts) == 1:
            cv2.circle(m, pts[0], r, 1.0, -1, cv2.LINE_AA)
        for a, b in zip(pts, pts[1:]):
            cv2.line(m, a, b, 1.0, r * 2, cv2.LINE_AA)
            cv2.circle(m, b, r, 1.0, -1, cv2.LINE_AA)
        return m


@dataclass
class EllipseShape:
    cx: float = 0.5
    cy: float = 0.5
    rx: float = 0.25          # fraction of width
    ry: float = 0.25          # fraction of height
    op: str = "add"

    def render(self, h, w, guide=None):
        m = np.zeros((h, w), np.float32)
        cv2.ellipse(m, (int(self.cx * w), int(self.cy * h)),
                    (max(1, int(self.rx * w)), max(1, int(self.ry * h))),
                    0, 0, 360, 1.0, -1, cv2.LINE_AA)
        return m


@dataclass
class LinearGradient:
    # mask ramps 0->1 from p0 to p1 (normalised); perpendicular bands are constant
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 1.0
    y1: float = 0.0
    op: str = "add"

    def render(self, h, w, guide=None):
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        x0, y0 = self.x0 * w, self.y0 * h
        x1, y1 = self.x1 * w, self.y1 * h
        dx, dy = x1 - x0, y1 - y0
        length2 = dx * dx + dy * dy
        if length2 == 0:
            return np.zeros((h, w), np.float32)
        t = ((xx - x0) * dx + (yy - y0) * dy) / length2
        return np.clip(t, 0.0, 1.0).astype(np.float32)


@dataclass
class RadialGradient:
    cx: float = 0.5
    cy: float = 0.5
    radius: float = 0.4        # fraction of diagonal; full inside, 0 at edge
    op: str = "add"

    def render(self, h, w, guide=None):
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        cx, cy = self.cx * w, self.cy * h
        r = max(1.0, self.radius * _diag(h, w))
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        return np.clip(1.0 - dist / r, 0.0, 1.0).astype(np.float32)


@dataclass
class RasterSource:
    """A precomputed pixel mask (e.g. from a segmentation model).

    Stored at whatever resolution it was produced and resized to the target on
    render, so it still travels through proxy preview → full-res export like the
    geometric sources. `data` is float32 in [0,1].
    """
    data: "np.ndarray" = None
    op: str = "add"

    def render(self, h, w, guide=None):
        if self.data is None:
            return np.zeros((h, w), np.float32)
        if self.data.shape[:2] == (h, w):
            return self.data.astype(np.float32)
        return cv2.resize(self.data.astype(np.float32), (w, h),
                          interpolation=cv2.INTER_LINEAR)

    def __repr__(self):   # keep Layer's cache key cheap + stable
        d = self.data
        sig = None if d is None else (d.shape, int(d.sum()))
        return f"RasterSource(op={self.op}, sig={sig})"


@dataclass
class LuminanceRange:
    """Parametric mask: select pixels by brightness (Darktable-style)."""
    lo: float = 0.0            # [0,1]
    hi: float = 1.0
    feather: float = 0.1       # soft edge width in luminance units
    op: str = "add"

    def render(self, h, w, guide=None):
        if guide is None:
            return np.ones((h, w), np.float32)
        lum = cv2.cvtColor(guide, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        f = max(self.feather, 1e-3)
        lo_ramp = np.clip((lum - (self.lo - f)) / f, 0, 1)
        hi_ramp = np.clip(((self.hi + f) - lum) / f, 0, 1)
        return (lo_ramp * hi_ramp).astype(np.float32)


# ---------------------------------------------------------------------------
# Mask — a stack of sources + feather/refine settings
# ---------------------------------------------------------------------------

@dataclass
class Mask:
    sources: list = field(default_factory=list)
    invert: bool = False
    feather: float = 0.0       # blur sigma as fraction of diagonal
    edge_aware: bool = False   # guided-filter refine against the image

    def is_empty(self) -> bool:
        return not self.sources

    def resolve(self, h: int, w: int, guide: np.ndarray | None = None) -> np.ndarray:
        """Rasterize to float32 HxW in [0,1]."""
        m = np.zeros((h, w), np.float32)
        for src in self.sources:
            layer = src.render(h, w, guide)
            if getattr(src, "op", "add") == "subtract":
                m = np.clip(m - layer, 0, 1)
            else:
                m = np.clip(m + layer, 0, 1)

        if self.feather > 0:
            sigma = self.feather * _diag(h, w)
            k = int(sigma * 3) | 1
            m = cv2.GaussianBlur(m, (k, k), sigma)

        if self.edge_aware and guide is not None:
            try:
                m = cv2.ximgproc.guidedFilter(
                    guide, m, radius=max(2, int(0.01 * _diag(h, w))), eps=1e-4)
                m = np.clip(m, 0, 1)
            except (cv2.error, AttributeError):
                pass  # ximgproc unavailable — keep the gaussian-feathered mask

        if self.invert:
            m = 1.0 - m
        return m
