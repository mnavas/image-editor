# image-editor — Changelog

Running record of what has actually been built. Newest first.
See [plan.md](plan.md) for the phase roadmap and [analysis.md](analysis.md) for the research.

---

## 2026-09-17 (later) — Styled HTML docs for the site ✅

GitHub Pages served the raw `.md` files unformatted. Added `docs/build_docs.py`
(uses the `markdown` package) which renders every `docs/*.md` into a standalone,
themed `*.html` (violet site theme, styled tables/code, a top doc-nav) and rewrites
intra-doc `.md` links to `.html`. The landing page now links to the `.html` docs;
the `.md` files stay the source (GitHub renders them natively). Regenerate with
`.venv/bin/python docs/build_docs.py` after editing any `.md`.

---

## 2026-09-17 (later) — Docs: pro guide + user guide refresh ✅

- New **`docs/pro-guide.md`** — a step-by-step "professional look" recipe (7 steps),
  quick preset table (clean/warm portrait/cinematic/landscape/B&W), and common
  mistakes, all mapped to image-editor's tools.
- **`docs/user-guide.md`** updated for the new adjustments (clarity/texture/dehaze/
  sharpen) and the **Color tab** (split-tone, HSL, vignette, grain).
- Linked the pro guide from the README and the landing page footer.

---

## 2026-09-17 (later) — Phase 9 (no-dep pro tools) ✅

The no-dependency slice of Phase 9 — the levers that give a professional look.

- **New maskable adjustments** (work whole-image AND on a selection): **Clarity**
  (midtone local contrast), **Texture** (fine detail), **Sharpen** (unsharp), **Dehaze**
  (simplified dark-channel prior). Added to the Adjust sliders.
- **New Color tab (whole-image grade):**
  - **Split-tone** colour grading — tint shadows and highlights toward chosen hues.
  - **HSL** — saturation by colour band (red/yellow/green/cyan/blue/magenta).
  - **Finishing** — Vignette and Film grain.
- All are ordinary `core/ops.py` ops, so they compose in the render pipeline and
  serialize into `.iedit` (grade saved/restored).
- Tests: pro ops run + behave (vignette darkens corners, sharpen raises edge
  variance, HSL targets one hue), and a grade `.iedit` round-trip. 32/32 pass.

Still to do in Phase 9: dodge & burn tool, frequency separation, presets/batch, and
the backend tier (RAW, AI denoise, super-resolution, lens correction).

---

## 2026-09-17 — Pro-editing research → analysis §11 + plan Phase 9 ✅

Researched what makes photos look professional and which tools deliver it; folded
the findings into the docs (not yet built — planning only).

- `analysis.md` **§11**: the pro workflow, the reference tools (Lightroom, Capture
  One, DxO, Darktable, RawTherapee, Photoshop, Topaz, Real-ESRGAN) and what each is
  for, image-editor's current strengths vs. the pro gaps, with sources.
- `plan.md` **Phase 9** (+ milestone **M5**): prioritized pro features — colour
  grading/HSL, WB eyedropper, clarity/texture/dehaze, sharpening (capture + output),
  dodge & burn, frequency separation, vignette/grain, presets/batch (all no-dep),
  then RAW, denoise, super-resolution (Real-ESRGAN), and lens/perspective correction
  as optional backends.

---

## 2026-09-14 (later) — Docs + landing page ✅

Documentation and a landing page, modelled on image_selector / instax-printing.

- `docs/installation.md` (core + optional CPU-only AI install recipes + licence note),
  `docs/user-guide.md` (full workflow), `docs/architecture.md` (module map, document
  model, render pipeline).
- `index.html` — a responsive landing page (violet theme): hero with an editor
  mockup, features, how-it-works, an "engine" table, install, contribute, and a
  Support section with GitHub Sponsors / PayPal / **De Una QR** (modal).
- Copied `assets/deuna-qr.png` for supporter donations. README gained a
  Documentation section.

---

## 2026-09-14 — Reshape / liquify (body slimming) ✅

A push-brush warp like phone "Reshape/Slim" tools — drag a body edge inward to slim.

- **Core** `core/warp.py`: a `WarpField` holds a smooth normalised displacement map
  on a grid sized to the image aspect; a drag accumulates Gaussian-falloff pushes;
  `apply` resizes the field to the target and warps via `cv2.remap` — so the same
  field drives proxy preview and full-res export. Non-destructive (stores the field,
  not warped pixels).
- **New `warp` layer kind** (cached), with `.iedit` serialisation (fields embedded
  as base64 .npy).
