# image-editor — Feature Research & Analysis

> Research analysis for a new **standalone photo-editing** desktop app. Not an
> image selector — a plain editor with **Photoshop-grade capabilities but
> phone-app-level ease of use**: erase people, apply an effect to only part of a
> picture, blend the result so the edit is invisible, colour/tone curves — and
> save at **full original resolution**.
>
> Date: 2026-09-11 · Status: research / pre-implementation

---

## 0. Product context & design principles

**The problem that started this.** Editing is currently done in **phone apps**,
which *destroy resolution*: they downscale the working image and re-compress on
export, so a 24 MP original comes back as a soft, recompressed few-megapixel JPEG.
There is no way to do a capable edit *and* keep the original pixels.

**So the two non-negotiables are:**

1. **Full-resolution, non-destructive.** The original is never downscaled. The
   preview may work on a scaled proxy for speed, but the **final render always runs
   the edit pipeline at native resolution** and saves with quality/format control
   (real JPEG quality, or PNG/TIFF). This is already how `image_selector` saves
   (full-res render only at save, atomic + timestamp-preserving) — we keep that and
   make it the headline feature. It is the single biggest advantage over any phone app.
2. **Phone-app-simple, Photoshop-capable.** The power (masks, layers, inpainting,
   curves) lives *underneath* a UI that stays as approachable as Snapseed/Instagram:
   - one big image, direct-on-image gestures (pinch-zoom, brush, drag-to-adjust),
   - **tap the person → Erase**, **drag on the sky → darker**, not "create an
     adjustment layer, add a luminosity mask, set blend mode",
   - sensible auto-defaults (auto-feather, auto-pick inpaint engine, auto colour-match)
     so the *simple* path needs no jargon, and the depth is opt-in.
   - Snapseed is the model to study: pro results, thumb-friendly, no layer panel in
     the user's face — the layer/mask machinery is an *implementation detail*, not
     the interface.

Every feature section below should be read through this lens: **the algorithm is
the Photoshop half; the interaction design is the phone-app half, and both must
ship together.**

---

## 1. Why this is a new project (and not "just more OpenCV")

The features requested — *erasing people, applying contrast/effects to a selected
region only, blending an edit to match its surroundings, colour and tone curves* —
split into two very different tiers of difficulty:

| Tier | Technique | Tooling | Quality |
|------|-----------|---------|---------|
| **Classical (OpenCV/NumPy)** | `cv2.inpaint` (Telea / Navier–Stokes), grey-world WB, LUT curves, `cv2.seamlessClone` | Already in `image_selector`'s `edit_ops.py` | Fine for scratches, dust, tiny blemishes and simple gradients — **falls apart on anything textured or larger than a few dozen pixels** |
| **Content-aware / ML** | LaMa / diffusion inpainting, SAM2 segmentation, U²-Net matting, PatchMatch, gradient-domain blending | New dependencies (PyTorch/ONNX + models) | This is what "erase a person and you can't tell" actually requires |

This is the earlier point about "OpenCV is too simple": `cv2.inpaint` diffuses
neighbouring colour into the hole. It cannot **hallucinate plausible texture**
(grass, brick, a face behind the removed person), so removing a whole person
leaves a smear. The sophisticated behaviour you want is fundamentally a
**machine-learning problem sitting on top of an OpenCV/NumPy plumbing layer** —
not a pure-OpenCV one. So `image-editor` keeps OpenCV for the fast pixel math and
adds a model runtime (ONNX Runtime, optionally PyTorch) for the hard parts.

The good news: the whole editing *architecture* from `image_selector` transfers
directly — Qt-decoupled pure-array ops, an `EditState`, a fixed pipeline, atomic
Unicode-safe saves. We extend that model from *global* state to *masked, layered*
state.

---

## 2. The one foundation everything else needs: **selections & masks**

