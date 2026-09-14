"""Fujifilm-inspired film simulation functions.

Each function takes a BGR uint8 ndarray and returns a BGR uint8 ndarray.
All tone curve work is done via numpy; no Qt dependencies.
"""
from __future__ import annotations

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _curve(xp: list[float], fp: list[float]) -> np.ndarray:
    """Build a 256-entry uint8 LUT from control points (xp → fp, both 0-255)."""
    t = np.arange(256, dtype=np.float32)
    out = np.interp(t, xp, fp)
    return np.clip(out, 0, 255).astype(np.uint8)


def _apply_per_channel(img: np.ndarray, lut_b: np.ndarray, lut_g: np.ndarray, lut_r: np.ndarray) -> np.ndarray:
    b, g, r = cv2.split(img)
    return cv2.merge([cv2.LUT(b, lut_b), cv2.LUT(g, lut_g), cv2.LUT(r, lut_r)])


def _shift_hue(img: np.ndarray, delta: int) -> np.ndarray:
    """Rotate hue by delta degrees (Hue is 0-179 in OpenCV)."""
    hsv = img.astype(np.int16)
    hsv[:, :, 0] = (hsv[:, :, 0] + delta) % 180
    return hsv.astype(np.uint8)


def _scale_saturation(img: np.ndarray, factor: float) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * factor, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


# ---------------------------------------------------------------------------
# Film simulations
# ---------------------------------------------------------------------------

def _provia(img: np.ndarray) -> np.ndarray:
    """Provia/Standard — slight S-curve, accurate colours."""
    lut = _curve([0, 64, 128, 192, 255], [0, 60, 128, 196, 255])
    neutral = _apply_per_channel(img, lut, lut, lut)
    return neutral


def _velvia(img: np.ndarray) -> np.ndarray:
    """Velvia — punchy contrast, boosted saturation, warm cast."""
    # Strong S-curve
    lut_shared = _curve([0, 32, 128, 224, 255], [0, 20, 128, 235, 255])
    # Warm: lift red, slightly suppress blue
    lut_r = _curve([0, 128, 255], [0, 135, 255])
    lut_b = _curve([0, 128, 255], [0, 118, 245])
    out = _apply_per_channel(img, lut_b, lut_shared, lut_r)
    return _scale_saturation(out, 1.35)


def _astia(img: np.ndarray) -> np.ndarray:
    """Astia/Soft — lifted shadows, gentle S-curve, natural skin tones."""
    lut = _curve([0, 64, 128, 192, 255], [15, 70, 128, 188, 245])
    out = _apply_per_channel(img, lut, lut, lut)
    return _scale_saturation(out, 0.88)


def _classic_chrome(img: np.ndarray) -> np.ndarray:
    """Classic Chrome — lifted blacks, desaturated blues/greens, cool cast."""
    # Lifted shadow base, compressed highlights
    lut_shared = _curve([0, 64, 128, 192, 255], [20, 72, 128, 185, 240])
    # Cool: lift blue slightly, pull red back
    lut_r = _curve([0, 128, 255], [0, 122, 238])
    lut_b = _curve([0, 128, 255], [5, 132, 248])
    out = _apply_per_channel(img, lut_b, lut_shared, lut_r)
    # Desaturate blues and greens selectively via global sat reduction
    return _scale_saturation(out, 0.72)


def _classic_neg(img: np.ndarray) -> np.ndarray:
    """Classic Neg — warm shadows, cyan highlight push, high contrast."""
    lut_shared = _curve([0, 40, 128, 215, 255], [0, 28, 130, 228, 255])
    # Warm shadows: lift red in shadows; cyan highlights: suppress red in highlights
    lut_r = _curve([0, 64, 128, 200, 255], [8, 74, 132, 200, 248])
    # Cool highlights via blue channel
    lut_b = _curve([0, 64, 128, 200, 255], [0, 58, 126, 205, 255])
    out = _apply_per_channel(img, lut_b, lut_shared, lut_r)
    return _scale_saturation(out, 1.15)


