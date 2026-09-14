"""MainWindow — phone-simple layout over the Photoshop-grade engine.

Left: the canvas. Right: a tabbed rail (Adjust / Curves / Layers). Toolbar:
Open / Save / Undo / Redo and geometry tools (Crop / Rotate). The live preview
renders a proxy on a 60 ms debounce; Save always renders full resolution; the
heavy LaMa erase runs on a background thread so the UI never freezes.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QScrollArea,
    QSlider, QTabWidget, QVBoxLayout, QWidget,
)

from app_controller import GLOBAL_ADJUST_KEYS, AppController
from config import Config
from core.film_luts import FILM_SIMS
from widgets.canvas import Canvas
from widgets.curve_editor import CurveEditor

# The native OS file dialog matches globs case-sensitively, so plain "*.jpg" hides
# ".JPG" and folders look empty. List both cases.
_IMG_EXTS = ("jpg", "jpeg", "jpe", "jfif", "png", "tif", "tiff", "bmp", "webp")
_PATTERNS = " ".join(f"*.{e} *.{e.upper()}" for e in _IMG_EXTS)
_OPEN_FILTER = f"Images ({_PATTERNS});;All files (*)"


class _RenderWorker(QThread):
    """Runs a pure (Qt-free) render callable off the main thread."""
    done = pyqtSignal(object)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn())
        except Exception:
            self.done.emit(None)


class MainWindow(QMainWindow):
    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.ctl = AppController(config)
        self.setWindowTitle("image-editor")
        self.resize(1360, 900)

        self._show_selection = True
        self.canvas = Canvas()
        self.canvas.brush_started.connect(self._brush_started)
        self.canvas.brush_moved.connect(self._brush_moved)
        self.canvas.brush_ended.connect(self._brush_ended)
        self.canvas.warp_dragged.connect(self._warp_dragged)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.canvas, 1)
        root.addWidget(self._build_rail())
        self.setCentralWidget(central)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(60)
        self._preview_timer.timeout.connect(self._render_preview)

        self._worker = None
        self._build_toolbar()
        self._set_enabled(False)

    # --- UI construction ---------------------------------------------------

    def _build_toolbar(self):
        tb = self.addToolBar("main")
        tb.setMovable(False)
        specs = [("Open", self._open), ("Save As", self._save), (None, None),
                 ("Open Project", self._open_project), ("Save Project", self._save_project),
                 (None, None),
                 ("Undo", self._undo), ("Redo", self._redo), (None, None),
                 ("Crop", self._crop_tool), ("Apply Crop", self._apply_crop),
                 ("Reset Crop", self._reset_crop),
                 ("⟲", lambda: self._rotate(False)), ("⟳", lambda: self._rotate(True))]
        self._tb_buttons = []
        for label, slot in specs:
            if label is None:
                tb.addSeparator()
                continue
            b = QPushButton(label)
            b.clicked.connect(slot)
            tb.addWidget(b)
            if label not in ("Open", "Open Project"):
                self._tb_buttons.append(b)

    def _build_rail(self) -> QWidget:
        tabs = QTabWidget()
        tabs.setFixedWidth(320)
        tabs.addTab(self._adjust_tab(), "Adjust")
        tabs.addTab(self._curves_tab(), "Curves")
        tabs.addTab(self._reshape_tab(), "Reshape")
        tabs.addTab(self._paste_tab(), "Paste")
        tabs.addTab(self._layers_tab(), "Layers")
        tabs.currentChanged.connect(lambda *_: self._refresh_layers())
        return tabs

    def _adjust_tab(self) -> QWidget:
        rail = QWidget()
        v = QVBoxLayout(rail)

        v.addWidget(self._header("Tools"))
        tools = QHBoxLayout()
        self.btn_hand = QPushButton("✋ Move")
        self.btn_brush = QPushButton("🖌 Select")
        for b in (self.btn_hand, self.btn_brush):
            b.setCheckable(True)
        self.btn_hand.setChecked(True)
        self.btn_hand.clicked.connect(lambda: self._set_tool("hand"))
        self.btn_brush.clicked.connect(lambda: self._set_tool("brush"))
        tools.addWidget(self.btn_hand)
        tools.addWidget(self.btn_brush)
        v.addLayout(tools)

        v.addWidget(QLabel("Brush size"))
        self.brush_slider = QSlider(Qt.Orientation.Horizontal)
        self.brush_slider.setRange(1, 20)
        self.brush_slider.setValue(3)
        self.brush_slider.valueChanged.connect(
            lambda x: setattr(self.ctl, "brush_radius", x / 100.0))
        v.addWidget(self.brush_slider)

        row = QHBoxLayout()
        self.btn_erase = QPushButton("🩹 Erase selection")
        self.btn_erase.clicked.connect(self._erase)
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self._clear_sel)
        row.addWidget(self.btn_erase)
        row.addWidget(self.btn_clear)
        v.addLayout(row)

        row2 = QHBoxLayout()
        self.btn_person = QPushButton("🧍 Remove person")
        self.btn_person.clicked.connect(self._remove_person)
        self.btn_subject = QPushButton("🎯 Select subject")
        self.btn_subject.clicked.connect(self._select_subject)
        row2.addWidget(self.btn_person)
        row2.addWidget(self.btn_subject)
        v.addLayout(row2)

        self.chk_show_sel = QCheckBox("Show selection outline")
        self.chk_show_sel.setChecked(True)
        self.chk_show_sel.toggled.connect(self._toggle_show_sel)
        v.addWidget(self.chk_show_sel)

        v.addWidget(self._header("Adjust"))
        mode = QHBoxLayout()
        self.btn_mode_global = QPushButton("Whole image")
        self.btn_mode_sel = QPushButton("Selection only")
        for b in (self.btn_mode_global, self.btn_mode_sel):
            b.setCheckable(True)
        self.btn_mode_global.setChecked(True)
        self.btn_mode_global.clicked.connect(lambda: self._set_mode("global"))
        self.btn_mode_sel.clicked.connect(lambda: self._set_mode("selection"))
        mode.addWidget(self.btn_mode_global)
        mode.addWidget(self.btn_mode_sel)
        v.addLayout(mode)

        self.sliders = {}
        for key in GLOBAL_ADJUST_KEYS:
            v.addWidget(QLabel(key.capitalize()))
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(-100, 100)
            s.setValue(0)
            s.valueChanged.connect(lambda val, k=key: self._on_slider(k, val))
            self.sliders[key] = s
            v.addWidget(s)

        self.lbl_feather = QLabel("Border smoothing (feather)")
        v.addWidget(self.lbl_feather)
        self.feather_slider = QSlider(Qt.Orientation.Horizontal)
        self.feather_slider.setRange(0, 100)
        self.feather_slider.setValue(13)
        self.feather_slider.valueChanged.connect(self._on_feather)
        v.addWidget(self.feather_slider)

        self.chk_edge = QCheckBox("Snap border to edges (edge-aware)")
        self.chk_edge.setChecked(True)
        self.chk_edge.toggled.connect(self._on_edge_aware)
        v.addWidget(self.chk_edge)

        self.btn_apply_sel = QPushButton("✓ Apply to selection")
        self.btn_apply_sel.clicked.connect(self._commit_local)
        v.addWidget(self.btn_apply_sel)

        v.addWidget(self._header("Film look (whole image)"))
        self.film_box = QComboBox()
        self.film_box.addItem("original")
        for name in FILM_SIMS:
            self.film_box.addItem(name)
        self.film_box.currentTextChanged.connect(self._on_film)
        v.addWidget(self.film_box)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        v.addStretch(1)
        return self._scroll(rail)

    def _curves_tab(self) -> QWidget:
        rail = QWidget()
        v = QVBoxLayout(rail)
        v.addWidget(self._header("Tone / colour curves"))
        self.curve_target_lbl = QLabel("Editing: whole image")
        self.curve_target_lbl.setStyleSheet("color: #888;")
        v.addWidget(self.curve_target_lbl)
        v.addWidget(QLabel("Switch Whole image / Selection in the Adjust tab."))

        self.curve_channel = QComboBox()
        self.curve_channel.addItems(["master", "r", "g", "b"])
        self.curve_channel.currentTextChanged.connect(
            lambda ch: self.curve_editor.set_channel(ch))
        v.addWidget(self.curve_channel)

        self.curve_editor = CurveEditor()
        self.curve_editor.changed.connect(self._on_curves)
        v.addWidget(self.curve_editor)

        v.addWidget(QLabel("Click to add a point, drag to shape, right-click to remove.\n"
                           "An S-curve adds contrast; per-channel shifts colour."))
        self.btn_apply_curve = QPushButton("✓ Apply to selection")
        self.btn_apply_curve.clicked.connect(self._commit_local)
        self.btn_apply_curve.setEnabled(False)
        v.addWidget(self.btn_apply_curve)
        btn_reset = QPushButton("Reset curves")
        btn_reset.clicked.connect(self._reset_curves)
        v.addWidget(btn_reset)
        v.addStretch(1)
        return self._scroll(rail)

    def _reshape_tab(self) -> QWidget:
        rail = QWidget()
        v = QVBoxLayout(rail)
        v.addWidget(self._header("Reshape (liquify / slim)"))
        v.addWidget(QLabel("Push pixels to reshape a body or object — e.g. drag an\n"
                           "edge inward to slim. Turn on the brush, then drag on the\n"
                           "image. Apply to keep it (undoable)."))
        self.btn_reshape = QPushButton("🫳 Reshape brush")
        self.btn_reshape.setCheckable(True)
        self.btn_reshape.clicked.connect(self._toggle_reshape)
        v.addWidget(self.btn_reshape)

        v.addWidget(QLabel("Brush size"))
        self.warp_size = QSlider(Qt.Orientation.Horizontal)
        self.warp_size.setRange(3, 50); self.warp_size.setValue(12)
        self.warp_size.valueChanged.connect(lambda x: self.ctl.set_warp_radius(x / 100.0))
        v.addWidget(self.warp_size)

        v.addWidget(QLabel("Strength"))
        self.warp_strength = QSlider(Qt.Orientation.Horizontal)
        self.warp_strength.setRange(5, 100); self.warp_strength.setValue(50)
        self.warp_strength.valueChanged.connect(lambda x: self.ctl.set_warp_strength(x / 100.0))
        v.addWidget(self.warp_strength)

        row = QHBoxLayout()
        self.btn_apply_warp = QPushButton("✓ Apply reshape")
        self.btn_apply_warp.clicked.connect(self._apply_warp)
        self.btn_reset_warp = QPushButton("Reset")
        self.btn_reset_warp.clicked.connect(self._reset_warp)
        row.addWidget(self.btn_apply_warp); row.addWidget(self.btn_reset_warp)
        v.addLayout(row)
        v.addStretch(1)
        return self._scroll(rail)

    def _paste_tab(self) -> QWidget:
        rail = QWidget()
        v = QVBoxLayout(rail)
        v.addWidget(self._header("Insert / paste an image"))
        v.addWidget(QLabel("Blends another image in seamlessly (Poisson) and\n"
                           "colour-matches it. A cutout PNG's transparency is used\n"
                           "as the shape; otherwise the whole rectangle is blended."))
        self.btn_insert = QPushButton("📎 Insert image…")
        self.btn_insert.clicked.connect(self._insert_image)
        v.addWidget(self.btn_insert)

        self.paste_controls = []
        self.paste_sliders = {}
        for key, lo, hi, val, label in (("cx", 0, 100, 50, "Position X"),
                                        ("cy", 0, 100, 50, "Position Y"),
                                        ("scale", 5, 100, 40, "Size (% of width)")):
            lbl = QLabel(label)
            v.addWidget(lbl)
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(lo, hi); s.setValue(val)
            s.valueChanged.connect(lambda x, k=key: self._on_paste_slider(k, x))
            v.addWidget(s)
            self.paste_sliders[key] = s
            self.paste_controls += [lbl, s]

        self.chk_mixed = QCheckBox("Mixed clone (keep destination texture)")
        self.chk_mixed.toggled.connect(lambda on: self._on_paste_flag("mixed", on))
        self.chk_match = QCheckBox("Match colour to surroundings")
        self.chk_match.setChecked(True)
        self.chk_match.toggled.connect(lambda on: self._on_paste_flag("match", on))
        v.addWidget(self.chk_mixed)
        v.addWidget(self.chk_match)
        self.paste_controls += [self.chk_mixed, self.chk_match]

        row = QHBoxLayout()
        self.btn_apply_paste = QPushButton("✓ Apply paste")
        self.btn_apply_paste.clicked.connect(self._apply_paste)
        self.btn_cancel_paste = QPushButton("Cancel")
        self.btn_cancel_paste.clicked.connect(self._cancel_paste)
        row.addWidget(self.btn_apply_paste); row.addWidget(self.btn_cancel_paste)
        v.addLayout(row)
        self.paste_controls += [self.btn_apply_paste, self.btn_cancel_paste]

        for w in self.paste_controls:
            w.setEnabled(False)
        v.addStretch(1)
        return self._scroll(rail)

    def _layers_tab(self) -> QWidget:
        rail = QWidget()
        v = QVBoxLayout(rail)
        v.addWidget(self._header("Layers (edits)"))
        self.layer_list = QListWidget()
        self.layer_list.itemChanged.connect(self._on_layer_check)
        self.layer_list.currentRowChanged.connect(self._on_layer_selected)
        v.addWidget(self.layer_list, 1)

        v.addWidget(QLabel("Opacity"))
        self.layer_opacity = QSlider(Qt.Orientation.Horizontal)
        self.layer_opacity.setRange(0, 100)
        self.layer_opacity.setValue(100)
        self.layer_opacity.valueChanged.connect(self._on_layer_opacity)
        v.addWidget(self.layer_opacity)

        self.btn_del_layer = QPushButton("Delete layer")
        self.btn_del_layer.clicked.connect(self._delete_layer)
        v.addWidget(self.btn_del_layer)

        v.addWidget(QLabel("Global sliders, curves and film look apply on top and\n"
                           "aren't listed here — only committed local edits are."))
        return self._scroll(rail)

    def _scroll(self, w) -> QScrollArea:
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setWidget(w)
        return s

    def _header(self, text) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight: bold; margin-top: 8px;")
        return lbl

    # --- file --------------------------------------------------------------

    def _open(self):
        start = self.config.last_dir or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Open image", start, _OPEN_FILTER)
        if not path:
            return
        if not self.ctl.open(path):
            QMessageBox.warning(self, "image-editor", "Could not open that image.")
            return
        self._reset_controls()
        self._set_enabled(True)
        self.canvas.set_array(self.ctl.render(), reset=True)
        self._refresh_layers()
        h, w = self.ctl.doc.base.shape[:2]
        self.setWindowTitle(f"image-editor — {Path(path).name} ({w}×{h})")

    def _save(self):
        if self.ctl.doc is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save As", str(self.ctl.path), _OPEN_FILTER)
        if not path:
            return
        if Path(path).suffix == "":
            path += self.ctl.path.suffix
        self.status.setText("Saving full resolution…")
        _process_events()
        if self.ctl.save(path):
            self.status.setText(f"Saved {Path(path).name} at full resolution.")
        else:
            QMessageBox.warning(self, "image-editor", "Save failed.")

    # --- project (.iedit) --------------------------------------------------

    _PROJ_FILTER = "image-editor project (*.iedit)"

    def _save_project(self):
        if self.ctl.doc is None:
            return
        start = str(self.ctl.path.with_suffix(".iedit")) if self.ctl.path else ""
        path, _ = QFileDialog.getSaveFileName(self, "Save Project", start, self._PROJ_FILTER)
        if not path:
            return
        if Path(path).suffix == "":
            path += ".iedit"
        if self.ctl.save_project(path):
            self.status.setText(f"Project saved: {Path(path).name} (reopen to keep editing).")
        else:
            QMessageBox.warning(self, "image-editor", "Could not save project.")

    def _open_project(self):
        start = self.config.last_dir or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", start, self._PROJ_FILTER)
        if not path:
            return
        if not self.ctl.load_project(path):
            QMessageBox.warning(self, "image-editor",
                                "Could not open the project (is the source image still there?).")
            return
        self._set_enabled(True)
        self._sync_controls_from_ctl()
        self.canvas.set_array(self.ctl.render(), reset=True)
        self._refresh_layers()
        self.setWindowTitle(f"image-editor — {Path(path).name}")
        self.status.setText("Project loaded.")

    def _sync_controls_from_ctl(self):
        """Push loaded controller state (adjust/film/curves/mode) into the widgets."""
        for k, s in self.sliders.items():
            v = self.ctl.adjust.get(k, 0.0)
            ui = int(v / 3.0 * 100) if k == "exposure" else int(v)
            s.blockSignals(True); s.setValue(ui); s.blockSignals(False)
        self.film_box.blockSignals(True)
        self.film_box.setCurrentText(self.ctl.film or "original")
        self.film_box.blockSignals(False)
        self.curve_editor.blockSignals(True)
        self.curve_editor.set_all(self.ctl.curves or {})
        self.curve_editor.blockSignals(False)
        self.ctl.set_mode("global")
        self.btn_mode_global.setChecked(True)
        self.btn_mode_sel.setChecked(False)

    def _undo(self):
        if self.ctl.undo():
            self._refresh_layers()
            self._render_preview()

    def _redo(self):
        if self.ctl.redo():
            self._refresh_layers()
            self._render_preview()

    # --- geometry ----------------------------------------------------------

    def _crop_tool(self):
        self._set_tool("crop")
        self.status.setText("Drag a rectangle, then 'Apply Crop'.")

    def _apply_crop(self):
        rect = self.canvas.get_crop_rect()
        if rect and rect[2] > 0.01 and rect[3] > 0.01:
            self.ctl.apply_crop(rect)
            self._set_tool("hand")
            self.canvas.set_array(self.ctl.render(), reset=True)
        else:
            self.status.setText("Draw a crop rectangle first (Crop tool).")

    def _reset_crop(self):
        self.ctl.clear_crop()
        self.canvas.set_array(self.ctl.render(), reset=True)

    def _rotate(self, cw):
        if self.ctl.doc is None:
            return
        self.ctl.rotate(cw)
        self.canvas.set_array(self.ctl.render(), reset=True)

    # --- tools / modes -----------------------------------------------------

    def _set_tool(self, tool):
        self.btn_hand.setChecked(tool == "hand")
        self.btn_brush.setChecked(tool == "brush")
        if hasattr(self, "btn_reshape"):
            self.btn_reshape.setChecked(tool == "warp")
        self.canvas.set_tool(tool)

    def _on_slider(self, key, val):
        value = (val / 100.0) * 3.0 if key == "exposure" else float(val)
        if self.ctl.mode == "selection":
            self.ctl.set_local(key, value)
        else:
            self.ctl.set_adjust(key, value)
        self._preview_timer.start()

    def _on_film(self, name):
        self.ctl.set_film(name)
        self._preview_timer.start()

    def _on_curves(self):
        pts = self.curve_editor.get_all()
        if self.ctl.mode == "selection":
            self.ctl.set_local_curves(**pts)
        else:
            self.ctl.set_curves(**pts)
        self._preview_timer.start()

    def _reset_curves(self):
        self.curve_editor.reset()   # emits changed → routed by mode

    def _set_mode(self, mode):
        self.btn_mode_global.setChecked(mode == "global")
        self.btn_mode_sel.setChecked(mode == "selection")
        self.ctl.set_mode(mode)
        for s in self.sliders.values():
            s.blockSignals(True); s.setValue(0); s.blockSignals(False)
        self.ctl.reset_local()
        # curves editor follows the target (whole image vs selection)
        self.curve_editor.blockSignals(True)
        self.curve_editor.set_all(self.ctl.local_curves if mode == "selection" else self.ctl.curves)
        self.curve_editor.blockSignals(False)
        self.curve_target_lbl.setText("Editing: " + ("selection" if mode == "selection" else "whole image"))
        for w in (self.lbl_feather, self.feather_slider, self.chk_edge,
                  self.btn_apply_sel, self.btn_apply_curve):
            w.setEnabled(mode == "selection")
        if mode == "selection":
            self.status.setText("Brush a region with 🖌, tune sliders, then Apply. "
                                "Use 'Border smoothing' so the edit blends.")
            self._set_tool("brush")
        self._show_mask()
        self._preview_timer.start()

    def _on_feather(self, val):
        self.ctl.set_feather(val / 100.0 * 0.15)
        self._show_mask()
        self._preview_timer.start()

    def _on_edge_aware(self, on):
        self.ctl.set_edge_aware(on)
        self._show_mask()
        self._preview_timer.start()

    def _commit_local(self):
        if self.ctl.commit_local():
            for s in self.sliders.values():
                s.blockSignals(True); s.setValue(0); s.blockSignals(False)
            self.curve_editor.blockSignals(True)
            self.curve_editor.set_all({})          # local curves were baked in
            self.curve_editor.blockSignals(False)
            self._show_mask(filled=False)
            self._refresh_layers()
            self.status.setText("Applied. Not right? Undo, then re-tune the same "
                                "selection — no need to re-brush. Or Clear to drop it.")
            self._render_preview()
        else:
            self.status.setText("Brush a region and move a slider first.")

    # --- brush -------------------------------------------------------------

    def _brush_started(self, x, y):
        self.ctl.brush_start(x, y)
        self._show_mask(filled=True)

    def _brush_moved(self, x, y):
        self.ctl.brush_point(x, y)
        self._show_mask(filled=True)

    def _brush_ended(self):
        self.ctl.brush_end()
        self._show_mask(filled=False)
        self._preview_timer.start()

    def _show_mask(self, filled: bool = False):
        if not self._show_selection:
            self.canvas.set_overlay(None)
            return
        self.canvas.set_overlay(self.ctl.current_mask_array(), filled=filled)

    def _toggle_show_sel(self, on):
        self._show_selection = on
        self._show_mask()   # selection is kept; only its display changes

    def _has_selection(self) -> bool:
        return self.ctl.pending_mask is not None and not self.ctl.pending_mask.is_empty()

    def _erase(self):
        if not self.ctl.erase_selection():
            self.status.setText("Select an area with the 🖌 tool first.")
            return
        self.canvas.set_overlay(None)
        self._refresh_layers()
        engine = "LaMa AI" if self.ctl.lama_available() else "classical"
        self.status.setText(f"Filling background ({engine})…")
        self._run_job(lambda: (True, self.ctl.render()),
                      lambda _ok: self.status.setText("Erased. (Undo in toolbar.)"))

    def _remove_person(self):
        if not self._has_selection():
            self.status.setText("Brush roughly over the person first, then Remove person.")
            return
        if not self.ctl.segmentation_available():
            self.status.setText("SAM model unavailable — erasing the brushed area instead.")
            self._erase()
            return
        self.canvas.set_overlay(None)
        self.status.setText("Finding the person (SAM) and filling the background (LaMa)… "
                            "first run also loads the model, so give it a moment.")

        def work():
            ok = self.ctl.remove_person_in_selection()   # SAM refine + add heal layer
            return (ok, self.ctl.render())               # LaMa runs here, off-thread

        def done(res):
            self._refresh_layers()
            self.status.setText("Person removed. (Undo in toolbar.)" if res[0]
                                else "Couldn't segment a person — try a bigger/rougher selection.")
        self._run_job(work, done)

    def _select_subject(self):
        if not self._has_selection():
            self.status.setText("Brush roughly over the subject first, then Select subject.")
            return
        if not self.ctl.segmentation_available():
            self.status.setText("SAM model unavailable (see requirements.txt Phase 6).")
            return
        self.status.setText("Finding the subject (SAM)…")

        def work():
            ok = self.ctl.refine_to_subject()
            return (ok, self.ctl.render())

        def done(res):
            self._show_mask(filled=False)
            self.status.setText("Subject selected — now Erase, or apply an adjustment." if res[0]
                                else "No subject found — try a bigger selection.")
        self._run_job(work, done)

    def _clear_sel(self):
        self.ctl.clear_selection()
        self.canvas.set_overlay(None)

    # --- paste -------------------------------------------------------------

    def _insert_image(self):
        if self.ctl.doc is None:
            return
        start = self.config.last_dir or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Insert image", start, _OPEN_FILTER)
        if not path:
            return
        if not self.ctl.insert_image(path):
            QMessageBox.warning(self, "image-editor", "Could not load that image.")
            return
        for w in self.paste_controls:
            w.setEnabled(True)
        for k, dv in (("cx", 50), ("cy", 50), ("scale", 40)):
            self.paste_sliders[k].blockSignals(True)
            self.paste_sliders[k].setValue(dv)
            self.paste_sliders[k].blockSignals(False)
        self.status.setText("Position & size the pasted image, then Apply paste.")
        self._render_preview()

    def _on_paste_slider(self, key, x):
        self.ctl.set_paste_param(key, x / 100.0)
        self._preview_timer.start()

    def _on_paste_flag(self, key, on):
        self.ctl.set_paste_param(key, bool(on))
        self._preview_timer.start()

    def _apply_paste(self):
        if self.ctl.commit_paste():
            for w in self.paste_controls:
                w.setEnabled(False)
            self._refresh_layers()
            self.status.setText("Paste applied (blended). Undo in toolbar.")
            self._render_preview()

    def _cancel_paste(self):
        self.ctl.cancel_paste()
        for w in self.paste_controls:
            w.setEnabled(False)
        self._render_preview()

    # --- reshape / liquify -------------------------------------------------

    def _toggle_reshape(self, on):
        self._set_tool("warp" if on else "hand")
        self.status.setText("Drag on the image to reshape; Apply to keep it." if on
                            else "")

    def _warp_dragged(self, x0, y0, x1, y1):
        self.ctl.warp_stroke(x0, y0, x1, y1)
        self._preview_timer.start()

    def _apply_warp(self):
        if self.ctl.commit_warp():
            self.btn_reshape.setChecked(False)
            self._set_tool("hand")
            self._refresh_layers()
            self.status.setText("Reshape applied. Undo in toolbar.")
            self._render_preview()
        else:
            self.status.setText("Drag on the image with the Reshape brush first.")

    def _reset_warp(self):
        self.ctl.cancel_warp()
        self._render_preview()

    # --- background jobs (heavy ML ops) ------------------------------------

    def _run_job(self, work_fn, on_done):
        """Run a heavy (Qt-free) job off-thread; work_fn returns (ok, image)."""
        self._set_busy(True)
        self._worker = _RenderWorker(work_fn)

        def finished(result):
            if isinstance(result, tuple) and result[1] is not None:
                self.canvas.set_array(result[1])
            self._set_busy(False)
            on_done(result if isinstance(result, tuple) else (False, None))

        self._worker.done.connect(finished)
        self._worker.start()

    def _set_busy(self, busy):
        self.setCursor(Qt.CursorShape.WaitCursor if busy else Qt.CursorShape.ArrowCursor)
        self.centralWidget().setEnabled(not busy)

    # --- layers panel ------------------------------------------------------

    def _refresh_layers(self):
        if not hasattr(self, "layer_list"):
            return
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        for i, layer in enumerate(self.ctl.layers()):
            label = layer.name or layer.kind
            it = QListWidgetItem(f"{i + 1}. {label}")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if layer.visible
                             else Qt.CheckState.Unchecked)
            self.layer_list.addItem(it)
        self.layer_list.blockSignals(False)

    def _on_layer_check(self, item):
        i = self.layer_list.row(item)
        self.ctl.set_layer_visible(i, item.checkState() == Qt.CheckState.Checked)
        self._render_preview()

    def _on_layer_selected(self, row):
        layers = self.ctl.layers()
        if 0 <= row < len(layers):
            self.layer_opacity.blockSignals(True)
            self.layer_opacity.setValue(int(layers[row].opacity * 100))
            self.layer_opacity.blockSignals(False)

    def _on_layer_opacity(self, val):
        row = self.layer_list.currentRow()
        if row >= 0:
            self.ctl.set_layer_opacity(row, val / 100.0)
            self._render_preview()

    def _delete_layer(self):
        row = self.layer_list.currentRow()
        if row >= 0:
            self.ctl.remove_layer_at(row)
            self._refresh_layers()
            self._render_preview()

    # --- preview -----------------------------------------------------------

    def _render_preview(self):
        if self.ctl.doc is not None:
            self.canvas.set_array(self.ctl.render())

    def _reset_controls(self):
        for s in self.sliders.values():
            s.blockSignals(True); s.setValue(0); s.blockSignals(False)
        self.film_box.blockSignals(True)
        self.film_box.setCurrentText("original")
        self.film_box.blockSignals(False)
        self.curve_editor.blockSignals(True)
        self.curve_editor.reset()
        self.curve_editor.blockSignals(False)
        self.ctl.reset_adjust()
        self.ctl.reset_local()
        self.ctl.set_curves()
        self._set_mode("global")

    def _set_enabled(self, on):
        widgets = [self.btn_brush, self.btn_hand, self.btn_erase, self.btn_clear,
                   self.btn_person, self.btn_subject, self.btn_insert, self.chk_show_sel,
                   self.btn_mode_global, self.btn_mode_sel, self.film_box,
                   self.brush_slider, self.curve_channel, self.curve_editor,
                   self.btn_apply_curve,
                   self.btn_reshape, self.warp_size, self.warp_strength,
                   self.btn_apply_warp, self.btn_reset_warp,
                   self.layer_list, self.layer_opacity, self.btn_del_layer,
                   *self.sliders.values(), *getattr(self, "_tb_buttons", [])]
        for w in widgets:
            w.setEnabled(on)
        sel = on and self.ctl.mode == "selection"
        for w in (self.lbl_feather, self.feather_slider, self.chk_edge,
                  self.btn_apply_sel, self.btn_apply_curve):
            w.setEnabled(sel)


def _process_events():
    from PyQt6.QtWidgets import QApplication
    QApplication.processEvents()
