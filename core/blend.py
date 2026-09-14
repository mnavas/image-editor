"""Pixel compositing: alpha blend + blend modes + gradient-domain paste.

Pure numpy/opencv. All images are BGR uint8 unless noted. Masks are float32
in [0, 1] with the same HxW as the image.
"""
from __future__ import annotations

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Blend modes — operate on float arrays in [0, 1]
# ---------------------------------------------------------------------------


def _normal(b, e):
    return e


def _multiply(b, e):
    return b * e


def _screen(b, e):
    return 1.0 - (1.0 - b) * (1.0 - e)


def _overlay(b, e):
    return np.where(b <= 0.5, 2.0 * b * e, 1.0 - 2.0 * (1.0 - b) * (1.0 - e))


BLEND_MODES = {
    "normal": _normal,
    "multiply": _multiply,
    "screen": _screen,
    "overlay": _overlay,
}


def composite(base: np.ndarray, effect: np.ndarray,
              mask: np.ndarray | None = None,
              mode: str = "normal", opacity: float = 1.0) -> np.ndarray:
    """Blend `effect` onto `base` through `mask` at `opacity`.

    base, effect: BGR uint8, same shape.
    mask: float32 HxW in [0,1], or None = fully applied everywhere.
    Returns BGR uint8.
    """
    if opacity <= 0.0:
        return base
    b = base.astype(np.float32) / 255.0
    e = effect.astype(np.float32) / 255.0

    blended = BLEND_MODES.get(mode, _normal)(b, e)

    # per-pixel alpha = mask * opacity
    if mask is None:
        alpha = np.float32(opacity)
    else:
        alpha = (mask * opacity).astype(np.float32)[:, :, None]

    out = b * (1.0 - alpha) + blended * alpha
    return np.clip(out * 255.0, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Gradient-domain paste (Poisson / seamless cloning)
# ---------------------------------------------------------------------------


def seamless_paste(src: np.ndarray, dst: np.ndarray, mask: np.ndarray,
                   center: tuple[int, int] | None = None,
                   mixed: bool = False) -> np.ndarray:
    """Poisson-blend `src` into `dst` where `mask` is set.

    Wraps cv2.seamlessClone (Perez et al. 2003). `mask` may be float [0,1] or
    uint8; it is binarised for the clone. `center` defaults to the mask centroid.
    """
    m = mask
    if m.dtype != np.uint8:
        m = (np.clip(m, 0, 1) * 255).astype(np.uint8)
    if m.ndim == 3:
        m = cv2.cvtColor(m, cv2.COLOR_BGR2GRAY)

    if center is None:
        ys, xs = np.where(m > 0)
        if len(xs) == 0:
            return dst
        center = (int(xs.mean()), int(ys.mean()))

    flags = cv2.MIXED_CLONE if mixed else cv2.NORMAL_CLONE
    return cv2.seamlessClone(src, dst, m, center, flags)


# ---------------------------------------------------------------------------
# Colour / tone matching — make a region belong to its surroundings
# ---------------------------------------------------------------------------


def place_and_blend(base: np.ndarray, src: np.ndarray, alpha: np.ndarray,
                    cx: float, cy: float, scale: float,
                    mixed: bool = False, match: bool = True) -> np.ndarray:
    """Paste `src` into `base` at normalised centre (cx,cy), sized to `scale` of
    the base width, Poisson-blended so the seam disappears.

    src: BGR object image. alpha: float [0,1] object mask (ones = whole rectangle).
    scale: pasted width as a fraction of base width.
    match: colour-match the object to the destination patch first.
    Returns BGR uint8 (same size as base). Falls back to a feathered alpha
    composite if seamlessClone can't run (e.g. patch at the very edge).
    """
    H, W = base.shape[:2]
    tw = max(2, int(scale * W))
    th = max(2, int(round(tw * src.shape[0] / src.shape[1])))
    if tw >= W or th >= H:                      # object bigger than canvas → clamp
        f = min((W - 2) / tw, (H - 2) / th)
        tw, th = max(2, int(tw * f)), max(2, int(th * f))
    src_r = cv2.resize(src, (tw, th), interpolation=cv2.INTER_AREA)
    alpha_r = cv2.resize(alpha, (tw, th), interpolation=cv2.INTER_LINEAR)

    hw, hh = tw // 2, th // 2
    px = min(max(int(cx * W), hw + 1), W - hw - 1)
    py = min(max(int(cy * H), hh + 1), H - hh - 1)

    m = (alpha_r > 0.5).astype(np.uint8) * 255
    if m.sum() == 0:
        return base

    if match:
        y0, x0 = py - hh, px - hw
        dst_patch = base[y0:y0 + th, x0:x0 + tw]
        if dst_patch.shape[:2] == src_r.shape[:2]:
            src_r = match_color(src_r, dst_patch)

    try:
        flags = cv2.MIXED_CLONE if mixed else cv2.NORMAL_CLONE
        return cv2.seamlessClone(src_r, base, m, (px, py), flags)
    except cv2.error:
        # fallback: feathered alpha composite
        out = base.copy()
        y0, x0 = py - hh, px - hw
        a = cv2.GaussianBlur(alpha_r, (0, 0), 1.5)[:, :, None]
        roi = out[y0:y0 + th, x0:x0 + tw].astype(np.float32)
        out[y0:y0 + th, x0:x0 + tw] = (roi * (1 - a) + src_r.astype(np.float32) * a).astype(np.uint8)
        return out


def match_color(region: np.ndarray, reference: np.ndarray,
                ref_mask: np.ndarray | None = None) -> np.ndarray:
    """Reinhard Lab colour transfer: shift `region` to the mean/std of `reference`.

    region, reference: BGR uint8. `ref_mask` (float [0,1] or bool) restricts which
    reference pixels count (e.g. the ring around a hole). Returns BGR uint8.
    """
    src = cv2.cvtColor(region, cv2.COLOR_BGR2LAB).astype(np.float32)
    ref = cv2.cvtColor(reference, cv2.COLOR_BGR2LAB).astype(np.float32)

    if ref_mask is not None:
        sel = ref_mask > 0.5 if ref_mask.dtype != bool else ref_mask
        ref_pixels = ref[sel]
        if ref_pixels.size == 0:
            return region
        ref_mean = ref_pixels.mean(axis=0)
        ref_std = ref_pixels.std(axis=0)
    else:
        ref_mean = ref.reshape(-1, 3).mean(axis=0)
        ref_std = ref.reshape(-1, 3).std(axis=0)

    src_flat = src.reshape(-1, 3)
    src_mean = src_flat.mean(axis=0)
    src_std = src_flat.std(axis=0)
    src_std[src_std == 0] = 1.0

    out = (src - src_mean) * (ref_std / src_std) + ref_mean
    out = np.clip(out, 0, 255).astype(np.uint8)
    return cv2.cvtColor(out, cv2.COLOR_LAB2BGR)
