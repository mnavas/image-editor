"""Inpainting / heal dispatch.

Picks an engine by mask size and availability:
  - tiny masks  -> cv2.inpaint (Telea / Navier-Stokes): fast, CPU, dust & specks
  - larger      -> LaMa (optional backend) for plausible texture over big holes
  - fallback    -> cv2.inpaint if the ML backend is unavailable

Returns a FULL image with the masked region filled; the Layer then composites it
back through the (feathered) mask so the fill blends into its surroundings.
"""
from __future__ import annotations

import cv2
import numpy as np


def _to_uint8_mask(mask: np.ndarray | None, shape) -> np.ndarray:
    if mask is None:
        return np.zeros(shape[:2], np.uint8)
    m = mask
    if m.dtype != np.uint8:
        m = (np.clip(m, 0, 1) * 255).astype(np.uint8)
    return (m > 10).astype(np.uint8) * 255


def _classical(img, mask_u8, radius=3, method="telea"):
    flag = cv2.INPAINT_TELEA if method == "telea" else cv2.INPAINT_NS
    return cv2.inpaint(img, mask_u8, radius, flag)


def apply(base: np.ndarray, params: dict, mask: np.ndarray | None) -> np.ndarray:
    """Fill the masked region of `base`. params: {engine, radius, method}."""
    mask_u8 = _to_uint8_mask(mask, base.shape)
    if mask_u8.max() == 0:
        return base

    engine = params.get("engine", "auto")
    frac = (mask_u8 > 0).mean()   # fraction of image covered

    if engine == "lama" or (engine == "auto" and frac > 0.01):
        try:
            from .backends import inpaint_lama
            return inpaint_lama.erase(base, mask_u8)
        except Exception:
            pass  # backend missing → classical fallback below

    return _classical(base, mask_u8,
                      radius=params.get("radius", 3),
                      method=params.get("method", "telea"))
