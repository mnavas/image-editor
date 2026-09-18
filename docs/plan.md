# image-editor — Implementation Plan

> Companion to [analysis.md](analysis.md). Turns the research into a concrete,
> phased build. Reuses `image_selector`'s conventions: PySide6/Qt UI, Qt-decoupled
> pure-array ops, atomic Unicode-safe full-resolution save.
>
> Date: 2026-09-11 · Status: planning

---

## Guiding constraints (from analysis §0)

1. **Full-resolution, non-destructive** — preview on a proxy, always render the
   final at native resolution with format/quality control.
2. **Photoshop-capable, phone-app-simple** — power (masks/layers/inpainting) lives
   under a direct-on-image UI. Every feature ships an algorithm *and* a simple
   interaction, together.
3. **Models are optional** — phases 1–5 run with zero ML deps; ML degrades
   gracefully when a model/GPU is absent.

---

## Target architecture

MVC like `image_selector`, but the "model" grows from a flat `EditState` into a
`Document` (layer stack). The **core is Qt-free** so it can back an MCP server later.

```
image-editor/
├── main.py                   # entry point — boots Qt, opens Document, wires window
├── config.py                 # JSON config (~/.config/image-editor/)
├── img_io.py                 # COPIED from image_selector — Unicode-safe imread/imwrite
├── core/                     # zero Qt imports — pure numpy/opencv
│   ├── document.py           # Document, layer stack, render(), history
│   ├── layers.py             # Layer types (Adjustment, Heal, Pixel, ...)
│   ├── mask.py               # Mask type + sources (shapes, brush, parametric, ML)
│   ├── ops.py                # ported edit_ops.py — brightness/contrast/curves/...
│   ├── film_luts.py          # COPIED from image_selector (film sims as ops)
│   ├── curves.py             # monotone-spline → 256-LUT
│   ├── blend.py              # alpha composite, blend modes, seamlessClone, colour-match
│   ├── heal.py               # inpaint dispatch: telea | patchmatch | lama
│   ├── render.py             # proxy vs full-res rendering, export (quality/format)
│   └── backends/             # ML wrappers, lazy-imported, optional
│       ├── segment.py        # SAM 2 + rembg  (returns a Mask)
│       └── inpaint_lama.py   # LaMa erase (+ optional SD)
├── widgets/                  # Qt view layer
│   ├── main_window.py        # window, toolbar, keyboard, open/save
│   ├── canvas.py             # zoom/pan preview (port preview_widget.py) + gestures
│   ├── tool_overlay.py       # on-canvas brush/shape/handles (port crop overlay)
│   ├── tools_panel.py        # the simple tool rail (Erase, Adjust, Curves, Crop...)
│   └── adjust_panel.py       # slider/curve UI for the active tool
├── app_controller.py         # actions ↔ Document ↔ widgets
├── requirements.txt
└── docs/{analysis.md, plan.md, changelog.md, versioning/...}
```

### Core data model

```python
# core/mask.py
@dataclass
class Mask:
    data: np.ndarray            # float32 HxW in [0,1], image-resolution (or None = all-ones)
    invert: bool = False
    feather_px: float = 0.0     # gaussian fallback
    edge_aware: bool = False    # guided-filter refine against image
    def resolve(self, img) -> np.ndarray: ...   # -> concrete float32 HxW in [0,1]

# core/layers.py
@dataclass
class Layer:
    kind: str                   # "adjust" | "heal" | "pixel"
    params: dict                # op name + values, or heal engine, or rgba+transform
    mask: Mask | None = None
    blend_mode: str = "normal"
    opacity: float = 1.0
    visible: bool = True

# core/document.py
@dataclass
class Document:
    base: np.ndarray            # immutable original BGR (full res)
    layers: list[Layer]
    crop_rect: tuple | None = None
    rotation: int = 0
    def render(self, scale: float = 1.0) -> np.ndarray: ...   # proxy or full-res
```

`render()` = start from (rotated, cropped) base, apply each visible layer
top-to-bottom via `blend.composite(base, effect, mask, mode, opacity)`. The
**same method** renders the proxy (scale<1, for live preview) and the full-res
export (scale=1) — guaranteeing what you see is what you save.

---

## Phase 0 — Project scaffold  *(0.5 day)*

- `main.py`, `config.py`, `img_io.py` (copy), `requirements.txt`
  (`PySide6`, `opencv-contrib-python`, `numpy`, `Pillow`, `send2trash`).
- `widgets/main_window.py` + `widgets/canvas.py`: open an image, zoom/pan/fit
  (port `preview_widget.py`), **Save As** with format + JPEG-quality control
  (atomic tempfile → `shutil.move` → `os.utime`, ported from `image_selector`).
