"""Per-pixel adjustment operations. Ported from image_selector/edit_ops.py.

Every op: (img: BGR uint8, **params) -> BGR uint8, same shape. No Qt.
The OPS registry lets a Layer reference an op by name + params dict.
"""
from __future__ import annotations

import cv2
import numpy as np

from . import curves as _curves


def _make_lut(fn) -> np.ndarray:
    t = np.arange(256, dtype=np.float32)
    return np.clip(fn(t), 0, 255).astype(np.uint8)


# --- tonal / colour adjustments -------------------------------------------

def brightness(img, value: float = 0.0):
    """Shift V channel in HSV. value ∈ [-100, 100]."""
    if value == 0.0:
        return img
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.int16)
    hsv[:, :, 2] = np.clip(hsv[:, :, 2] + int(value * 255 / 100), 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def contrast(img, value: float = 0.0):
    """Scale around 128, per RGB channel. value ∈ [-100, 100].

    Note: applying the same curve to each channel also boosts saturation — punchy,
    good for a whole-image look. For local edits that must stay natural, use
    `contrast_lum` (luminance only, no colour shift)."""
    if value == 0.0:
        return img
    factor = (value + 100) / 100.0
    return cv2.LUT(img, _make_lut(lambda t: (t - 128) * factor + 128))


def contrast_lum(img, value: float = 0.0):
    """Contrast applied to luminance only (LAB L channel) — colour/saturation are
    preserved, so a locally boosted region doesn't look edited. value ∈ [-100,100]."""
    if value == 0.0:
        return img
    factor = (value + 100) / 100.0
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lut = _make_lut(lambda t: (t - 128) * factor + 128)
    lab[:, :, 0] = cv2.LUT(lab[:, :, 0], lut)
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def exposure(img, stops: float = 0.0):
    """Multiply luminance by 2^stops. stops ∈ [-3, 3]."""
    if stops == 0.0:
        return img
    scale = 2.0 ** stops
    return cv2.LUT(img, _make_lut(lambda t: t * scale))


def saturation(img, value: float = 0.0):
    """Scale S channel in HSV. value ∈ [-100, 100]."""
    if value == 0.0:
        return img
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * (1.0 + value / 100.0), 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def vibrance(img, value: float = 0.0):
    """Smart saturation: boosts muted colours more than already-vivid ones,
    so it looks natural. value ∈ [-100, 100]."""
    if value == 0.0:
        return img
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    s01 = hsv[:, :, 1] / 255.0
    factor = 1.0 + (value / 100.0) * (1.0 - s01)   # low-sat pixels get more
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * factor, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def temperature(img, value: float = 0.0):
    """Warm (+) / cool (-) white balance shift. value ∈ [-100, 100]."""
    if value == 0.0:
        return img
    f = img.astype(np.float32)
    f[:, :, 2] = np.clip(f[:, :, 2] * (1.0 + value / 300.0), 0, 255)   # R
    f[:, :, 0] = np.clip(f[:, :, 0] * (1.0 - value / 300.0), 0, 255)   # B
    return f.astype(np.uint8)


def tint(img, value: float = 0.0):
    """Magenta (+) / green (-) shift. value ∈ [-100, 100]."""
    if value == 0.0:
        return img
    f = img.astype(np.float32)
    f[:, :, 1] = np.clip(f[:, :, 1] * (1.0 - value / 300.0), 0, 255)   # G
    return f.astype(np.uint8)


def shadows(img, value: float = 0.0):
    """Lift/crush lower tones. value ∈ [-100, 100]."""
    if value == 0.0:
        return img
    shift = value * 0.5
    return cv2.LUT(img, _make_lut(
        lambda t: t + shift * np.clip(1.0 - t / 192.0, 0, 1) ** 2))


def highlights(img, value: float = 0.0):
    """Roll-off/boost upper tones. value ∈ [-100, 100]."""
    if value == 0.0:
        return img
    shift = value * 0.5
    return cv2.LUT(img, _make_lut(
        lambda t: t + shift * np.clip((t - 64) / 191.0, 0, 1) ** 2))


def curves(img, master=None, r=None, g=None, b=None):
    """Tone/colour curves via monotone-spline LUT (see core.curves)."""
    return _curves.apply_curves(img, master, r, g, b)


# --- auto / analytic adjustments ------------------------------------------

def normalize(img):
    """CLAHE on the L channel in LAB."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    lab[:, :, 0] = clahe.apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def auto_levels(img, clip: float = 0.5):
    """Stretch each BGR channel to its clip..(100-clip) percentile range."""
    out = np.empty_like(img)
    for i in range(3):
        ch = img[:, :, i].astype(np.float32)
        lo = np.percentile(ch, clip)
        hi = np.percentile(ch, 100.0 - clip)
        if hi <= lo:
            out[:, :, i] = img[:, :, i]
            continue
        out[:, :, i] = np.clip((ch - lo) * 255.0 / (hi - lo), 0, 255).astype(np.uint8)
    return out


def auto_tone(img, clip: float = 0.5):
    """Stretch luminance (LAB L) only, preserving colour balance."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    l = lab[:, :, 0]
    lo = np.percentile(l, clip)
    hi = np.percentile(l, 100.0 - clip)
    if hi > lo:
        lab[:, :, 0] = np.clip((l - lo) * 255.0 / (hi - lo), 0, 255)
    return cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)


def auto_wb(img):
    """Grey-world white balance."""
    f = img.astype(np.float32)
    means = [f[:, :, i].mean() for i in range(3)]
    overall = sum(means) / 3.0
    for i in range(3):
        if means[i] > 0:
            f[:, :, i] = np.clip(f[:, :, i] * overall / means[i], 0, 255)
    return f.astype(np.uint8)


def film(img, name: str = "original"):
    """Apply a Fujifilm-inspired film simulation by name (see core.film_luts)."""
    from .film_luts import FILM_SIMS
    fn = FILM_SIMS.get(name)
    return fn(img) if fn else img


# --- registry --------------------------------------------------------------

OPS = {
    "brightness": brightness,
    "contrast": contrast,
    "contrast_lum": contrast_lum,
    "exposure": exposure,
    "saturation": saturation,
    "vibrance": vibrance,
    "temperature": temperature,
    "tint": tint,
    "shadows": shadows,
    "highlights": highlights,
    "curves": curves,
    "normalize": normalize,
    "auto_levels": auto_levels,
    "auto_tone": auto_tone,
    "auto_wb": auto_wb,
    "film": film,
}


def apply_op(img: np.ndarray, name: str, params: dict) -> np.ndarray:
    """Look up an op by name and apply it with the given params."""
    fn = OPS.get(name)
    if fn is None:
        return img
    return fn(img, **(params or {}))