- **Controller:** `warp_stroke`, `set_warp_radius/strength`, `commit_warp`,
  `cancel_warp`; pending warp previews live in the render pipeline (before the
  global grade, like the other pending previews).
- **UI:** new **Reshape** tab — 🫳 Reshape brush (a canvas warp tool), Brush size,
  Strength, Apply/Reset. Drag on the image to push pixels.
- Tests: warp push moves pixels; controller commit + `.iedit` round-trip preserves
  the field. 29/29 pass.

Note: this is a manual reshape brush (what the phone apps use). It edits the user's
own photos; there's no automatic body detection — you drag to shape.

---

## 2026-09-13 (later) — Camera picture profiles in the filter list ✅

Added camera-style looks alongside the film sims (same LUT/saturation mechanism),
listed first in the Film-look dropdown: **standard, vivid, neutral, faithful, flat,
landscape, portrait, monochrome**, plus **high_contrast / low_contrast** tone
presets. 30 filters total; monochrome is a luminosity-weighted B&W.

---

## 2026-09-13 (later) — Show/hide selection toggle ✅

New "Show selection outline" checkbox in the Adjust tab. Turning it off hides the
outline so you see the clean result, while **keeping the selection** — no more
clearing (which lost it) and re-brushing just to preview. Toggle it back on to keep
refining the same selection.

---

## 2026-09-13 — Full adjustment set + everything works on a selection ✅

Every adjustment (including curves) now works both whole-image and on a brushed
selection — the local editor was missing brightness and curves entirely.

- **Added ops:** `brightness` (was never exposed), `vibrance` (smart saturation
  that protects already-vivid colours), `temperature` (warm/cool), `tint`
  (magenta/green). Adjustment set is now: exposure, brightness, contrast,
  highlights, shadows, saturation, vibrance, temperature, tint.
- **Curves on a selection:** curves now have a local variant. The Whole image /
  Selection toggle governs both the sliders AND the curve editor; the Curves tab
  shows the current target and gained a **✓ Apply to selection** button (the
  earlier missing Apply). A local commit bundles the sliders *and* curves into one
  masked `adjust_set` layer.
- Sliders are generated from the adjustment list, so all nine appear in both modes;
  local edits keep the luminance-only contrast and the feather/edge-aware border.
- Tests: all ops present + run, temperature warms, local brightness+curves commit
  together into one masked layer. 27/27 pass.

---

## 2026-09-12 (later) — Phase 5: seamless paste (insert an image) ✅

Composite an object from another photo so it belongs in the scene.

- **Core** `blend.place_and_blend`: resize + position an object, colour-match it to
  the destination patch (Reinhard), then Poisson-blend (`cv2.seamlessClone`,
  NORMAL/MIXED) so the seam disappears; feathered-alpha fallback if clone can't run.
- **New `paste` layer kind** (cached like heal): holds the object image + alpha +
  position/scale/flags; renders through the compositor. A cutout **PNG's alpha** is
  used as the shape; otherwise the whole rectangle is blended.
- **Controller:** `insert_image` (alpha-aware load via `img_io.imread_unchanged`),
  `set_paste_param`, `commit_paste`, `cancel_paste`. Pending paste previews live.
- **Pipeline fix:** pending local-adjust and paste previews now render in the SAME
  position they'll occupy once committed (before the global grade), so preview ==
  final result — also tightens the earlier local-adjust ordering.
- **`.iedit`** now serialises paste layers (object + alpha embedded as base64 PNG).
- **UI:** new **Paste** tab — 📎 Insert image, Position X/Y, Size, Mixed-clone and
  Match-colour toggles, Apply/Cancel, with live preview.
- Tests: place-and-blend changes the image; paste commit + `.iedit` round-trip with
  the embedded object. 24/24 pass.

### Status vs. plan
Done: Phases 0–7 + geometry + layers + `.iedit` + luminance contrast. Remaining
(optional): **Phase 8** only — SD replace/outpaint, `ai_edit` text-look bridge,
RAW/HEIC input, batch. The editor is otherwise feature-complete.

---

## 2026-09-12 (later) — Luminance-only local contrast + `.iedit` project files ✅

- **Luminance-only contrast** (`ops.contrast_lum`): applies contrast to the LAB L
  channel only, so colour/saturation are preserved. Local (selection) edits now
  route contrast through it automatically, so a boosted region no longer looks
  "processed" (RGB contrast pushed a midtone's saturation 113→149; luminance-only
  keeps it ~109). Whole-image contrast stays per-channel RGB (punchy look intact).