- **Milestone:** open a 24 MP photo, zoom/pan smoothly, save a full-res copy at
  chosen quality. *This alone already beats the phone-app resolution loss.*

## Phase 1 — Document, layers, compositor, masks  *(3–4 days)* — the spine

- `core/document.py`, `core/layers.py`, `core/blend.py` (alpha composite + core
  blend modes: normal/multiply/screen/overlay).
- `core/mask.py` with sources: **brush**, **circle/ellipse**, **linear/radial
  gradient**, **parametric/luminosity** (mask from luminance sliders).
- Feathering: `cv2.GaussianBlur` (cheap) + **edge-aware** via
  `cv2.ximgproc.guidedFilter` using the image as guide.
- `widgets/tool_overlay.py`: paint/drag masks directly on the canvas; live proxy
  preview with the 50 ms debounce pattern from `image_selector`.
- Undo/redo stack over layer operations.
- **Milestone:** brush a region, see a visible mask, feather it edge-aware.

## Phase 2 — Local adjustments  *(2 days)*

- Port `edit_ops.py` → `core/ops.py` and `film_luts.py` (unchanged math).
- Wrap each op as an **AdjustmentLayer**; global = all-ones mask (one code path).
- `widgets/adjust_panel.py`: sliders for exposure/contrast/saturation/shadows/
  highlights + film-sim picker.
- Simple UX: "drag on the sky → it gets a darkened-sky adjust layer with an
  auto luminosity+gradient mask" — no layer jargon exposed.
- **Milestone:** apply contrast to only the shadows; brighten only a brushed area.

## Phase 3 — Curves  *(1–2 days)*

- `core/curves.py`: control points → monotone cubic spline → 256-LUT
  (hand-rolled PCHIP to avoid the SciPy dep) → `cv2.LUT`.
- Master RGB + per-channel R/G/B via a single `(256,1,3)` LUT; Lab L/a/b mode later.
- Curve editor widget (draggable points on a histogram backdrop); curves are just
  another op → automatically maskable + layerable.
- **Milestone:** S-curve contrast; per-channel colour grade; masked curve.

## Phase 4 — Classical heal / erase  *(1–2 days)*

- `core/heal.py`: dispatch by mask size → `cv2.inpaint` (Telea) for tiny defects,
  **PatchMatch** for textured self-similar backgrounds.
- HealLayer stores the mask + engine; result cached, re-render aware.
- **Milestone:** remove dust/blemishes/small distractions cleanly, CPU-only.

## Phase 5 — Seamless paste + colour match  *(2 days)*

- `core/blend.py`: `cv2.seamlessClone` (NORMAL/MIXED) for pasted regions;
  Lab mean/std colour transfer + `skimage.exposure.match_histograms`
  (add `scikit-image`) to make a filled/pasted region match its surroundings.
- Auto "match colour to surroundings" runs after any heal/paste, then feather.
- **Milestone:** paste an object from another photo with an invisible seam;
  colour-match a patch.

> **Phases 0–5 ship a genuinely useful editor with zero ML dependencies.**
> Everything below is additive and optional.

## Phase 6 — AI segmentation  *(2–3 days)*

- `core/backends/segment.py` behind a lazy import + capability check:
  **SAM 2** (click/box → precise mask) and **rembg/U²-Net** (one-click subject or
  background cutout). Output is a plain `Mask` → flows into the existing engine.
- Run via **ONNX Runtime** (CPU default; GPU if available). Missing model/dep →
  feature hidden, manual brush still works.
- UX: **tap the person → mask appears**; adjust with brush.
- **Milestone:** one tap selects a person accurately.

## Phase 7 — LaMa erase  *(2–3 days)* — the headline feature

- `core/backends/inpaint_lama.py` (`iopaint`/`simple-lama-inpainting`, ONNX/PyTorch).
- Wire "Erase" to auto-pick engine: tiny mask → `cv2.inpaint`; person/object mask →
  **LaMa**; then auto colour-match + feather (Phase 5).
- Graceful fallback to PatchMatch when LaMa unavailable.
- **Milestone:** tap a person → Erase → they're gone, background plausibly filled,
  saved at full resolution.

## Phase 8 — Optional extras  *(as desired)*

- Stable-Diffusion inpaint/outpaint ("erase and replace with…", extend canvas) —
  GPU-gated.
- Port `ai_edit.py` Claude/Ollama bridge for text-prompt global looks.
- RAW (`rawpy`) / HEIC (`pillow-heif`) input; batch apply a recipe.

---

## Phase 9 — Pro-grade capabilities  *(the "professional look")*

