"""Tone curves via monotone cubic (PCHIP) interpolation → 256-entry LUT.

A curve is a list of (x, y) control points in [0, 255]. The identity curve is
[(0,0), (255,255)]. Monotone (Fritsch–Carlson) interpolation is used instead of a
plain cubic spline so the curve never overshoots — overshoot would cause tonal
reversals (a brighter input mapping to a darker output).

No SciPy dependency — the monotone cubic is implemented directly.
"""
from __future__ import annotations

import cv2
import numpy as np


def _pchip_lut(points: list[tuple[float, float]]) -> np.ndarray:
    """Build a 256-entry uint8 LUT from control points using Fritsch–Carlson."""
    pts = sorted(points, key=lambda p: p[0])
    xs = np.array([p[0] for p in pts], dtype=np.float64)
    ys = np.array([p[1] for p in pts], dtype=np.float64)

    n = len(xs)
    if n < 2:
        # degenerate — flat line
        return np.clip(np.full(256, ys[0] if n else 0), 0, 255).astype(np.uint8)

    h = np.diff(xs)
    delta = np.diff(ys) / h  # secant slopes

    # tangents m[i]
    m = np.zeros(n)
    m[0] = delta[0]
    m[-1] = delta[-1]
    for i in range(1, n - 1):
        if delta[i - 1] * delta[i] <= 0:
            m[i] = 0.0  # local extremum → flat, guarantees monotonicity
        else:
            w1 = 2 * h[i] + h[i - 1]
            w2 = h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / delta[i - 1] + w2 / delta[i])

    # evaluate the Hermite cubic on the full 0..255 grid
    grid = np.arange(256, dtype=np.float64)
    out = np.empty(256, dtype=np.float64)
    idx = np.clip(np.searchsorted(xs, grid) - 1, 0, n - 2)
    for k in range(256):
        i = idx[k]
        t = (grid[k] - xs[i]) / h[i]
        t = min(max(t, 0.0), 1.0)
        h00 = 2 * t**3 - 3 * t**2 + 1
        h10 = t**3 - 2 * t**2 + t
        h01 = -2 * t**3 + 3 * t**2
        h11 = t**3 - t**2
        out[k] = (h00 * ys[i] + h10 * h[i] * m[i]
                  + h01 * ys[i + 1] + h11 * h[i] * m[i + 1])

    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def build_lut(master=None, r=None, g=None, b=None) -> np.ndarray:
    """Build a (256,1,3) BGR LUT from per-channel control-point lists.

    Each arg is a list of (x,y) points or None (identity). `master` is applied on
    top of every channel (composed after the per-channel curve).
    Returns a LUT ready for cv2.LUT on a BGR image.
    """
    ident = [(0, 0), (255, 255)]
    master_lut = _pchip_lut(master) if master else np.arange(256, dtype=np.uint8)
    b_lut = _pchip_lut(b) if b else np.arange(256, dtype=np.uint8)
    g_lut = _pchip_lut(g) if g else np.arange(256, dtype=np.uint8)
    r_lut = _pchip_lut(r) if r else np.arange(256, dtype=np.uint8)

    # compose master after each per-channel curve
    b_lut = master_lut[b_lut]
    g_lut = master_lut[g_lut]
    r_lut = master_lut[r_lut]

    lut = np.stack([b_lut, g_lut, r_lut], axis=1)  # (256, 3), BGR order
    return lut.reshape(256, 1, 3)


def apply_curves(img: np.ndarray, master=None, r=None, g=None, b=None) -> np.ndarray:
    """Apply master + per-channel curves to a BGR uint8 image."""
    if not any([master, r, g, b]):
        return img
    lut = build_lut(master, r, g, b)
    return cv2.LUT(img, lut)