- **`.iedit` project files** (`core/project.py`): Save Project / Open Project in the
  toolbar. Serialises the full non-destructive state to JSON — source path,
  rotation/crop, the layer stack (with masks; SAM raster masks embedded as base64
  PNG), and the global adjust / curves / film recipe. Reopen later and keep
  editing. The exported picture stays a separate flat file.
- Tests: luminance-contrast saturation behaviour; a full project round-trip
  (geometry + masked adjust layer + raster-mask heal layer + adjust/film/curves).
  22/22 pass.

### Status vs. plan
Done: Phases 0–4, 6, 7 + geometry + layers + `.iedit` projects + luminance contrast.
Remaining (optional): **Phase 5 seamless-paste UI** (engine exists), **Phase 8**
(SD replace/outpaint, `ai_edit` text-look bridge, RAW/HEIC, batch).

---

## 2026-09-12 (later) — Phase 6: SAM select → remove the person ✅

Brush roughly over a person and the app cuts them out precisely, then erases them.

- **Segmentation backend** `core/backends/segment.py`: SAM (Segment Anything, ViT-B,
  CPU) with a **box + positive-point prompt** built from the brush selection. The
  brush points are the key — a box alone grabbed only part of the figure; feeding
  the stroke points as "the object is here" selects the whole person. Image
  embedding is cached per image (slow encode once, then instant).
- **New mask source** `RasterSource` (core/mask.py): lets SAM's pixel mask live in
  the same resolution-independent mask system (resizes to the render target), so a
  segmented mask flows through proxy preview → full-res export like any other.
- **Controller:** `refine_to_subject()` (rough brush → precise SAM mask),
  `remove_person_in_selection()` (refine + LaMa erase in one), `segmentation_available()`.
- **UI:** 🧍 **Remove person** (SAM + LaMa, one click) and 🎯 **Select subject**
  (refine only, then erase or adjust). Both run on the background thread; graceful
  fallback to plain Erase if SAM isn't installed.
- **Install:** `pip install --no-deps segment-anything`; ViT-B checkpoint (~358 MB)
  auto-downloads to `~/.cache/image-editor/`. Reuses the CPU torch from Phase 7.
  CPU timing: first select ~8 s (load+encode), ~0.1 s after; full remove-person
  ~11 s incl. LaMa. All off the UI thread.
- Tests: SAM box segmentation, RasterSource resize, and a full brush→SAM→LaMa
  end-to-end (skips if backends absent). 20/20 pass.

### Status vs. plan
Done: Phases 0–4, 6, 7 + geometry + layers. Remaining (optional): Phase 5
seamless-paste UI (engine exists), Phase 8 (SD replace/outpaint, ai_edit text-look
bridge, RAW/HEIC, batch), and the luminance-only (LAB-L) contrast polish.

---

## 2026-09-12 — Completing the editor: curves UI, crop, rotate, layers, threaded erase ✅

Closed the main gaps between the engine and a usable editor. No new dependencies.

- **Phase 3 — Curves UI ✅.** New `widgets/curve_editor.py`: draggable tone curve
  with master + per-channel R/G/B, click-to-add / right-click-remove points, live
  monotone-spline preview line. Applied globally in the render (before film look).
- **Crop ✅.** Crop tool on the canvas (drag a rectangle, dim outside, Apply/Reset).
  Crops **compose** (crop of a crop) and **follow rotation** so the rect stays valid.
- **Rotate ✅.** ⟲ / ⟳ toolbar buttons; an active crop is rotated with the image.
- **Layers panel ✅.** New "Layers" tab lists committed local/heal edits with a
  visibility checkbox, an opacity slider, and delete — the non-destructive stack is
  now visible and manageable. (Global sliders/curves/film apply on top, not listed.)
- **Threaded erase ✅.** LaMa erase now runs on a `QThread` (`_RenderWorker`) so the
  UI no longer freezes; the canvas updates when the fill completes.
- **Tabbed rail** (Adjust / Curves / Layers) to hold the growing toolset while
  keeping the phone-simple feel.
- Tests: 18/18 pass — added rotate/dimension-swap, crop compose + clear, crop
  follows rotation, layer visibility/opacity/delete, global curves brighten.