From the professional-editing research in [analysis.md §11](analysis.md). Ordered by
**leverage on a professional result ÷ effort**. Items 9.1–9.6 are pure OpenCV/NumPy
(no new deps) and slot into the existing layer/mask/curve engine — do these first.
9.7–9.10 follow the optional-backend pattern proven with LaMa/SAM.

### No new dependencies (highest leverage first)

- **9.1 — Colour grading (HSL + colour balance)** — per-hue **saturation/luminance**
  targeting, and **shadow/midtone/highlight colour wheels** (split-tone). The biggest
  "pro colour" lever we lack (Capture One's headline). New `adjust` ops; maskable like
  the rest. *(2–3 days)*
- **9.2 — White-balance eyedropper + Kelvin temp** — click a neutral pixel to set WB;
  temperature in approximate Kelvin. *(1 day)*
- **9.3 — Clarity / Texture / Dehaze** — midtone local-contrast (unsharp on a large
  radius), fine-detail texture, and dark-channel-prior haze removal. Maskable. *(2 days)*
- **9.4 — Sharpening (capture + output)** — unsharp / high-pass sharpen, plus an
  **output-sharpening** step at export sized for screen vs print. *(1–2 days)*
- **9.5 — Dodge & burn tool** — a dedicated brush that paints local exposure up/down;
  mostly reuses the masked-exposure layer path. *(1 day)*
- **9.6 — Frequency separation (skin)** — split low (tone) / high (texture) frequency so
  skin can be smoothed while keeping pores; a portrait staple. Maskable. *(1–2 days)*
- **9.7 — Finishing: vignette + film grain** — creative edge darkening and grain to
  finish a graded look. *(1 day)*
- **9.8 — Presets + basic batch** — save an adjustment recipe (an `.iedit` **without**
  the pixel layers) and apply it to any image or a folder. Consistency = professionalism.
  Reuses `core/project.py`. *(1–2 days)*

### Optional backends (bigger, higher image-quality tier)

- **9.9 — RAW input** (`rawpy` / libraw) — the biggest *image-quality* gap: true highlight
  recovery and white balance come from RAW, not JPEG. Also HEIC (`pillow-heif`). *(2–3 days)*
- **9.10 — Denoise** — classical `cv2.fastNlMeansDenoisingColored` now; an **AI denoise**
  model later (the DxO DeepPRIME niche) for high-ISO. *(classical 1 day; ML more)*
- **9.11 — Lens & perspective correction** — distortion / vignetting / chromatic-aberration
  and keystone / horizon straighten via OpenCV `undistort` + perspective transform;
  manual sliders first, lens profiles later. *(2–3 days)*
- **9.12 — AI super-resolution / upscale** — **Real-ESRGAN** via ONNX Runtime (reuses the
  lazy `core/backends/` pattern) to enlarge for print without softening; optional face
  recovery. ⚠️ check model licence. *(2–3 days)*

**Suggested order:** 9.2 → 9.4 → 9.3 → 9.1 → 9.5 → 9.8 → 9.6 → 9.7, then the backend tier
9.9 → 9.10 → 9.12 → 9.11. Until RAW/denoise/upscale land, pair image-editor with a free RAW
processor (Darktable / RawTherapee) for those steps.

---

## Cross-cutting concerns

- **Performance:** proxy preview at longest-side ≤ ~2000 px; full-res only on
  export. Cache each layer's rendered output; invalidate on param/mask change.
  Heavy ops (heal/ML) run in a `QThread` (port `_AiWorker`) so the UI never blocks.
- **Non-destructive project files:** optional `.iedit` sidecar (JSON of the layer
  stack) so an edit can be reopened and revised; the pixel export stays separate.
- **Licensing:** pin exact model versions; record each weight's licence before
  shipping (some are non-commercial) — see analysis §8.
- **Testing:** pytest over `core/` (pure arrays, no Qt) — golden-image tests for
  ops/curves/blend; mask math unit tests; a tiny fixture image set.
- **Docs & versioning:** mirror `image_selector` — `docs/versioning/vX.Y.Z/`
  with `plan.md` / `changelog.md`, and keep `docs/analysis.md` current.

## Rough sequencing

| Milestone | Phases | Outcome |
|-----------|--------|---------|
| **M1 — "better than the phone"** | 0–3 | full-res open/edit/save, masks, local adjust, curves — no ML |
| **M2 — classical retouch** | 4–5 | heal small stuff, seamless paste, colour match |
| **M3 — "erase anyone"** | 6–7 | SAM tap-select + LaMa erase, the headline feature |
| **M4 — creative/optional** | 8 | SD replace/outpaint, AI looks, RAW/HEIC, batch |
| **M5 — pro-grade look** | 9 | colour grading/HSL, WB picker, clarity/dehaze, sharpening, dodge & burn, frequency separation, presets/batch, then RAW · denoise · upscale · lens correction |
</content>
