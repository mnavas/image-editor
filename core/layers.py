"""Layer types for the non-destructive document.

A Layer produces an `effect` image from an incoming base, then the document
composites that effect back through the layer's mask + blend mode. Keeping the
"produce effect" and "composite" steps separate is what makes every op maskable
by the same code path (a global adjustment is just a layer with no mask).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import blend, ops
from .mask import Mask


def _base_signature(base: np.ndarray) -> tuple:
    """Cheap, stable fingerprint of an image for caching (shape + subsample)."""
    return (base.shape, hash(base[::41, ::41].tobytes()))


@dataclass
class Layer:
    kind: str                          # "adjust" | "heal" | "pixel"
    name: str = ""                     # user-facing label
    params: dict = field(default_factory=dict)
    mask: Mask | None = None
    blend_mode: str = "normal"
    opacity: float = 1.0
    visible: bool = True
    # cache for expensive effects (heal/LaMa): {signature: effect_image}
    _cache: dict = field(default_factory=dict, repr=False, compare=False)

    # --- effect production -------------------------------------------------

    def _effect(self, base: np.ndarray) -> np.ndarray:
        if self.kind == "adjust":
            return ops.apply_op(base, self.params.get("op", ""), self.params.get("args", {}))
        if self.kind == "adjust_set":
            out = base
            for name, args in self.params.get("recipe", []):
                out = ops.apply_op(out, name, args)
            return out
        if self.kind in ("heal", "paste", "warp"):
            sig = (_base_signature(base), self.kind, repr(self.params), repr(self.mask))
            if sig not in self._cache:
                if len(self._cache) >= 4:      # keep a few (proxy + full res, etc.)
                    self._cache.pop(next(iter(self._cache)))
                self._cache[sig] = self._expensive_effect(base)
            return self._cache[sig]
        if self.kind == "pixel":
            # params["rgba"] pre-placed at full canvas size (BGR), params["alpha"] HxW
            return self.params.get("rgba", base)
        return base

    def _expensive_effect(self, base: np.ndarray) -> np.ndarray:
        if self.kind == "heal":
            from . import heal   # lazy: heal may pull optional backends
            return heal.apply(base, self.params, self._resolve_mask(base))
        if self.kind == "paste":
            from . import blend
            p = self.params
            return blend.place_and_blend(base, p["src"], p["alpha"], p["cx"], p["cy"],
                                         p["scale"], p.get("mixed", False),
                                         p.get("match", True))
        if self.kind == "warp":
            from . import warp
            return warp.apply(base, self.params["fx"], self.params["fy"])
        return base

    def __deepcopy__(self, memo):
        # copy everything EXCEPT the (large, disposable) render cache — keeps the
        # undo history from holding megabytes of cached heal results.
        import copy as _copy
        clone = Layer(
            kind=self.kind, name=self.name,
            params=_copy.deepcopy(self.params, memo),
            mask=_copy.deepcopy(self.mask, memo),
            blend_mode=self.blend_mode, opacity=self.opacity, visible=self.visible,
        )
        return clone

    def _resolve_mask(self, base: np.ndarray) -> np.ndarray | None:
        if self.mask is None or self.mask.is_empty():
            return None
        h, w = base.shape[:2]
        return self.mask.resolve(h, w, guide=base)

    # --- compositing -------------------------------------------------------

    def render_onto(self, base: np.ndarray) -> np.ndarray:
        """Apply this layer to `base`, return the new base."""
        if not self.visible or self.opacity <= 0:
            return base
        effect = self._effect(base)

        # heal already returns a fully-composited image (fills the hole);
        # blend it through the mask so opacity/feather still apply.
        mask = self._resolve_mask(base)
        return blend.composite(base, effect, mask, self.blend_mode, self.opacity)
