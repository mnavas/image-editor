"""Unicode-safe image read/write.

cv2.imread / cv2.imwrite build on fopen() with the given path encoded via the
current codepage on Windows, so any non-ASCII filename (accented letters, ñ,
CJK, ...) fails silently — imread returns None, imwrite returns False, no
exception. Route through numpy + imdecode/imencode instead, which take a
byte buffer and never touch the OS path-encoding layer.

Ported verbatim from image_selector.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def imread(path) -> np.ndarray | None:
    """Unicode-safe replacement for cv2.imread (color, BGR)."""
    try:
        buf = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if buf.size == 0:
        return None
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def imread_unchanged(path) -> np.ndarray | None:
    """Read including an alpha channel if present (BGRA), Unicode-safe."""
    try:
        buf = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if buf.size == 0:
        return None
    return cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)


def imwrite(path, img: np.ndarray, params: list[int] | None = None) -> bool:
    """Unicode-safe replacement for cv2.imwrite.

    `params` is the usual cv2 encode-parameter list, e.g.
    [cv2.IMWRITE_JPEG_QUALITY, 95] — used to preserve export quality.
    """
    path = Path(path)
    ext = path.suffix
    if params:
        ok, buf = cv2.imencode(ext, img, params)
    else:
        ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    buf.tofile(str(path))
    return True
