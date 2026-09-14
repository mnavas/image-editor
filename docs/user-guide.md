# image-editor — User Guide

## What is image-editor?

image-editor is a desktop photo editor with **Photoshop-grade capabilities and
phone-app-level ease of use** — that always saves at **full original resolution**.

It exists because phone editing apps downscale and re-compress your photos: you get
a soft, smaller JPEG back. image-editor edits **non-destructively** and renders the
final image at native resolution with real quality control.

---

## The Workflow at a Glance

1. **Open** a photo.
2. **Adjust** the whole image, or **draw a selection** and adjust only that part.
3. **Retouch**: erase distractions or a whole person, reshape/slim, paste something in.
4. **Save As** at full resolution — or **Save Project** (`.iedit`) to keep editing later.

Everything is non-destructive: your edits stack as layers you can hide, re-opacity,
delete, or undo, and the original pixels are never thrown away.

---

## Opening & Saving

- **Open** — pick a photo (JPEG, PNG, TIFF, BMP, WEBP). Paths with accents, ñ, or
  non-Latin characters work on every platform.
- **Save As** — renders the full-resolution result. JPEG saves at your configured
  quality; PNG/TIFF are lossless.
- **Save Project / Open Project** (`.iedit`) — stores the whole edit (layers, masks,
  adjustments, curves) next to the source image so you can reopen and refine it.
- **Zoom** with the mouse wheel, **pan** by dragging with the Move tool,
  double-click to reset.

---

## Adjust — whole image or a selection

The **Adjust** tab has two modes, toggled at the top:

- **Whole image** — the sliders affect everything.
- **Selection only** — brush a region with the 🖌 tool, and the sliders affect just
  that area, blended so it doesn't look edited.

Adjustments: **Exposure, Brightness, Contrast, Highlights, Shadows, Saturation,
Vibrance, Temperature, Tint**. (Local contrast is applied to luminance only, so a
boosted region keeps its natural colour.)

### Border smoothing

When editing a selection, the **Border smoothing (feather)** slider controls how
softly the edit fades at the edge, and **Snap border to edges** makes the boundary
follow real edges in the photo (e.g. stop at the horizon). Together they make a
local edit invisible.

- **Show selection outline** — toggle the outline off to judge the clean result
  without losing the selection, then back on to keep refining.
- **Apply to selection** bakes the current sliders (and curves) into one layer.

### Film & camera looks

The **Film look** dropdown carries camera picture profiles (Standard, Vivid,
Neutral, Faithful, Flat/Log, Landscape, Portrait, Monochrome, High/Low Contrast)
and 20 Fujifilm-inspired film simulations.

---

## Curves

The **Curves** tab is a draggable tone curve — click to add a point, drag to shape,
right-click to remove. An S-curve adds contrast; per-channel **R / G / B** shifts
colour. Curves follow the Adjust tab's Whole image / Selection target, and can be
**applied to a selection** just like the sliders.

---

## Retouch

### Erase distractions / a person 🩹 🧍

1. Switch to **Selection only** and brush over what you want gone.
2. **Erase selection** removes it — a small blemish uses fast classical inpainting;
   a larger object uses **LaMa AI**, which fills the background convincingly and
   colour-matches it. (LaMa is an optional install; see the install guide.)
3. To remove a **person**, brush roughly over them and press **🧍 Remove person** —
   **SAM** cuts them out precisely, then LaMa fills the gap. **🎯 Select subject**
   just refines a rough brush to the exact object.

AI steps run on a background thread, so the window stays responsive.

### Reshape / slim 🫳

The **Reshape** tab is a liquify push-brush. Turn on the **Reshape brush**, set the
**Brush size** and **Strength**, then drag on the image — for slimming, drag a body
edge inward. **Apply** keeps it (undoable). It's non-destructive: a smooth warp
field is stored, not baked pixels.

### Insert / paste an image 📎

The **Paste** tab composites another image into your photo. **Insert image** (a
cutout PNG's transparency is used as the shape), then set Position and Size. It's
**Poisson-blended** and **colour-matched** to the surroundings so it belongs in the
scene. **Mixed clone** preserves destination texture over busy backgrounds.

---

## Crop & Rotate

From the toolbar: **Crop** draws a rectangle (drag, then **Apply Crop**), and
**⟲ / ⟳** rotate 90°. Crops compose and follow rotation, so the frame never
desyncs.

---

## Layers

The **Layers** tab lists every committed local edit — a local adjustment, an erase,
a reshape, a paste. For each you can toggle **visibility**, change **opacity**, or
**delete** it. Whole-image sliders, curves, and the film look apply on top and
aren't listed here.

**Undo / Redo** (toolbar) step through your edits.

---

## Tips

- Work at any zoom — the preview uses a fast proxy, but **Save always renders full
  resolution**, so what you see is what you get.
- Small, soft edits look most natural: keep feather up for selections, and use
  gentle reshape pushes.
- Save an `.iedit` project before a big session so you can always come back and
  tweak instead of starting over.
