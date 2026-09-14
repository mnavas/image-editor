# Installation Guide

## Prerequisites

- **Python 3.11 or newer** — [python.org/downloads](https://www.python.org/downloads/)
- **pip** (bundled with Python 3.11+)
- **git** (to clone the repository)

image-editor is a desktop app built on **PyQt6 + OpenCV + NumPy**. The core editor
has no build step and needs no models — clone, install a handful of Python
dependencies, and run. The AI features (erase a person, tap-to-select) are an
**optional** extra install (see [AI features](#optional-ai-features) below).

---

## Linux

### 1 — System dependencies

PyQt6 needs a few system libraries that may be missing on a minimal install.

**Ubuntu / Debian:**
```bash
sudo apt update
sudo apt install python3-dev libxcb-cursor0 libgl1
```

**Fedora / RHEL:**
```bash
sudo dnf install python3-devel xcb-util-cursor mesa-libGL
```

**Arch:**
```bash
sudo pacman -S xcb-util-cursor mesa
```

> If you see `qt.qpa.plugin: could not load the Qt platform plugin "xcb"` on
> launch, the `libxcb-cursor0` package is likely missing.

### 2 — Clone and run

```bash
git clone https://github.com/mnavas/image-editor.git
cd image-editor
./launch.sh
```

`launch.sh` creates a local `.venv`, installs the dependencies from
`requirements.txt` on first run, and launches the app. Every run after that just
starts the app.

### 3 — Run by hand (optional)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

### 4 — Desktop launcher (optional)

```bash
cat > ~/.local/share/applications/image-editor.desktop << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=image-editor
Comment=Full-resolution non-destructive photo editor
Exec=/absolute/path/to/image-editor/launch.sh
Icon=shotwell
Terminal=false
Categories=Graphics;Photography;
StartupNotify=true
EOF
chmod +x /absolute/path/to/image-editor/launch.sh
update-desktop-database ~/.local/share/applications/
```

---

## macOS

```bash
git clone https://github.com/mnavas/image-editor.git
cd image-editor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

The `launch.sh` launcher works on macOS too.

---

## Windows

Open **PowerShell** or **Command Prompt**:

```powershell
git clone https://github.com/mnavas/image-editor.git
cd image-editor
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

> `launch.sh` is a Bash script — on Windows launch with `python main.py` (or run
> it from Git Bash / WSL).

---

## Core dependencies

All are in `requirements.txt` — CPU-only, no account, no internet needed:

| Package | Version | Purpose |
|---------|---------|---------|
| `PyQt6` | ≥ 6.6 | UI framework |
| `opencv-contrib-python` | ≥ 4.9 | Image maths, blending, and the edge-aware (guided-filter) masks |
| `numpy` | ≥ 1.24 | Array maths for the edit pipeline |
| `Pillow` | ≥ 10.0 | Extra image I/O |
| `send2trash` | ≥ 1.8 | Safe deletes |

> The core editor — adjustments, curves, local edits, crop/rotate, film & camera
> looks, reshape/liquify, seamless paste, classical heal, `.iedit` projects, and
> **full-resolution export** — runs entirely on these, CPU-only.

---

## Optional: AI features

Two headline features are AI-powered and installed **separately** so the base app
stays light. They reuse **CPU-only PyTorch** — no GPU required (a GPU just makes
them faster).

### Erase / Remove person (LaMa)

`simple-lama-inpainting`'s own pins are hostile (they force an old Pillow, downgrade
NumPy, and pull the full CUDA toolkit). Install it deliberately, in **two steps**:

```bash
# 1) CPU-only PyTorch (skips the multi-GB CUDA packages)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 2) the LaMa wrapper, WITHOUT its dependency pins
pip install --no-deps simple-lama-inpainting fire
```

The ~200 MB LaMa model downloads automatically to `~/.cache/torch/hub/` on the
first erase.

### Tap / brush to select a person (SAM)

```bash
pip install --no-deps segment-anything
```

The ViT-B checkpoint (~358 MB) downloads automatically to `~/.cache/image-editor/`
on first use, or fetch it manually:

```bash
curl -L -o ~/.cache/image-editor/sam_vit_b_01ec64.pth \
  https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth
```

**If these aren't installed**, the app still runs — *Erase* falls back to classical
inpainting (fine for small blemishes) and *Remove person* is unavailable.

> ⚠️ **Licences:** the LaMa and SAM model weights carry their own licences, distinct
> from this app's code. Check them before any commercial use.

---

## First launch

**Open** a photo, then edit non-destructively:
adjust, draw a selection to edit part of the image, erase distractions, reshape,
or paste something in. **Save As** always renders at full resolution; **Save
Project** (`.iedit`) lets you reopen and keep editing later. See
[user-guide.md](user-guide.md) for the full workflow.
