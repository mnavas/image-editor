# image-editor — Architecture & Developer Guide

## Overview

image-editor separates a **Qt-free editing core** from the **Qt view**, mediated by
a controller — the same discipline as image_selector, so the core can also back a
headless/MCP process.

- **Model / engine** — everything in `core/` (pure NumPy/OpenCV, zero Qt imports)
- **Controller** — `app_controller.py`
- **View** — `main.py` + everything in `widgets/`

The design rule: **every image operation takes a NumPy array and returns one.** The
UI only assembles state and displays results.

---

## Module map

```
image-editor/
├── main.py                 Entry point — boots Qt, wires controller + window
├── config.py               JSON config (~/.config/image-editor/)
├── img_io.py               Unicode-safe imread/imwrite (+ alpha-aware read, quality params)
├── app_controller.py       Mediates Document ↔ widgets; global/local edit state
├── core/                   Qt-free engine
│   ├── document.py         Document = base image + layer stack; render(scale)
│   ├── layers.py           Layer types (adjust / adjust_set / heal / paste / warp) + compositing
│   ├── mask.py             Mask recipes: brush, shapes, gradients, luminance, RasterSource
│   ├── ops.py              Per-pixel adjustments + op registry
│   ├── curves.py           Monotone-spline (PCHIP) → 256-LUT
│   ├── film_luts.py        Camera profiles + Fujifilm-inspired film simulations
│   ├── blend.py            Composite + blend modes, seamless paste, colour match
│   ├── heal.py             Inpaint dispatch (classical → LaMa)
│   ├── warp.py             Liquify / reshape displacement field
│   ├── project.py          .iedit save/load (JSON + embedded arrays)
│   └── backends/           Optional ML, lazily imported
│       ├── segment.py      SAM box/point segmentation
│       └── inpaint_lama.py LaMa erase
└── widgets/
    ├── main_window.py      Window, toolbar, tabbed rail, background jobs
    ├── canvas.py           Zoom/pan preview + brush / crop / warp tools + selection overlay
    └── curve_editor.py     Draggable tone-curve widget
```

---

## The document model

```python
@dataclass
class Document:
    base: np.ndarray                 # immutable original, BGR uint8, full res
    layers: list[Layer]              # ordered, bottom → top
    crop_rect: tuple | None          # normalised, post-rotation
    rotation: int                    # 0 / 90 / 180 / 270
    # + undo/redo history over (layers, crop, rotation)
```

A **Layer** produces an *effect* image, which the document composites back through
the layer's **mask** and blend mode — so a global adjustment and a local one share
one code path (global = no mask). Expensive layers (`heal`, `paste`, `warp`) cache
their result per resolution.

### Masks are resolution-independent recipes

`Mask` holds a list of sources (brush strokes, shapes, gradients, luminance ranges,
or a `RasterSource` from SAM) in **normalised** coordinates, plus feather and an
optional edge-aware (guided-filter) refine. `resolve(h, w)` rasterizes to a float
`[0,1]` map at any resolution — so a mask drives both the proxy preview and the
full-res export.

---

## The render pipeline

`AppController.render(full=False)` is the single source of truth, and it renders
pending previews in the **same position they'll occupy once committed**, so preview
== final:

```
base = Document.render(scale)          # committed layers, geometry
  → pending local-selection edit       # (uncommitted) masked adjust_set
  → pending paste                       # (uncommitted) seamless clone
  → pending reshape/warp                # (uncommitted) remap
  → global grade                        # adjust sliders + curves + film look
```

`scale < 1` renders a fast proxy for live preview; **Save always calls
`render(full=True)`** and writes atomically (tempfile → move) with the original
timestamp preserved.

---

## Optional ML backends

`core/backends/` is lazily imported and always guarded — if a package or model is
missing, the feature degrades (Erase → classical inpaint; Remove person →
unavailable). Heavy calls run on a `QThread` (`_RenderWorker`) so the UI never
freezes. See [installation.md](installation.md) for the CPU-only install recipes
and the licence note.

---

## Testing

`tests/test_core.py` exercises the Qt-free core with pytest: curves, ops, masks,
compositing, geometry, layers, project round-trips, and (when the backends are
installed) a full SAM→LaMa person removal.

```bash
.venv/bin/python -m pytest tests -q
```

---

## Further reading

- [analysis.md](analysis.md) — the feature research (how each tool implements erasing,
  local adjustments, curves, blending) and the tech-stack rationale.
- [plan.md](plan.md) — the phased build plan.
- [changelog.md](changelog.md) — what's been built, newest first.
