"""Segmentation backend — turn a rough selection into a precise object mask.

Uses SAM (Segment Anything, Meta) with a BOX prompt derived from the user's
brushed selection: the box tells SAM "the thing to cut out is in here", and it
returns a pixel-perfect mask (e.g. the person). That mask then drives Erase
(LaMa) or a local adjustment.

CPU-friendly ViT-B model. The image embedding is cached per image, so the slow
part (encoding) happens once; subsequent box/point prompts are fast.

Lazily imported and optional — callers must handle ImportError/RuntimeError and
fall back (e.g. use the brushed mask as-is).
"""
from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np

MODEL_TYPE = "vit_b"
MODEL_FILE = "sam_vit_b_01ec64.pth"
MODEL_URL = f"https://dl.fbaipublicfiles.com/segment_anything/{MODEL_FILE}"
CACHE_DIR = Path.home() / ".cache" / "image-editor"
SAM_MAX_SIDE = 1024          # SAM resizes longest side to 1024 internally anyway

_PREDICTOR = None
_EMBED_SIG = None            # signature of the image currently encoded


def model_path() -> Path:
    return CACHE_DIR / MODEL_FILE


def available() -> bool:
    """True only if both the package and the downloaded weights are present."""
    try:
        import segment_anything  # noqa: F401
    except Exception:
        return False
    return model_path().exists()


def ensure_model() -> Path:
    """Download the checkpoint if missing (blocking)."""
    p = model_path()
    if not p.exists():
        import urllib.request
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".part")
        urllib.request.urlretrieve(MODEL_URL, tmp)
        os.replace(tmp, p)
    return p


def _get_predictor():
    global _PREDICTOR
    if _PREDICTOR is None:
        from segment_anything import SamPredictor, sam_model_registry
        sam = sam_model_registry[MODEL_TYPE](checkpoint=str(ensure_model()))
        sam.to("cpu")
        _PREDICTOR = SamPredictor(sam)
    return _PREDICTOR


def _sig(img: np.ndarray):
    return (img.shape, int(img[::37, ::37].sum()))


def _set_image(img_bgr: np.ndarray):
    """Encode the image once; reuse the embedding for later prompts."""
    global _EMBED_SIG
    predictor = _get_predictor()
    sig = _sig(img_bgr)
    if sig != _EMBED_SIG:
        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        predictor.set_image(rgb)
        _EMBED_SIG = sig
    return predictor


def segment(img_bgr: np.ndarray, box=None, points=None, labels=None) -> np.ndarray:
    """Return a float32 [0,1] mask for the object indicated by box/points.

    box: (x0, y0, x1, y1) in pixel coords of img_bgr, or None.
    points: list of (x, y); labels: list of 1 (foreground) / 0 (background).
    """
    # cap resolution for CPU speed; scale the prompt to match, mask back up later
    H, W = img_bgr.shape[:2]
    scale = min(1.0, SAM_MAX_SIDE / max(H, W))
    if scale < 1.0:
        small = cv2.resize(img_bgr, (int(W * scale), int(H * scale)), interpolation=cv2.INTER_AREA)
    else:
        small = img_bgr

    predictor = _set_image(small)

    box_arr = None
    if box is not None:
        box_arr = np.array([c * scale for c in box], dtype=np.float32)
    pts = lbls = None
    if points:
        pts = np.array([[x * scale, y * scale] for x, y in points], dtype=np.float32)
        lbls = np.array(labels if labels else [1] * len(points), dtype=np.int32)

    masks, scores, _ = predictor.predict(
        point_coords=pts, point_labels=lbls, box=box_arr, multimask_output=True)
    mask = masks[int(np.argmax(scores))].astype(np.float32)   # best of the 3

    if mask.shape[:2] != (H, W):
        mask = cv2.resize(mask, (W, H), interpolation=cv2.INTER_LINEAR)
    return np.clip(mask, 0.0, 1.0)