### Status vs. plan
Done: Phases 0, 1, 2, 3, 4, 7 + geometry + layers. Remaining (optional):
- **Phase 5 UI** — seamless-paste tool (engine `seamless_paste`/`match_color` exists).
- **Phase 6 — SAM 2 tap-to-select / rembg cutout** (needs an ML install; deferred).
- **Phase 8** — Stable-Diffusion replace/outpaint, `ai_edit` text-look bridge,
  RAW/HEIC input, batch. Luminance-only (LAB-L) contrast still noted as a polish item.

---

## 2026-09-11 (later) — UX fix: see the edit while selecting ✅

The solid red mask overlay hid the image, so you couldn't see how a local edit
would look and had to commit blind (then undo + re-brush to retry).

- **Selection now shows as a dashed outline** (black+white marching-ants style) via
  mask contours in normalised coords — the edited result stays fully visible
  underneath while you tune sliders. A faint red tint (alpha 60) appears **only
  while you're actively brushing**, then drops to outline-only on release.
- **Live preview is now actually visible:** releasing the brush refreshes the
  composited preview, so moving any slider shows the final blended result in real
  time — no more committing blind.
- **Selection persists after Apply:** if the result is wrong, Undo and re-tune the
  *same* region — no re-brushing. "Clear" drops the selection explicitly.
- Also improves the Erase selection UX (outline instead of obscuring red fill).

---

## 2026-09-11 (later) — Fix: empty Open dialog on Linux ✅

The Open dialog showed no images. Root cause (same as instax-printing): the native
OS file dialog matches extension globs **case-sensitively**, so `*.jpg` hid `.JPG`
files and folders looked empty. Fix: build a case-inclusive filter listing both
cases of every extension (`*.jpg *.JPG …`) + "All files (*)", used for Open and Save.

---

## 2026-09-11 (later) — Phase 2: local-adjust panel + border smoothing ✅

Answers "when I adjust a region, does the border blend so it doesn't look edited?"

- **Whole image / Selection mode toggle.** In Selection mode the five adjustment
  sliders (exposure/contrast/saturation/shadows/highlights) apply live to the
  brushed region only, previewed in real time.
- **Border smoothing (Feather) slider** — controls the mask-edge blur (0–15% of the
  image diagonal); the effect fades in across that band instead of stopping at a
  hard line. This is the border-smoothing control the user asked for.
- **"Snap border to edges" (edge-aware) toggle** — runs `cv2.ximgproc.guidedFilter`
  so the mask boundary follows real image edges (e.g. stops at the horizon).
- The overlay shows the *feathered* mask live, so you see the softened border while
  tuning it. **✓ Apply to selection** bakes it into one undoable `adjust_set`
  layer (new layer kind: applies an ordered recipe of ops through a single mask).
- Tests added: feather visibly widens the blended transition band; controller
  commits a masked `adjust_set` layer carrying the chosen feather. 14/14 pass.
- Known follow-up: contrast is still per-channel RGB (can nudge saturation); a
  luminance-only (LAB-L) mode would look even more natural — noted, not yet done.

---

## 2026-09-11 (later) — Phase 7: LaMa "erase a person" ✅

Real AI object/person removal — the headline feature — now works, CPU-only.

- **Engine:** `simple-lama-inpainting` (Big-LaMa, ~200 MB model auto-downloaded to
  `~/.cache/torch/hub` on first erase). `core/backends/inpaint_lama.py` is fully
  implemented: BGR→PIL, run LaMa, back to BGR, then an automatic **Reinhard
  colour-match** of the filled region against the ring of pixels around the hole
  so the fill matches colour/exposure — not just texture.
- **Performance:** LaMa runs at a capped working resolution (`LAMA_MAX_SIDE=1280`)
  then the fill is pasted back into the full-res image (only masked pixels are used
  by the compositor, so full resolution is preserved everywhere else). Measured on
  this CPU: warm 400×600 ≈ 2.3 s; 6 MP ≈ 11.7 s. First-ever call ~40 s (one-time
  Torch JIT graph warmup).
- **Dispatch:** `core/heal.py` now auto-selects LaMa for person/object-sized masks
  (>1% of the image) and `cv2.inpaint` for tiny defects; falls back to classical if
  the backend is missing.
- **Caching:** heal results cached per resolution in the Layer, so LaMa runs once
  per erase, not on every preview frame; excluded from the undo deepcopy.
- **UI:** Erase shows "Filling background (LaMa AI)…" + wait cursor.
- **Install note (important):** `simple-lama-inpainting`'s own pins are hostile
  (Pillow<10 from source, numpy<2, full CUDA toolkit). Correct install is CPU-only
  in two steps — see `requirements.txt`. Verified numpy 2.5.3 / opencv-contrib /
  ximgproc all remain intact afterward.

