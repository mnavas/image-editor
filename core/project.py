"""`.iedit` project files — save/reopen a non-destructive edit.

Serialises the whole editing state to JSON: the source image path, geometry
(rotation/crop), the layer stack (with masks), and the global adjust / curves /
film recipe. The exported picture stays a separate flat file; the `.iedit`
sidecar lets you reopen and keep tweaking later.

Raster masks (from SAM) are embedded as base64 PNG so a segmented selection
survives a save/reload.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import cv2
import numpy as np

from core import mask as mask_mod
from core.layers import Layer
from core.mask import (BrushStroke, EllipseShape, LinearGradient, LuminanceRange,
                       Mask, RadialGradient, RasterSource)

FORMAT_VERSION = 1

# geometric source dataclasses serialise field-by-field; RasterSource is special
_GEOM_SOURCES = {
    "BrushStroke": BrushStroke, "EllipseShape": EllipseShape,
    "LinearGradient": LinearGradient, "RadialGradient": RadialGradient,
    "LuminanceRange": LuminanceRange,
}


# --- masks -----------------------------------------------------------------

def _source_to_dict(src) -> dict:
    name = type(src).__name__
    if name == "RasterSource":
        u8 = (np.clip(src.data, 0, 1) * 255).astype(np.uint8)
        ok, buf = cv2.imencode(".png", u8)
        return {"type": "RasterSource", "op": src.op,
                "data": base64.b64encode(buf.tobytes()).decode()}
    d = {"type": name}
    d.update(vars(src))
    return d


def _dict_to_source(d: dict):
    t = d.pop("type")
    if t == "RasterSource":
        raw = base64.b64decode(d["data"])
        arr = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
        return RasterSource(data=arr.astype(np.float32) / 255.0, op=d.get("op", "add"))
    cls = _GEOM_SOURCES[t]
    # JSON turns tuples/points into lists; the dataclasses accept lists fine
    return cls(**d)


def _mask_to_dict(m: Mask | None):
    if m is None:
        return None
    return {"invert": m.invert, "feather": m.feather, "edge_aware": m.edge_aware,
            "sources": [_source_to_dict(s) for s in m.sources]}


def _dict_to_mask(d) -> Mask | None:
    if d is None:
        return None
    return Mask(sources=[_dict_to_source(s) for s in d["sources"]],
                invert=d.get("invert", False), feather=d.get("feather", 0.0),
                edge_aware=d.get("edge_aware", False))


# --- layers ----------------------------------------------------------------

def _img_to_b64(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img)
    return base64.b64encode(buf.tobytes()).decode()


def _b64_to_img(s: str, flags=cv2.IMREAD_UNCHANGED) -> np.ndarray:
    raw = base64.b64decode(s)
    return cv2.imdecode(np.frombuffer(raw, np.uint8), flags)


def _arr_to_b64(a: np.ndarray) -> str:
    import io
    buf = io.BytesIO()
    np.save(buf, a.astype(np.float32))
    return base64.b64encode(buf.getvalue()).decode()


def _b64_to_arr(s: str) -> np.ndarray:
    import io
    return np.load(io.BytesIO(base64.b64decode(s)))


def _params_to_dict(kind: str, params: dict) -> dict:
    """Layers whose params carry numpy arrays embed them (PNG for images, npy for fields)."""
    if kind == "paste":
        out = {k: v for k, v in params.items() if k not in ("src", "alpha")}
        out["src"] = _img_to_b64(params["src"])
        out["alpha"] = _img_to_b64((np.clip(params["alpha"], 0, 1) * 255).astype(np.uint8))
        return out
    if kind == "warp":
        return {"fx": _arr_to_b64(params["fx"]), "fy": _arr_to_b64(params["fy"])}
    return params


def _dict_to_params(kind: str, d: dict) -> dict:
    if kind == "paste":
        out = dict(d)
        out["src"] = _b64_to_img(d["src"], cv2.IMREAD_COLOR)
        out["alpha"] = _b64_to_img(d["alpha"], cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255.0
        return out
    if kind == "warp":
        return {"fx": _b64_to_arr(d["fx"]), "fy": _b64_to_arr(d["fy"])}
    return d


def _layer_to_dict(layer: Layer) -> dict:
    return {"kind": layer.kind, "name": layer.name,
            "params": _params_to_dict(layer.kind, layer.params),
            "blend_mode": layer.blend_mode, "opacity": layer.opacity,
            "visible": layer.visible, "mask": _mask_to_dict(layer.mask)}


def _dict_to_layer(d: dict) -> Layer:
    return Layer(kind=d["kind"], name=d.get("name", ""),
                 params=_dict_to_params(d["kind"], d.get("params", {})),
                 blend_mode=d.get("blend_mode", "normal"),
                 opacity=d.get("opacity", 1.0), visible=d.get("visible", True),
                 mask=_dict_to_mask(d.get("mask")))


# --- top level -------------------------------------------------------------

def to_dict(ctl) -> dict:
    doc = ctl.doc
    return {
        "version": FORMAT_VERSION,
        "source": str(ctl.path) if ctl.path else "",
        "rotation": doc.rotation,
        "crop_rect": list(doc.crop_rect) if doc.crop_rect else None,
        "adjust": dict(ctl.adjust),
        "film": ctl.film,
        "curves": ctl.curves,
        "layers": [_layer_to_dict(l) for l in doc.layers],
    }


def save(ctl, path) -> bool:
    path = Path(path)
    path.write_text(json.dumps(to_dict(ctl), indent=2))
    return True


def load(ctl, path) -> bool:
    """Populate `ctl` from an `.iedit` file. Returns False if the source is missing."""
    data = json.loads(Path(path).read_text())
    if not ctl.open(data.get("source", "")):
        return False
    doc = ctl.doc
    doc.rotation = data.get("rotation", 0)
    cr = data.get("crop_rect")
    doc.crop_rect = tuple(cr) if cr else None
    doc.layers = [_dict_to_layer(d) for d in data.get("layers", [])]
    ctl.adjust = {**ctl.adjust, **data.get("adjust", {})}
    ctl.film = data.get("film", "original")
    ctl.curves = data.get("curves", {"master": None, "r": None, "g": None, "b": None})
    return True