def _acros(img: np.ndarray) -> np.ndarray:
    """Acros — rich black-and-white with deep blacks and luminosity weights."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    lut = _curve([0, 32, 100, 180, 255], [0, 18, 95, 188, 255])
    gray = cv2.LUT(gray, lut)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def _eterna(img: np.ndarray) -> np.ndarray:
    """Eterna — flat cinematic look, low contrast, muted colours."""
    # Lift blacks, compress highlights — flat log-like tone
    lut = _curve([0, 64, 128, 192, 255], [30, 80, 128, 178, 220])
    out = _apply_per_channel(img, lut, lut, lut)
    # Slight cool-green cast typical of cinema film
    lut_b = _curve([0, 128, 255], [2, 130, 245])
    lut_g = _curve([0, 128, 255], [0, 130, 252])
    lut_r = _curve([0, 128, 255], [0, 124, 238])
    out = _apply_per_channel(out, lut_b, lut_g, lut_r)
    return _scale_saturation(out, 0.80)


def _sepia(img: np.ndarray) -> np.ndarray:
    """Sepia — warm brown monochrome."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    lut = _curve([0, 64, 128, 192, 255], [0, 55, 118, 185, 245])
    gray = cv2.LUT(gray, lut)
    bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR).astype(np.float32)
    # Tint: warm brown (r > g > b)
    tinted = bgr.copy()
    tinted[:, :, 2] = np.clip(bgr[:, :, 2] * 1.12, 0, 255)   # red up
    tinted[:, :, 1] = np.clip(bgr[:, :, 1] * 0.90, 0, 255)   # green slightly down
    tinted[:, :, 0] = np.clip(bgr[:, :, 0] * 0.68, 0, 255)   # blue down
    return tinted.astype(np.uint8)


def _faded(img: np.ndarray) -> np.ndarray:
    """Faded / Matte — lifted blacks, reduced contrast, slightly cool."""
    # Lift shadows, compress highlights — matte look
    lut = _curve([0, 64, 128, 192, 255], [40, 88, 138, 188, 230])
    out = _apply_per_channel(img, lut, lut, lut)
    # Slight cool cast
    lut_b = _curve([0, 128, 255], [5, 135, 250])
    lut_r = _curve([0, 128, 255], [0, 122, 235])
    lut_g = _curve([0, 128, 255], [0, 128, 245])
    out = _apply_per_channel(out, lut_b, lut_g, lut_r)
    return _scale_saturation(out, 0.78)


def _cross_process(img: np.ndarray) -> np.ndarray:
    """Cross Process — slide film developed in C-41, vivid colour shifts."""
    lut_g = _curve([0, 64, 128, 192, 255], [0, 40, 128, 210, 255])
    lut_r = _curve([0, 64, 128, 192, 255], [10, 60, 138, 218, 255])
    lut_b = _curve([0, 64, 128, 192, 255], [0, 20, 100, 170, 220])
    out = _apply_per_channel(img, lut_b, lut_g, lut_r)
    return _scale_saturation(out, 1.30)


def _fortia_sp(img: np.ndarray) -> np.ndarray:
    """Fortia SP — ultra-vivid saturation, more extreme than Velvia."""
    lut_shared = _curve([0, 24, 128, 232, 255], [0, 10, 128, 242, 255])
    lut_r = _curve([0, 128, 255], [0, 138, 255])
    lut_b = _curve([0, 128, 255], [0, 114, 240])
    out = _apply_per_channel(img, lut_b, lut_shared, lut_r)
    return _scale_saturation(out, 1.55)