### Answering "does erase fill the background like the phone apps?"
Yes — now it does, via LaMa, for people/objects (was classical-only before, which
only worked for small blemishes).

---

## 2026-09-11 — Phase 0 + Phase 1 + Phase 2 (partial) + Phase 4 (classical)

First working, end-to-end vertical slice: open → edit (global + local) → erase →
**full-resolution save**. All core logic is Qt-free and unit-tested.

### Phase 0 — Scaffold ✅
- Project skeleton, `.venv` (PyQt6 6.11, OpenCV 5.0 w/ ximgproc, numpy).
- `img_io.py` — ported Unicode-safe imread/imwrite; `imwrite` now takes cv2
  encode params so JPEG quality / PNG compression is controllable on export.
- `config.py` — JSON config at `~/.config/image-editor/` (last dir, JPEG quality,
  proxy max side).
- `widgets/canvas.py` — zoom/pan QPainter preview (ported from image_selector),
  extended with a brush overlay that reports points in **normalised** coords.
- `main.py`, `widgets/main_window.py` — window, toolbar (Open/Save/Undo/Redo),
  tool rail; **Save As renders at full native resolution**, atomic
  tempfile→move, original mtime preserved, quality-aware.

### Phase 1 — Document, layers, compositor, masks ✅ (spine)
- `core/document.py` — `Document` = base image + layer stack. **One `render(scale)`
  drives both the proxy preview and the full-res export** (WYSIWYG guarantee).
  Rotation + crop geometry, and an undo/redo history over the layer stack.
- `core/layers.py` — `Layer` (adjust / heal / pixel); produces an effect then the
  document composites it back through the layer's mask (global = no mask, same path).
- `core/mask.py` — masks stored as **resolution-independent recipes** rasterized on
  demand: `BrushStroke`, `EllipseShape`, `LinearGradient`, `RadialGradient`,
  `LuminanceRange` (parametric). Feather via Gaussian, optional **edge-aware**
  refine via `cv2.ximgproc.guidedFilter`. Add/subtract source composition + invert.
- `core/blend.py` — alpha `composite` with blend modes (normal/multiply/screen/
  overlay), plus `seamless_paste` (Poisson `cv2.seamlessClone`) and `match_color`
  (Reinhard Lab transfer) ready for Phase 5.

### Phase 2 — Local adjustments 🟡 (partial)
- `core/ops.py` — ported all image_selector adjustments (brightness, contrast,
  exposure, saturation, shadows, highlights, auto levels/tone/wb, normalize) +
  `film` op; name→function registry so layers reference ops by name.
- `core/film_luts.py` — copied verbatim (20 Fujifilm-inspired sims).
- UI: global sliders (exposure/contrast/saturation/shadows/highlights) + film-look
  picker, live proxy preview on a 60 ms debounce. "Apply Contrast to selection"
  bakes a **masked** adjustment layer (edge-aware feather) — proves local adjust.
- ⏳ Still to do: per-layer UI/management, more one-tap local adjustments, curves UI.

### Phase 3 — Curves ✅ (engine) / ⏳ (UI)
- `core/curves.py` — monotone cubic (Fritsch–Carlson PCHIP) → 256-LUT, master +
  per-channel R/G/B in a single `cv2.LUT`. No SciPy dep. Tested for monotonicity /
  no overshoot. UI curve editor still to build.

### Phase 4 — Classical heal / erase ✅
- `core/heal.py` — dispatch by mask size: `cv2.inpaint` (Telea/NS) now; hook to a
  LaMa backend (`core/backends/inpaint_lama.py`) with graceful fallback for Phase 7.
- UI: 🖌 Select + 🩹 Erase selection → adds an undoable heal layer.

### Tests
- `tests/test_core.py` — 12 tests, all passing: curves identity/monotonicity, ops
  registry, film op, mask resolve/gradient/luminance, masked composite, proxy vs
  full-res shapes, undo/redo, classical heal, colour match.
- Headless offscreen smoke test: open 1600×1200 → adjust + film + erase + masked
  contrast + undo/redo → full-res save verified at 1600×1200.

### Notes / next
- Not yet built: SAM 2 + rembg segmentation (Phase 6), LaMa erase (Phase 7),
  seamless-paste UI + auto colour-match (Phase 5 UI), curve editor + layers panel.
- ML deps intentionally left commented in `requirements.txt` — everything above
  runs CPU-only with zero models.
