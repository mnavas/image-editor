"""AppController — mediates Document (model) and widgets (view). Minimal Qt use.

Global tone sliders are a live recipe applied on top of the render (they stay out
of the undo history). Discrete edits — a brushed heal, or an adjustment restricted
to a brushed selection — become real layers in the Document (undoable).
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import cv2
import numpy as np

import img_io
from config import Config
from core import blend, ops
from core.document import Document
from core.layers import Layer
from core.mask import BrushStroke, Mask, RasterSource

# the full adjustment set — every one works globally AND on a selection
GLOBAL_ADJUST_KEYS = ["exposure", "brightness", "contrast", "highlights", "shadows",
                      "saturation", "vibrance", "temperature", "tint",
                      "clarity", "texture", "dehaze", "sharpen"]


def _default_grade() -> dict:
    return {
        "split_tone": {"sh_hue": 220.0, "sh_amt": 0.0, "hi_hue": 45.0, "hi_amt": 0.0},
        "hsl": {"red": 0.0, "yellow": 0.0, "green": 0.0, "cyan": 0.0, "blue": 0.0, "magenta": 0.0},
        "vignette": 0.0,
        "grain": 0.0,
    }


class AppController:
    def __init__(self, config: Config):
        self.config = config
        self.doc: Document | None = None
        self.path: Path | None = None
        self._orig_stat = None

        # live global adjustment recipe (not in undo history)
        self.adjust = {k: 0.0 for k in GLOBAL_ADJUST_KEYS}
        self.film = "original"
        self.curves = {"master": None, "r": None, "g": None, "b": None}
        self.grade = _default_grade()   # colour grade + finishing (whole-image)

        # local (selection) editing — mirrors the global set + its own curves
        self.mode = "global"                          # "global" | "selection"
        self.local = {k: 0.0 for k in GLOBAL_ADJUST_KEYS}
        self.local_curves = {"master": None, "r": None, "g": None, "b": None}
        self.local_feather = 0.02                     # border smoothing, frac of diagonal
        self.local_edge_aware = True

        # in-progress brush selection
        self._stroke: BrushStroke | None = None
        self.pending_mask: Mask | None = None
        self.brush_radius = 0.03   # fraction of diagonal

        # in-progress paste (insert another image)
        self.pending_paste: dict | None = None

        # in-progress reshape / liquify warp
        self.pending_warp = None                      # core.warp.WarpField | None
        self.warp_radius = 0.12                       # fraction of grid diagonal
        self.warp_strength = 0.5

    # --- file --------------------------------------------------------------

    def open(self, path) -> bool:
        img = img_io.imread(path)
        if img is None:
            return False
        self.doc = Document(base=img)
        self.path = Path(path)
        self._orig_stat = os.stat(path)
        self.adjust = {k: 0.0 for k in GLOBAL_ADJUST_KEYS}
        self.film = "original"
        self.curves = {"master": None, "r": None, "g": None, "b": None}
        self.grade = _default_grade()
        self.local = {k: 0.0 for k in GLOBAL_ADJUST_KEYS}
        self.local_curves = {"master": None, "r": None, "g": None, "b": None}
        self.mode = "global"
        self.pending_mask = None
        self.pending_paste = None
        self.pending_warp = None
        self.config.last_dir = str(self.path.parent)
        return True

    def proxy_scale(self) -> float:
        return self.doc.proxy_scale(self.config.proxy_max_side)

    # --- rendering ---------------------------------------------------------

    def _recipe(self, adjust: dict, lum_contrast: bool = False) -> list:
        """Turn an adjustment dict into an ordered (op, args) recipe.

        lum_contrast=True routes contrast through the luminance-only op so a local
        edit keeps its colour (used for selection edits, not the whole-image look).
        """
        recipe = []
        for k in GLOBAL_ADJUST_KEYS:
            v = adjust[k]
            if v:
                if k == "contrast" and lum_contrast:
                    recipe.append(("contrast_lum", {"value": v}))
                else:
                    arg = "stops" if k == "exposure" else "value"
                    recipe.append((k, {arg: v}))
        return recipe

    def _full_recipe(self, adjust: dict, curves: dict, lum_contrast: bool) -> list:
        """Adjust sliders + curves as one ordered recipe (for local edits)."""
        recipe = self._recipe(adjust, lum_contrast)
        if curves and any(curves.values()):
            recipe.append(("curves", dict(curves)))
        return recipe

    def _apply_global(self, img: np.ndarray) -> np.ndarray:
        out = img
        for name, args in self._recipe(self.adjust):
            out = ops.apply_op(out, name, args)
        c = self.curves
        if any(c.values()):
            out = ops.apply_op(out, "curves", dict(c))
        # colour grade
        g = self.grade
        if any(g["hsl"].values()):
            out = ops.apply_op(out, "hsl", dict(g["hsl"]))
        st = g["split_tone"]
        if st["sh_amt"] or st["hi_amt"]:
            out = ops.apply_op(out, "split_tone", dict(st))
        if self.film and self.film != "original":
            out = ops.apply_op(out, "film", {"name": self.film})
        # finishing
        if g["vignette"]:
            out = ops.apply_op(out, "vignette", {"value": g["vignette"]})
        if g["grain"]:
            out = ops.apply_op(out, "grain", {"value": g["grain"]})
        return out

    def _live_mask(self):
        """The pending selection mask with the CURRENT feather / edge settings."""
        if self.pending_mask is None or self.pending_mask.is_empty():
            return None
        return Mask(sources=list(self.pending_mask.sources),
                    feather=self.local_feather, edge_aware=self.local_edge_aware)

    def render(self, full: bool = False) -> np.ndarray:
        scale = 1.0 if full else self.proxy_scale()
        out = self.doc.render(scale)                    # committed layers

        # uncommitted local (selection) edit — rendered in the same position it
        # will occupy once committed (a layer), so preview == final result
        if self.mode == "selection":
            recipe = self._full_recipe(self.local, self.local_curves, lum_contrast=True)
            m = self._live_mask()
            if recipe and m is not None:
                effect = out
                for name, args in recipe:
                    effect = ops.apply_op(effect, name, args)
                mask = m.resolve(out.shape[0], out.shape[1], guide=out)
                out = blend.composite(out, effect, mask)

        # uncommitted paste preview
        if self.pending_paste:
            p = self.pending_paste
            out = blend.place_and_blend(out, p["src"], p["alpha"], p["cx"], p["cy"],
                                        p["scale"], p.get("mixed", False),
                                        p.get("match", True))

        # uncommitted reshape/liquify preview
        if self.pending_warp is not None and not self.pending_warp.is_empty():
            from core import warp
            out = warp.apply(out, self.pending_warp.fx, self.pending_warp.fy)

        # global grade (adjust / curves / film) applies on top of everything
        return self._apply_global(out)

    def current_mask_array(self, full: bool = False):
        """Resolve the pending brush mask (with live feather) for the overlay."""
        m = self._live_mask() if self.mode == "selection" else self.pending_mask
        if m is None or m.is_empty():
            return None
        base = self.doc.render(1.0 if full else self.proxy_scale())
        return m.resolve(base.shape[0], base.shape[1], guide=base)

    # --- global adjustments ------------------------------------------------

    def set_adjust(self, key: str, value: float):
        self.adjust[key] = value

    def set_film(self, name: str):
        self.film = name

    def reset_adjust(self):
        self.adjust = {k: 0.0 for k in GLOBAL_ADJUST_KEYS}
        self.film = "original"

    # --- colour grade + finishing (whole image) ----------------------------

    def set_split_tone(self, key: str, value: float):
        self.grade["split_tone"][key] = value

    def set_hsl(self, band: str, value: float):
        self.grade["hsl"][band] = value

    def set_finish(self, key: str, value: float):   # "vignette" | "grain"
        self.grade[key] = value

    def reset_grade(self):
        self.grade = _default_grade()

    def set_curves(self, master=None, r=None, g=None, b=None):
        self.curves = {"master": master, "r": r, "g": g, "b": b}

    # --- geometry: rotate + crop -------------------------------------------

    @staticmethod
    def _rotate_rect_cw(rect):
        """Map a normalised crop rect through a 90° clockwise image rotation."""
        x, y, w, h = rect
        return (1.0 - y - h, x, h, w)

    def rotate(self, cw: bool = True):
        if self.doc is None:
            return
        self.doc.push_history()
        step = 90 if cw else 270
        self.doc.rotation = (self.doc.rotation + step) % 360
        if self.doc.crop_rect is not None:
            r = self.doc.crop_rect
            for _ in range(step // 90):
                r = self._rotate_rect_cw(r)
            self.doc.crop_rect = r

    def apply_crop(self, drawn):
        """Compose a crop drawn on the CURRENT view onto any existing crop."""
        if self.doc is None:
            return
        dx, dy, dw, dh = drawn
        if dw <= 0.01 or dh <= 0.01:
            return
        ex, ey, ew, eh = self.doc.crop_rect or (0.0, 0.0, 1.0, 1.0)
        self.doc.push_history()
        self.doc.crop_rect = (ex + dx * ew, ey + dy * eh, dw * ew, dh * eh)

    def clear_crop(self):
        if self.doc and self.doc.crop_rect is not None:
            self.doc.push_history()
            self.doc.crop_rect = None

    # --- layer management --------------------------------------------------

    def layers(self):
        return self.doc.layers if self.doc else []

    def set_layer_visible(self, i: int, on: bool):
        if self.doc and 0 <= i < len(self.doc.layers):
            self.doc.push_history()
            self.doc.layers[i].visible = on

    def set_layer_opacity(self, i: int, opacity: float):
        if self.doc and 0 <= i < len(self.doc.layers):
            self.doc.layers[i].opacity = max(0.0, min(1.0, opacity))

    def remove_layer_at(self, i: int):
        if self.doc and 0 <= i < len(self.doc.layers):
            self.doc.push_history()
            del self.doc.layers[i]

    # --- local (selection) adjustments -------------------------------------

    def set_mode(self, mode: str):
        self.mode = mode

    def set_local(self, key: str, value: float):
        self.local[key] = value

    def set_feather(self, frac: float):
        self.local_feather = max(0.0, frac)

    def set_edge_aware(self, on: bool):
        self.local_edge_aware = bool(on)

    def set_local_curves(self, master=None, r=None, g=None, b=None):
        self.local_curves = {"master": master, "r": r, "g": g, "b": b}

    def reset_local(self):
        self.local = {k: 0.0 for k in GLOBAL_ADJUST_KEYS}
        self.local_curves = {"master": None, "r": None, "g": None, "b": None}

    def commit_local(self) -> bool:
        """Bake the live local edit into an undoable masked adjust_set layer."""
        recipe = self._full_recipe(self.local, self.local_curves, lum_contrast=True)
        if not recipe or self.pending_mask is None or self.pending_mask.is_empty():
            return False
        mask = Mask(sources=list(self.pending_mask.sources),
                    feather=self.local_feather, edge_aware=self.local_edge_aware)
        self.doc.add_layer(Layer(kind="adjust_set", name="Local adjust",
                                 params={"recipe": recipe}, mask=mask))
        self.reset_local()
        # keep the selection so the user can Undo and re-tune the SAME region
        # without re-brushing; Clear removes it explicitly.
        return True

    # --- brush selection ---------------------------------------------------

    def brush_start(self, x, y):
        self._stroke = BrushStroke(points=[(x, y)], radius=self.brush_radius)
        if self.pending_mask is None:
            self.pending_mask = Mask(feather=0.01, edge_aware=False)
        self.pending_mask.sources.append(self._stroke)

    def brush_point(self, x, y):
        if self._stroke is not None:
            self._stroke.points.append((x, y))

    def brush_end(self):
        self._stroke = None

    def clear_selection(self):
        self.pending_mask = None
        self._stroke = None

    # --- committing edits (undoable layers) --------------------------------

    def lama_available(self) -> bool:
        try:
            from core.backends import inpaint_lama
            return inpaint_lama.available()
        except Exception:
            return False

    def erase_selection(self) -> bool:
        """Add a heal layer that removes the brushed region."""
        if self.pending_mask is None or self.pending_mask.is_empty():
            return False
        mask = Mask(sources=list(self.pending_mask.sources),
                    feather=0.006, edge_aware=False)
        self.doc.add_layer(Layer(kind="heal", name="Erase",
                                 params={"engine": "auto"}, mask=mask))
        self.clear_selection()
        return True

    # --- segmentation (SAM) ------------------------------------------------

    def segmentation_available(self) -> bool:
        try:
            from core.backends import segment
            return segment.available()
        except Exception:
            return False

    def refine_to_subject(self) -> bool:
        """Replace the rough brush selection with a precise SAM mask of the
        object inside it (e.g. the person), using its bounding box as the prompt."""
        if self.pending_mask is None or self.pending_mask.is_empty():
            return False
        base = self.doc.render(1.0)                    # actual image content, full res
        h, w = base.shape[:2]
        cur = self.pending_mask.resolve(h, w, guide=base)
        ys, xs = np.where(cur > 0.5)
        if len(xs) == 0:
            return False
        # pad the box generously so SAM sees the whole object, not just the strokes
        pad_x, pad_y = int(0.05 * w), int(0.05 * h)
        box = (max(0, xs.min() - pad_x), max(0, ys.min() - pad_y),
               min(w, xs.max() + pad_x), min(h, ys.max() + pad_y))

        # brush points become positive prompts ("the object is here") — this is
        # what lets a few strokes select the whole person, not just the box centre.
        points = []
        for src in self.pending_mask.sources:
            for (nx, ny) in getattr(src, "points", []):
                points.append((nx * w, ny * h))
        if len(points) > 24:                           # subsample to keep prompt small
            step = len(points) // 24
            points = points[::step]

        from core.backends import segment
        person = segment.segment(base, box=box, points=points or None,
                                 labels=[1] * len(points) if points else None)
        if person.sum() < 10:
            return False
        self.pending_mask = Mask(sources=[RasterSource(person)],
                                 feather=0.004, edge_aware=False)
        return True

    def remove_person_in_selection(self) -> bool:
        """One shot: SAM-refine the selection to the person, then erase (LaMa)."""
        if not self.refine_to_subject():
            return False
        return self.erase_selection()

    # --- seamless paste (insert another image) -----------------------------

    def insert_image(self, path) -> bool:
        """Load an object image to paste. Uses its alpha channel as the mask if
        present (a cutout PNG); otherwise the whole rectangle is blended."""
        img = img_io.imread_unchanged(path)
        if img is None:
            return False
        if img.ndim == 3 and img.shape[2] == 4:
            alpha = img[:, :, 3].astype(np.float32) / 255.0
            src = img[:, :, :3]
        else:
            if img.ndim == 2:
                src = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            else:
                src = img[:, :, :3]
            alpha = np.ones(src.shape[:2], np.float32)
        self.pending_paste = {"src": src, "alpha": alpha, "cx": 0.5, "cy": 0.5,
                              "scale": 0.4, "mixed": False, "match": True}
        return True

    def set_paste_param(self, key: str, value):
        if self.pending_paste is not None:
            self.pending_paste[key] = value

    def cancel_paste(self):
        self.pending_paste = None

    def commit_paste(self) -> bool:
        if self.pending_paste is None:
            return False
        self.doc.add_layer(Layer(kind="paste", name="Paste",
                                 params=dict(self.pending_paste)))
        self.pending_paste = None
        return True

    # --- reshape / liquify (body slimming) ---------------------------------

    def warp_stroke(self, x0: float, y0: float, x1: float, y1: float):
        """Push pixels near (x0,y0) toward (x1,y1). Coords normalised [0,1]."""
        if self.doc is None:
            return
        if self.pending_warp is None:
            from core.warp import WarpField
            h, w = self.doc.base.shape[:2]
            self.pending_warp = WarpField.for_aspect(h, w)
        self.pending_warp.push(x0, y0, x1 - x0, y1 - y0,
                               radius=self.warp_radius, strength=self.warp_strength)

    def set_warp_radius(self, frac: float):
        self.warp_radius = max(0.01, frac)

    def set_warp_strength(self, s: float):
        self.warp_strength = max(0.0, min(1.0, s))

    def cancel_warp(self):
        self.pending_warp = None

    def commit_warp(self) -> bool:
        if self.pending_warp is None or self.pending_warp.is_empty():
            return False
        self.doc.add_layer(Layer(kind="warp", name="Reshape",
                                 params={"fx": self.pending_warp.fx.copy(),
                                         "fy": self.pending_warp.fy.copy()}))
        self.pending_warp = None
        return True

    def undo(self) -> bool:
        return self.doc.undo() if self.doc else False

    def redo(self) -> bool:
        return self.doc.redo() if self.doc else False

    # --- project (.iedit) --------------------------------------------------

    def save_project(self, path) -> bool:
        if self.doc is None:
            return False
        from core import project
        return project.save(self, path)

    def load_project(self, path) -> bool:
        from core import project
        ok = project.load(self, path)
        if ok:
            self._orig_stat = os.stat(self.path) if self.path and self.path.exists() else None
            self.pending_mask = None
        return ok

    # --- save --------------------------------------------------------------

    def save(self, target_path) -> bool:
        """Render full-res and save atomically, preserving the original mtime."""
        if self.doc is None:
            return False
        target_path = Path(target_path)
        out = self.render(full=True)

        ext = target_path.suffix.lower()
        params = []
        if ext in (".jpg", ".jpeg"):
            params = [cv2.IMWRITE_JPEG_QUALITY, int(self.config.jpeg_quality)]
        elif ext == ".png":
            params = [cv2.IMWRITE_PNG_COMPRESSION, 3]

        fd, tmp = tempfile.mkstemp(suffix=ext, dir=str(target_path.parent))
        os.close(fd)
        try:
            if not img_io.imwrite(tmp, out, params):
                os.unlink(tmp)
                return False
            shutil.move(tmp, str(target_path))
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            return False

        if self._orig_stat is not None:
            try:
                os.utime(target_path, (self._orig_stat.st_atime, self._orig_stat.st_mtime))
            except OSError:
                pass
        self.config.last_dir = str(target_path.parent)
        return True