Every sophisticated feature below ("only on certain sections", "erase this
person", "blend to match") is really *"do operation X, but only where mask M says
so, and feather the boundary"*. So the mask engine is the core of the app, not an
afterthought. This is exactly how Darktable and Lightroom are built: a module does
one thing globally, and a **mask** restricts *where* it applies.

### How the reference tools do it

- **Drawn masks** (Darktable): primitive shapes the user draws — *brush, circle,
  ellipse, path, gradient*. Each shape stores geometry + a **feather/border**
  radius and an opacity, and multiple shapes combine (union / intersection /
  difference). ([darktable — drawn masks](https://docs.darktable.org/usermanual/development/en/darkroom/masking-and-blending/masks/drawn/))
- **Parametric / luminosity masks** (Darktable): the mask is generated *from pixel
  values* — e.g. "select pixels by how bright they are" via input sliders that can
  be feathered inward for a smooth falloff. This is how you "apply contrast only to
  the shadows" without drawing anything. ([Luminosity masking in darktable](https://pixls.us/articles/luminosity-masking-in-darktable/))
- **Edge-aware feathering** (Darktable): instead of a plain Gaussian blur on the
  mask edge, the mask edge is snapped to *image* edges using a guided filter, so a
  sky mask stops at the horizon. ([mask refinement controls](https://docs.darktable.org/usermanual/development/en/darkroom/masking-and-blending/masks/refinement-controls/))
- **AI object masks** (modern Darktable / Photoshop "Select Subject"): a click or
  box is handed to a segmentation model that returns a pixel-perfect mask (see §3).

### Implementation for image-editor

- Represent a mask as a single-channel `float32` array in `[0,1]` (0 = unaffected,
  1 = full effect) at image resolution. This unifies *every* mask source — drawn,
  parametric, or ML-produced — into one type the pipeline consumes.
- Mask sources compose into a stack with blend modes (add / subtract / intersect).
- **Feathering** = `cv2.GaussianBlur` on the mask for the cheap version; a
  **guided filter** (`cv2.ximgproc.guidedFilter`, from `opencv-contrib-python`)
  for the edge-aware version, using the image as guide. This is the single most
  important quality lever in the whole app.
- Apply is a simple alpha composite: `out = base*(1-m) + effect*m` — see §6.

---

## 3. Erasing people & objects (inpainting)

Two sub-problems: **(a) get the mask of the thing to remove**, and
**(b) fill the hole convincingly**.

### (a) Getting the mask — segmentation

| Approach | What it is | Library / model | Notes |
|----------|-----------|-----------------|-------|
| **Manual brush** | user paints over the person | our own mask engine (§2) | always available, zero deps |
| **SAM 2** (Segment Anything Model 2, Meta) | click a point or drag a box → pixel-perfect mask; foundation model, prompt-based (points/boxes/masks) | `ultralytics` SAM-2 or `segment-anything-2`; ONNX export possible | ~44 fps inference, real-time feedback; the gold standard for "click the person, get the mask" ([SAM 2 · Ultralytics](https://docs.ultralytics.com/models/sam-2), [SAM2 overview (arXiv)](https://arxiv.org/pdf/2503.00042)) |
| **U²-Net / rembg** | whole-image foreground/background matting | `rembg` (bundles `u2net`, `u2net_human_seg`, BRIA RMBG) via ONNX Runtime | great for "remove the background", "cut out the subject"; `u2net_human_seg` is people-specific ([rembg](https://github.com/danielgatis/rembg), [U²-Net explained](https://learnopencv.com/u2-net-image-segmentation/)) |

**Recommendation:** ship SAM 2 (interactive, precise, this is what makes "erase
that person" feel magic) + `rembg` for one-click subject/background cutouts, and
always keep the manual brush as the dependency-free fallback.

### (b) Filling the hole — inpainting

| Method | Engine | When it wins | Cost |
|--------|--------|-------------|------|
| **Telea / Navier–Stokes** | `cv2.inpaint` | 1–20 px defects: dust, scratches, sensor spots, tiny blemishes | instant, CPU, already have it |
| **PatchMatch** ("content-aware fill" / GIMP Resynthesizer) | classical, copies best-matching patches from elsewhere in the image | textured but *self-similar* backgrounds (grass, gravel, water, sky) | fast-ish, CPU, no model |
| **LaMa** (resolution-robust large-mask inpainting) | `iopaint` / `simple-lama-inpainting`, ONNX or PyTorch | **the default for object/person removal** — hallucinates plausible structure over large holes, matches surroundings | ~100–500 ms GPU, seconds CPU; ~200 MB model |
| **Stable-Diffusion inpaint** | `iopaint` with an SD model | *replace* with new content ("erase and put grass"), outpainting/extending canvas | heavy (GB-scale model, GPU strongly preferred) |

How the reference tool (**IOPaint**, formerly Lama-Cleaner) works end-to-end:
*load image → paint a mask over the unwanted object → an erase model (LaMa) fills
the region to match surrounding pixels; a diffusion model can instead replace or
outpaint.* This is exactly the mask→fill pipeline we build. ([IOPaint on GitHub](https://github.com/Sanster/IOPaint))

**Recommendation:** a single "Erase" action that picks the engine by mask size —
`cv2.inpaint` for tiny masks, **LaMa** for anything person/object-sized — with SD
inpaint as an optional "replace with…" mode behind a flag. IOPaint can even be
vendored as a library rather than reimplemented.

---

## 4. Local adjustments — "contrast/effects on certain sections only"

This is §2 (masks) applied to the *existing* `edit_ops.py` operations. Nothing new
in the math — the novelty is that each adjustment carries a mask and a blend mode.

- **Lightroom / Darktable model:** an adjustment "module" (exposure, contrast,
  colour, a film LUT…) runs, then its output is blended into the image *through a
  mask*. Stack several masked adjustments and you get dodge-and-burn, selective
  saturation, darkened-sky, brightened-subject, etc.
- **Parametric masks** let "contrast in the shadows only" work with zero drawing —
  the mask is derived from luminance. ([darktable — luminosity masks](https://www.darktable.org/2015/01/luminosity-masks-in-darktable/))
- **Feathering radius is the make-or-break control** for avoiding hard,
  obviously-edited transitions. ([mask refinement](https://docs.darktable.org/usermanual/development/en/darkroom/masking-and-blending/masks/refinement-controls/))

### Implementation for image-editor

- Reuse `apply_contrast`, `apply_exposure`, `apply_saturation`, `apply_shadows`,
  `apply_highlights`, the film LUTs, curves (§5), etc. **unchanged**.
- Wrap each in an **adjustment layer**: `{op, params, mask, blend_mode, opacity}`.
- Compose the layer stack top-to-bottom (see §6). A global adjustment is just a
  layer whose mask is all-ones — so global and local share one code path.

---

## 5. Colour & tone curves

The classic diagonal-line control: input on X, output on Y; identity is the
straight line; a curve above brightens, below darkens, and an **S-curve adds
contrast**. Points are joined by a **monotonic spline** (not plain cubic, which
overshoots and causes tonal reversals). ([darktable — tone curve](https://docs.darktable.org/usermanual/development/en/module-reference/processing-modules/tone-curve/))

Key design decisions the reference tools make:

- **Which channel(s):**
  - *RGB master* curve → affects luminance-ish, simple.
  - *Per-channel R / G / B* curves → colour grading, but applying a non-linear
    curve independently per channel **shifts hue** — a known artefact to warn about
    or mitigate. ([tone curve — colour preservation](https://docs.darktable.org/usermanual/development/en/module-reference/processing-modules/tone-curve/))
  - *Lab / "separated channels"* (Darktable tone curve) → independent control of
    **L** (luminance) vs **a/b** (chroma) so tonal contrast doesn't wreck colour.
- **Interpolation:** monotonic cubic spline (PCHIP-style) through user points.

### Implementation for image-editor

- A curve = a list of control points → build a **256-entry LUT** via monotonic
  spline interpolation (`scipy.interpolate.PchipInterpolator`, or a small
  hand-rolled monotone cubic to avoid the SciPy dep), then `cv2.LUT`. This slots
  straight into the existing `_make_lut` / `apply_lut` helpers in `edit_ops.py`.
- Offer **Master RGB + per-channel R/G/B** first (a `(256,1,3)` LUT does all four
  in one `cv2.LUT` call), and a **Lab L/a/b** mode later for hue-safe contrast.
- Curves become just another op → automatically maskable (§4) and layerable.

---

## 6. Blending the final picture to match (the "invisible edit")

Two distinct blending problems, often confused:

### (a) Boundary blending — hide the seam of a paste/composite

**Poisson image editing / gradient-domain blending** (Pérez, Gangnet & Blake,
SIGGRAPH 2003): instead of copying pixel *values* across a boundary, it copies the
source region's **gradients** and solves a Poisson equation so the pasted region's
*colours/brightness bend to meet* the destination at the seam — the transition
becomes invisible. This is precisely how you "blend the final picture to match".
Directly available as **`cv2.seamlessClone(src, dst, mask, center, flags)`** with
`NORMAL_CLONE` / `MIXED_CLONE` / `MONOCHROME_TRANSFER` modes.
([OpenCV seamless cloning](https://docs.opencv.org/4.x/df/da0/group__photo__clone.html),
[Poisson image editing (Pérez et al.)](https://www.cs.jhu.edu/~misha/Fall07/Papers/Perez03.pdf),
[learnopencv walkthrough](https://learnopencv.com/seamless-cloning-using-opencv-python-cpp/))

- Good for: pasting an object from another photo, patching a region with borrowed
  content, face/sky swaps.
- `MIXED_CLONE` preserves destination texture through the seam (better over busy
  backgrounds); `NORMAL_CLONE` fully replaces.

### (b) Colour/tone matching — make the edited region *belong*

Even with a perfect seam, a pasted or inpainted region can be the wrong colour
temperature or exposure. **Colour transfer** matches the statistics
(mean + standard deviation per channel, classically in Lab space — Reinhard et al.)
of the edit region to a reference region so its palette matches. Histogram matching
(`skimage.exposure.match_histograms`) is the stronger variant.

### Implementation for image-editor

- **Seamless paste tool:** user places/masks a source region → `cv2.seamlessClone`.
- **"Match colour to surroundings"** step for any inpaint/paste: sample the ring of
  pixels *around* the mask, transfer Lab mean/std (or histogram-match) onto the
  filled region, then feather. Run it *after* LaMa fill for a near-invisible erase.
- The universal compositor for §2–§6:
  ```
  out = base * (1 - mask) + effect * mask          # feathered mask in [0,1]
  # for paste/heal where geometry moves, use cv2.seamlessClone instead
  ```

---

## 7. Layers & non-destructive document model

To hold all of the above, the `EditState` from `image_selector` grows into a small
**document model** (like a lightweight PSD / Darktable history stack):

```
Document
├── base image (immutable original, BGR/float)
├── ordered layer stack (bottom → top)
│   ├── AdjustmentLayer { op, params, mask, blend_mode, opacity, visible }
│   ├── HealLayer       { mask, engine: telea|patchmatch|lama, params }
│   ├── PixelLayer      { rgba, transform }          # pasted / composited content
│   └── ...
├── crop_rect, rotation                              # from existing pipeline
└── history (undo/redo of layer ops)
```

Rendering = start from base, apply each visible layer top-to-bottom via its
mask + blend mode. Everything stays **non-destructive** and reproducible, matching
the design goal `image_selector` already committed to (pure-array ops, full-res
render only at save). Save-as remains atomic + Unicode-safe + timestamp-preserving,
reusing `img_io.py` and the tempfile-then-`shutil.move` pattern.

---

## 8. Recommended tech stack

Reuse everything proven in `image_selector`; add a model runtime.

| Layer | Choice | Rationale |
|-------|--------|-----------|
| UI | **PySide6 / Qt** (QPainter preview, zoom/pan) | direct reuse of `preview_widget.py`, `edit_panel.py`, crop overlay |
| Pixel math | **OpenCV (+ `opencv-contrib-python` for `ximgproc` guided filter) + NumPy** | reuse `edit_ops.py`, `film_luts.py`, LUT/curve helpers |
| Curves | monotone cubic spline → LUT (`scipy` PchipInterpolator *or* hand-rolled) | keep deps light |
| Segmentation | **SAM 2** (interactive) + **rembg / U²-Net** (one-click cutout) | precise masks; the "click the person" magic |
| Inpainting | **`cv2.inpaint`** (tiny) → **LaMa** (`iopaint`/`simple-lama-inpainting`, default) → optional **SD inpaint** (replace/outpaint) | right engine per mask size |
| Blending | **`cv2.seamlessClone`** (Poisson) + Lab colour transfer / histogram match (`scikit-image`) | invisible seams + colour match |
| Model runtime | **ONNX Runtime** first (CPU-friendly, easy install); **PyTorch** only where a model needs it | Mario's box may be CPU-only; ONNX keeps it usable |
| AI-assist (optional) | keep the `ai_edit.py` Claude/Ollama bridge for text-driven global looks | already built, complements manual local tools |

**GPU note:** LaMa and SAM run on CPU (seconds) or GPU (sub-second). SD inpaint
really wants a GPU. Structure model calls behind a `backends/` interface so a
missing/absent GPU degrades gracefully (LaMa-CPU, or fall back to PatchMatch).

### Dependency & licence snapshot

| Package | Purpose | Model size | Licence notes |
|---------|---------|-----------|---------------|
| `opencv-contrib-python` | pixel ops + guided filter + seamlessClone | — | Apache-2.0 |
| `onnxruntime` | run ONNX models on CPU/GPU | — | MIT |
| `rembg` | background/subject cutout | ~5–180 MB | MIT (models vary — check BRIA RMBG terms) |
| SAM 2 (`ultralytics` or `segment-anything-2`) | interactive segmentation | ~40–350 MB | check per-model (Apache/BSD; some non-commercial) |
| `iopaint` / `simple-lama-inpainting` | LaMa erase (+ optional SD) | LaMa ~200 MB | LaMa weights: **verify licence before commercial use** |
| `scikit-image` | histogram matching / colour transfer | — | BSD |
| `scipy` (optional) | monotone spline for curves | — | BSD |

> ⚠️ **Licensing matters here** given Mario keeps a day job and ships side
> projects publicly: several segmentation/inpainting weights carry non-commercial
> or attribution terms distinct from their code. Pin exact model versions and
> record each licence before shipping.

---

## 9. Suggested build order

1. **Document + mask engine + layer compositor** (§2, §7) — the spine. Drawn masks
   (brush/gradient/shape) + feather + guided-filter edge-aware refinement.
2. **Local adjustments** (§4) — wrap existing `edit_ops` in masked layers. Immediate
   payoff, no new heavy deps.
3. **Curves** (§5) — master + per-channel, LUT-based.
4. **Classical heal/erase** (§3b) — `cv2.inpaint` + PatchMatch for small stuff.
5. **Seamless paste + colour match** (§6) — `seamlessClone` + Lab transfer.
6. **AI segmentation** (§3a) — SAM 2 click-to-mask + rembg cutout, wired into the
   mask engine.
7. **LaMa erase** (§3b) — the headline "remove a person" feature.
8. **(Optional) SD inpaint / outpaint**, and the `ai_edit` text-prompt bridge for
   global looks.

Phases 1–5 are pure OpenCV/NumPy/Qt (no models, works everywhere). Phases 6–8 add
the ML runtime — the part that makes edits genuinely *sophisticated* rather than
*simple*.

---

## 10. What transfers directly from `image_selector`

- `img_io.py` — Unicode-safe imread/imwrite (keep verbatim).
- `edit_ops.py` + `film_luts.py` — all become maskable layer ops unchanged.
- `preview_widget.py` — zoom/pan/QPainter preview.
- `edit_panel.py` crop overlay & debounced live-preview pattern.
- Atomic, timestamp-preserving Save-As (tempfile → `shutil.move` → `os.utime`).
- `ai_edit.py` Claude/Ollama bridge (optional global-look assist).
- The MVC discipline and "ops take a NumPy array, return a NumPy array, zero Qt
  imports" rule — which is what lets the same pipeline back an MCP server later.

---

## 11. Professional-grade capabilities — research (2026)

> Added after a research pass on *what actually makes photos look professional* and
> which tools deliver it, to steer image-editor toward pro-quality output. The goal:
> keep the phone-simple UX while adding the levers that separate an amateur edit from
> a professional one.

### What the pros actually do (the workflow)

The consistent professional pipeline, across guides, is an **ordered, non-destructive
workflow** — not random slider-pushing:

1. **Cull** ruthlessly (pick keepers; toss blurry/blinked).
2. **Base correction on the RAW** — white balance, exposure, highlight/shadow recovery.
3. **Tone & colour** — contrast/curves, then **colour grading** (HSL + split-tone).
4. **Local work** — masked adjustments, **dodge & burn** to shape light.
5. **Retouch** — heal/spot removal; **frequency separation** for skin.
6. **Denoise** (especially high-ISO) and **lens/perspective correction**.
7. **Output** — resize + **output sharpening** tuned for screen or print.
8. **Consistency** — a signature look applied as **presets** across a set; increasingly
   an **AI assistant** trained on the photographer's style handles the mechanical steps.
   ([Imagen — edit like a pro](https://imagen-ai.com/valuable-tips/how-to-edit-photos-like-a-professional-editor/),
   [Filterpixel — repeatable workflow](https://filterpixel.com/blog/how-to-professionally-edit-photos),
   [Fstoppers — freq. separation / dodge & burn / grading](https://fstoppers.com/education/complete-guide-frequency-separation-dodging-and-burning-and-color-grading-485517))

The "pro look" is mostly: **accurate colour + white balance, deliberate light
(dodge & burn), clean colour grading, natural skin, low noise, and correct
sharpening** — applied non-destructively and consistently.

### The reference tools (and what each is *for*)

| Tool | Licence | Known for | Relevance to us |
|------|---------|-----------|-----------------|
| **Adobe Lightroom Classic** | paid | the default RAW workflow; GPU RAW; AI masks | the workflow model to emulate |
| **Capture One** | paid | **best colour tools** & skin rendering, tethering | its colour-grading depth is the bar for our HSL/colour work |
| **DxO PhotoLab** | paid | **DeepPRIME denoise** + best lens corrections | denoise + lens-correction are its moat — both are gaps for us |
| **Darktable** | **FOSS** | scene-referred pipeline, 60+ modules, masks | our closest open reference; algorithms we can mirror |
| **RawTherapee** | **FOSS** | powerful RAW demosaic & detail | reference for RAW processing |
| **Photoshop** | paid | pixel retouching, frequency separation, dodge & burn | the retouching techniques to implement |
| **Topaz Photo AI** | paid | denoise / sharpen / **upscale** / face recovery | what "AI enhance" means to users |
| **Real-ESRGAN / Upscayl** | **FOSS** | AI **super-resolution**, rivals paid upscalers | our open path to upscaling |
([Best editing software 2026](https://www.findingtheuniverse.com/best-photo-editing-software/),
[Topaz upscalers](https://www.topazlabs.com/best-image-upscalers),
[Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN))

### image-editor today vs. the pro gap

**Already have (good foundation):** exposure/brightness/contrast/highlights/shadows,
saturation/vibrance, temperature/tint, curves (master + RGB), **local masked edits with
feather + edge-aware borders**, heal (classical + LaMa), remove-person (SAM),
reshape/liquify, seamless paste, crop/rotate, 30 looks, full-res non-destructive, layers,
`.iedit` projects. Dodge & burn is *nearly* free already (masked local exposure).

**The gaps that most affect a professional result**, high → lower leverage:

1. **HSL + colour grading** (per-hue sat/lum; shadow/mid/highlight colour balance / split-tone).
   Capture One's headline strength; the biggest "pro colour" lever we lack. *(OpenCV/NumPy — no model.)*
2. **White-balance eyedropper** + Kelvin temp; **auto-WB we have, but not click-neutral.** *(easy)*
3. **Clarity / Texture / Dehaze** (local-contrast midtone punch; dark-channel-prior haze removal). *(OpenCV — no model.)*
4. **Sharpening** — capture sharpening (unsharp/high-pass) **and output sharpening** sized for
   screen/print. A pro final step we don't have. *(OpenCV — no model.)*
5. **Dodge & burn tool** — a dedicated brush (leverages our masked-exposure layers). *(reuse.)*
6. **Denoise** — classical (`cv2.fastNlMeansDenoisingColored`) now; **AI denoise** later.
   High-ISO cleanup is a top pro differentiator (DxO DeepPRIME). *(classical easy; ML bigger.)*
7. **Frequency separation** — smooth skin tone while keeping texture, for portraits.
   *(low/high-pass split — OpenCV.)*
8. **Vignette + film grain** — finishing touches for a graded look. *(easy.)*
9. **Presets** — save an adjustment recipe (an `.iedit` minus the pixels) and apply it to any
   image / a batch. **Consistency is itself professionalism.** *(reuses our serializer.)*
10. **RAW input** (`rawpy`/libraw) — the single biggest *image-quality* gap: real highlight
    recovery and WB come from RAW, not JPEG. *(dependency, no model.)*
11. **Lens & perspective correction** — distortion/vignetting/chromatic-aberration and
    keystone/horizon straighten. *(OpenCV `undistort` / perspective; manual sliders feasible.)*
12. **AI super-resolution / upscale** — enlarge for print without going soft; **Real-ESRGAN**
    via ONNX Runtime is the open path (reuses our lazy-backend pattern from LaMa/SAM). *(model.)*

### Recommendation

Most of the "professional look" is reachable **with no new dependencies** — items 1–5, 7–9 are
pure OpenCV/NumPy and slot into the existing layer/mask/curve engine. Items 6, 10–12 (AI denoise,
RAW, lens profiles, super-resolution) are the heavier, higher-quality tier that follows the same
optional-backend pattern already proven with LaMa and SAM. Until RAW/denoise/upscale land,
pairing image-editor with a free RAW processor (**Darktable / RawTherapee**) covers the gap.

See `plan.md` **Phase 9** for the prioritized build.

---

## Sources

- IOPaint (LaMa / SD inpainting, mask→fill workflow) — https://github.com/Sanster/IOPaint
- Poisson Image Editing, Pérez, Gangnet & Blake, SIGGRAPH 2003 — https://www.cs.jhu.edu/~misha/Fall07/Papers/Perez03.pdf
- OpenCV Seamless Cloning API — https://docs.opencv.org/4.x/df/da0/group__photo__clone.html
- Seamless Cloning walkthrough (LearnOpenCV) — https://learnopencv.com/seamless-cloning-using-opencv-python-cpp/
- SAM 2 (Ultralytics docs) — https://docs.ultralytics.com/models/sam-2
- Segment Anything 2 analysis (arXiv) — https://arxiv.org/pdf/2503.00042
- rembg (U²-Net background removal) — https://github.com/danielgatis/rembg
- U²-Net image segmentation (LearnOpenCV) — https://learnopencv.com/u2-net-image-segmentation/
- darktable — tone curve — https://docs.darktable.org/usermanual/development/en/module-reference/processing-modules/tone-curve/
- darktable — drawn masks — https://docs.darktable.org/usermanual/development/en/darkroom/masking-and-blending/masks/drawn/
- darktable — mask refinement (edge-aware feathering) — https://docs.darktable.org/usermanual/development/en/darkroom/masking-and-blending/masks/refinement-controls/
- Luminosity masking in darktable (PIXLS.US) — https://pixls.us/articles/luminosity-masking-in-darktable/
- Imagen — how to edit like a professional (2026 workflow) — https://imagen-ai.com/valuable-tips/how-to-edit-photos-like-a-professional-editor/
- Filterpixel — a precise, repeatable pro workflow — https://filterpixel.com/blog/how-to-professionally-edit-photos
- Fstoppers — frequency separation, dodge & burn, colour grading — https://fstoppers.com/education/complete-guide-frequency-separation-dodging-and-burning-and-color-grading-485517
- Best photo editing software 2026 (Lightroom/Capture One/DxO/Darktable) — https://www.findingtheuniverse.com/best-photo-editing-software/
- Topaz Labs — best image upscalers 2026 — https://www.topazlabs.com/best-image-upscalers
- Real-ESRGAN (open-source super-resolution) — https://github.com/xinntao/Real-ESRGAN
</content>
</invoke>
