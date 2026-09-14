# image-editor

A standalone desktop photo editor with **Photoshop-grade capabilities and
phone-app-level ease of use** — that saves at **full original resolution**.

Built because phone editing apps downscale and re-compress your photos, throwing
away resolution. This edits non-destructively and always renders the final image
at native resolution with real quality control.

> Status: early. Phases 0–4 (core + local edits + classical erase) work today,
> CPU-only, no ML models required. See [docs/plan.md](docs/plan.md) for the
> roadmap, [docs/changelog.md](docs/changelog.md) for what's done, and
> [docs/analysis.md](docs/analysis.md) for the feature research.

## What works now

- Open / zoom / pan; **Save As at full resolution** (JPEG quality / PNG control).
- Adjustments (whole image **or** brushed selection): exposure, brightness,
  contrast, highlights, shadows, saturation, vibrance, temperature, tint.
- **Tone/colour curves** — master + per-channel R/G/B, draggable points; works
  globally or on a selection (Apply to selection).
- 30 looks: camera profiles (standard, vivid, neutral, faithful, flat, landscape,
  portrait, monochrome) + high/low-contrast presets + 20 Fujifilm-inspired film sims.
- **Crop** (composes, follows rotation) and **rotate** ⟲ / ⟳.
- 🖌 brush a selection → apply adjustments to **only that region**, with a
  **border-smoothing (feather)** control and edge-aware masking so it blends; the
  selection shows as an outline (not an obscuring fill) with a live preview.
- 🧍 **Remove person** — brush roughly over someone, and SAM segments them
  precisely, then LaMa fills the background. 🎯 **Select subject** refines a rough
  brush to the exact object for erasing or local adjustment. (Optional install.)
- 🩹 **Erase** objects/people — LaMa AI fills the background (runs off the UI thread),
  classical inpainting for small blemishes; auto colour-match.
- 📎 **Insert / paste** another image — Poisson-blended and colour-matched so it
  belongs in the scene (cutout PNG transparency supported).
- 🫳 **Reshape / liquify** — a push brush to slim or reshape a body/object; drag an
  edge inward. Non-destructive (stored as a warp field).
- **Layers panel** — see, hide, re-opacity, and delete every committed local edit.
- **Save/Open Project (`.iedit`)** — reopen an edit later and keep tweaking
  (non-destructive; the exported image stays a separate flat file).
- Local contrast is **luminance-only**, so a boosted region keeps its natural colour.
- Fully **non-destructive**, resolution-independent engine; undo/redo.

## Coming (see plan / changelog)

- Stable-Diffusion replace/outpaint, text-prompt looks, RAW/HEIC, batch (Phase 8).

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Test

```bash
.venv/bin/python -m pytest tests -q
```

## Documentation

- **[docs/installation.md](docs/installation.md)** — full setup, including the optional CPU-only AI models.
- **[docs/user-guide.md](docs/user-guide.md)** — the complete editing workflow.
- **[docs/architecture.md](docs/architecture.md)** — module map, document model, and render pipeline.
- **[docs/analysis.md](docs/analysis.md)** / **[docs/plan.md](docs/plan.md)** / **[docs/changelog.md](docs/changelog.md)** — research, roadmap, and what's built.

A landing page lives at **[index.html](index.html)** (ready for GitHub Pages).

## Architecture

The editing engine (`core/`) has **zero Qt imports** — pure NumPy/OpenCV, so it
can also back a headless / MCP process. `widgets/` is the Qt view;
`app_controller.py` mediates. The same `Document.render(scale)` produces both the
live proxy preview and the full-resolution export, guaranteeing WYSIWYG.
