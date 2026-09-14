"""LaMa large-mask inpainting backend (the "erase a person" engine).

Uses `simple-lama-inpainting` (LaMa model, ~200 MB, downloaded on first use).
Runs on CPU in a few seconds; uses GPU automatically if torch sees one.

The model is loaded lazily and cached, so the first erase pays the load cost and
subsequent ones are fast. If the package/model isn't available, `erase()` raises
and core/heal.py falls back to classical cv2.inpaint.
"""
from __future__ import annotations

import cv2
import numpy as np

_MODEL = None

# LaMa cost scales with pixel count. Run at most this long-side on CPU, then paste
# the fill back into the full-res image (only masked pixels are used downstream, so
# full resolution is preserved everywhere except the synthesized patch).
LAMA_MAX_SIDE = 1280


def available() -> bool:
    try:
        import simple_lama_inpainting  # noqa: F401
        return True
    except Exception:
        return False


def _get_model():
    global _MODEL
    if _MODEL is None:
        from simple_lama_inpainting import SimpleLama
        _MODEL = SimpleLama()   # downloads weights on first construction
    return _MODEL


def erase(img: np.ndarray, mask_u8: np.ndarray) -> np.ndarray:
    """Fill the white region of mask_u8 in `img` (BGR uint8) with plausible content.

    Returns a BGR uint8 image. LaMa already matches surrounding structure; we run
    a light Reinhard colour-match on the filled region against the ring around the
    hole so the fill also matches colour/exposure exactly.
    """
    from PIL import Image

    model = _get_model()
    H, W = img.shape[:2]

    # work at a capped resolution for speed/memory
    scale = min(1.0, LAMA_MAX_SIDE / max(H, W))
    if scale < 1.0:
        wimg = cv2.resize(img, (int(W * scale), int(H * scale)), interpolation=cv2.INTER_AREA)
        wmask = cv2.resize(mask_u8, (int(W * scale), int(H * scale)), interpolation=cv2.INTER_NEAREST)
    else:
        wimg, wmask = img, mask_u8

    rgb = cv2.cvtColor(wimg, cv2.COLOR_BGR2RGB)
    result = model(Image.fromarray(rgb), Image.fromarray(wmask).convert("L"))
    out_rgb = np.array(result)                        # LaMa pads to /8 internally

    # back to full resolution
    out = cv2.cvtColor(out_rgb, cv2.COLOR_RGB2BGR)
    if out.shape[:2] != (H, W):
        out = cv2.resize(out, (W, H), interpolation=cv2.INTER_LANCZOS4)

    return _color_match_fill(img, out, mask_u8)


def _color_match_fill(orig: np.ndarray, filled: np.ndarray,
                      mask_u8: np.ndarray) -> np.ndarray:
    """Nudge the filled hole toward the colour stats of the ring around it."""
    from .. import blend

    hole = mask_u8 > 0
    # ring = dilated mask minus the hole itself
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
    ring = (cv2.dilate(mask_u8, k) > 0) & (~hole)
    if ring.sum() < 50:
        return filled

    matched = blend.match_color(filled, orig, ref_mask=ring.astype(np.float32))
    out = filled.copy()
    out[hole] = matched[hole]
    return out