def _neopan_1600(img: np.ndarray) -> np.ndarray:
    """Neopan 1600 — high-contrast B&W with deep blacks, high-ISO character."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    lut = _curve([0, 20, 80, 160, 220, 255], [0, 8, 60, 175, 235, 255])
    return cv2.cvtColor(cv2.LUT(gray, lut), cv2.COLOR_GRAY2BGR)


def _t64(img: np.ndarray) -> np.ndarray:
    """T64 — tungsten-balanced slide film; strong blue/cool cast in daylight."""
    lut_b = _curve([0, 64, 128, 192, 255], [20, 95, 160, 215, 255])
    lut_g = _curve([0, 128, 255], [0, 128, 245])
    lut_r = _curve([0, 64, 128, 192, 255], [0, 55, 108, 168, 215])
    return _apply_per_channel(img, lut_b, lut_g, lut_r)


def _pro_800z(img: np.ndarray) -> np.ndarray:
    """Pro 800Z — warm portrait negative, natural skin, lifted shadows."""
    lut = _curve([0, 64, 128, 192, 255], [10, 72, 130, 190, 248])
    lut_r = _curve([0, 128, 255], [0, 132, 252])
    lut_g = _curve([0, 128, 255], [0, 128, 248])
    lut_b = _curve([0, 128, 255], [0, 124, 242])
    out = _apply_per_channel(img, lut_b, lut_g, lut_r)
    out = _apply_per_channel(out, lut, lut, lut)
    return _scale_saturation(out, 0.90)


def _pro_400h(img: np.ndarray) -> np.ndarray:
    """Pro 400H — soft pastel portrait negative, very low contrast."""
    lut = _curve([0, 64, 128, 192, 255], [25, 82, 135, 190, 235])
    out = _apply_per_channel(img, lut, lut, lut)
    lut_r = _curve([0, 128, 255], [0, 128, 250])
    lut_g = _curve([0, 128, 255], [0, 125, 238])
    lut_b = _curve([0, 128, 255], [0, 126, 248])
    out = _apply_per_channel(out, lut_b, lut_g, lut_r)
    return _scale_saturation(out, 0.82)


def _pro_160c(img: np.ndarray) -> np.ndarray:
    """Pro 160C — natural daylight negative, clean and slightly warm."""
    lut = _curve([0, 64, 128, 192, 255], [5, 68, 130, 192, 250])
    lut_r = _curve([0, 128, 255], [0, 130, 252])
    lut_b = _curve([0, 128, 255], [0, 126, 248])
    out = _apply_per_channel(img, lut_b, lut, lut_r)
    return _scale_saturation(out, 0.95)


def _pro_160s(img: np.ndarray) -> np.ndarray:
    """Pro 160S — neutral daylight negative, cooler than 160C."""
    lut = _curve([0, 64, 128, 192, 255], [5, 68, 128, 190, 250])
    lut_b = _curve([0, 128, 255], [2, 130, 250])
    lut_r = _curve([0, 128, 255], [0, 125, 246])
    out = _apply_per_channel(img, lut_b, lut, lut_r)
    return _scale_saturation(out, 0.92)


def _superia_1600(img: np.ndarray) -> np.ndarray:
    """Superia 1600 — warm consumer high-ISO, pushed and contrasty."""
    lut = _curve([0, 40, 128, 210, 255], [0, 25, 132, 225, 255])
    out = _apply_per_channel(img, lut, lut, lut)
    lut_r = _curve([0, 128, 255], [0, 134, 252])
    lut_g = _curve([0, 128, 255], [0, 130, 248])
    lut_b = _curve([0, 128, 255], [0, 118, 238])
    out = _apply_per_channel(out, lut_b, lut_g, lut_r)
    return _scale_saturation(out, 1.10)


def _superia_400(img: np.ndarray) -> np.ndarray:
    """Superia 400 — warm mid-range consumer film, slight warm/green cast."""
    lut = _curve([0, 64, 128, 192, 255], [5, 68, 130, 192, 250])
    lut_r = _curve([0, 128, 255], [0, 132, 250])
    lut_g = _curve([0, 128, 255], [0, 130, 248])
    lut_b = _curve([0, 128, 255], [0, 122, 240])
    out = _apply_per_channel(img, lut_b, lut_g, lut_r)
    out = _apply_per_channel(out, lut, lut, lut)
    return _scale_saturation(out, 1.05)


def _superia_100(img: np.ndarray) -> np.ndarray:
    """Superia 100 — clean slow consumer film, barely warm."""
    lut = _curve([0, 64, 128, 192, 255], [2, 65, 128, 193, 252])
    lut_r = _curve([0, 128, 255], [0, 130, 250])
    lut_b = _curve([0, 128, 255], [0, 126, 246])
    out = _apply_per_channel(img, lut_b, lut, lut_r)
    return _scale_saturation(out, 1.02)


# ---------------------------------------------------------------------------
# Camera picture profiles (Canon / Nikon / Sony style) + contrast presets
# ---------------------------------------------------------------------------

def _cam_standard(img: np.ndarray) -> np.ndarray:
    """Standard — mild S-curve, slightly boosted colour (default camera look)."""
    lut = _curve([0, 64, 128, 192, 255], [0, 58, 128, 198, 255])
    out = _apply_per_channel(img, lut, lut, lut)
    return _scale_saturation(out, 1.12)


def _cam_vivid(img: np.ndarray) -> np.ndarray:
    """Vivid — punchy contrast and high saturation."""
    lut = _curve([0, 48, 128, 208, 255], [0, 30, 128, 226, 255])
    out = _apply_per_channel(img, lut, lut, lut)
    return _scale_saturation(out, 1.4)


def _cam_neutral(img: np.ndarray) -> np.ndarray:
    """Neutral — low contrast, restrained colour for later editing."""
    lut = _curve([0, 128, 255], [6, 128, 250])
    out = _apply_per_channel(img, lut, lut, lut)
    return _scale_saturation(out, 0.94)


def _cam_faithful(img: np.ndarray) -> np.ndarray:
    """Faithful — accurate colour, near-linear tone."""
    lut = _curve([0, 128, 255], [2, 128, 253])
    return _apply_per_channel(img, lut, lut, lut)


def _cam_flat(img: np.ndarray) -> np.ndarray:
    """Flat/Log — lifted blacks, pulled highlights, muted colour for grading."""
    lut = _curve([0, 64, 128, 192, 255], [20, 76, 128, 180, 236])
    out = _apply_per_channel(img, lut, lut, lut)
    return _scale_saturation(out, 0.88)


def _cam_landscape(img: np.ndarray) -> np.ndarray:
    """Landscape — strong contrast, vivid greens and blues."""
    lut = _curve([0, 48, 128, 208, 255], [0, 34, 128, 222, 255])
    lut_g = _curve([0, 128, 255], [0, 134, 255])   # lift greens
    lut_b = _curve([0, 128, 255], [0, 134, 255])   # lift blues
    out = _apply_per_channel(img, lut_b, lut_g, lut)
    return _scale_saturation(out, 1.3)


def _cam_portrait(img: np.ndarray) -> np.ndarray:
    """Portrait — gentle contrast, warm skin, restrained saturation."""
    lut = _curve([0, 64, 128, 192, 255], [8, 68, 128, 190, 248])
    lut_r = _curve([0, 128, 255], [0, 134, 255])   # slightly warm
    out = _apply_per_channel(img, lut, lut, lut_r)
    return _scale_saturation(out, 1.05)


def _cam_monochrome(img: np.ndarray) -> np.ndarray:
    """Monochrome — luminosity-weighted B&W with mild contrast."""
    b, g, r = cv2.split(img.astype(np.float32))
    y = np.clip(0.114 * b + 0.587 * g + 0.299 * r, 0, 255).astype(np.uint8)
    lut = _curve([0, 64, 128, 192, 255], [0, 56, 128, 200, 255])
    y = cv2.LUT(y, lut)
    return cv2.cvtColor(y, cv2.COLOR_GRAY2BGR)


def _high_contrast(img: np.ndarray) -> np.ndarray:
    """High contrast tone preset."""
    lut = _curve([0, 32, 128, 224, 255], [0, 14, 128, 242, 255])
    return _apply_per_channel(img, lut, lut, lut)


def _low_contrast(img: np.ndarray) -> np.ndarray:
    """Low contrast tone preset (lifted blacks, pulled whites)."""
    lut = _curve([0, 64, 128, 192, 255], [26, 80, 128, 176, 230])
    return _apply_per_channel(img, lut, lut, lut)


# ---------------------------------------------------------------------------
# Public dict
# ---------------------------------------------------------------------------

FILM_SIMS: dict[str, object] = {
    # camera picture profiles + tone presets
    "standard": _cam_standard,
    "vivid": _cam_vivid,
    "neutral": _cam_neutral,
    "faithful": _cam_faithful,
    "flat": _cam_flat,
    "landscape": _cam_landscape,
    "portrait": _cam_portrait,
    "monochrome": _cam_monochrome,
    "high_contrast": _high_contrast,
    "low_contrast": _low_contrast,
    # Fujifilm-inspired film simulations
    "provia": _provia,
    "velvia": _velvia,
    "astia": _astia,
    "classic_chrome": _classic_chrome,
    "classic_neg": _classic_neg,
    "acros": _acros,
    "eterna": _eterna,
    "sepia": _sepia,
    "faded": _faded,
    "cross_process": _cross_process,
    "fortia_sp": _fortia_sp,
    "neopan_1600": _neopan_1600,
    "t64": _t64,
    "pro_800z": _pro_800z,
    "pro_400h": _pro_400h,
    "pro_160c": _pro_160c,
    "pro_160s": _pro_160s,
    "superia_1600": _superia_1600,
    "superia_400": _superia_400,
    "superia_100": _superia_100,
}
