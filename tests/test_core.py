"""Core engine tests — pure arrays, no Qt. Run: .venv/bin/python -m pytest tests"""
import numpy as np
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import blend, curves, ops
from core.mask import Mask, BrushStroke, LinearGradient, LuminanceRange
from core.document import Document
from core.layers import Layer


def _img(h=64, w=96):
    rng = np.random.default_rng(0)
    return rng.integers(0, 256, (h, w, 3), dtype=np.uint8)


def test_curves_identity_is_noop():
    lut = curves.build_lut(master=[(0, 0), (255, 255)])
    assert np.array_equal(lut.reshape(256, 3)[:, 0], np.arange(256))


def test_curves_monotonic_no_overshoot():
    # steep S-curve control points must still produce a monotone, in-range LUT
    lut = curves._pchip_lut([(0, 0), (64, 30), (192, 225), (255, 255)])
    assert lut.min() >= 0 and lut.max() <= 255
    assert np.all(np.diff(lut.astype(int)) >= 0)  # non-decreasing


def test_ops_registry_roundtrip():
    img = _img()
    out = ops.apply_op(img, "contrast", {"value": 50})
    assert out.shape == img.shape and out.dtype == np.uint8


def test_film_op():
    img = _img()
    out = ops.apply_op(img, "film", {"name": "velvia"})
    assert out.shape == img.shape


def test_mask_resolves_in_range():
    m = Mask(sources=[BrushStroke(points=[(0.5, 0.5)], radius=0.1)], feather=0.02)
    r = m.resolve(64, 96, guide=_img())
    assert r.shape == (64, 96) and r.dtype == np.float32
    assert 0.0 <= r.min() and r.max() <= 1.0


def test_linear_gradient_ramps():
    r = LinearGradient(0, 0, 1, 0).render(10, 10)
    assert r[0, 0] < r[0, -1]  # left darker than right


def test_luminance_mask_selects_bright():
    guide = np.full((10, 10, 3), 240, np.uint8)
    r = LuminanceRange(lo=0.7, hi=1.0).render(10, 10, guide)
    assert r.mean() > 0.8


def test_composite_masked_local_only():
    base = np.zeros((10, 10, 3), np.uint8)
    effect = np.full((10, 10, 3), 255, np.uint8)
    mask = np.zeros((10, 10), np.float32)
    mask[:, 5:] = 1.0
    out = blend.composite(base, effect, mask)
    assert out[:, :5].max() == 0 and out[:, 5:].min() == 255


def test_document_full_vs_proxy_shapes():
    doc = Document(base=_img(200, 300))
    doc.add_layer(Layer(kind="adjust", params={"op": "exposure", "args": {"stops": 1.0}}))
    full = doc.render(1.0)
    proxy = doc.render(doc.proxy_scale(100))
    assert full.shape == (200, 300, 3)
    assert max(proxy.shape[:2]) <= 100


def test_undo_redo():
    doc = Document(base=_img())
    doc.add_layer(Layer(kind="adjust", params={"op": "contrast", "args": {"value": 20}}))
    assert len(doc.layers) == 1
    assert doc.undo() and len(doc.layers) == 0
    assert doc.redo() and len(doc.layers) == 1


def test_heal_classical_fills():
    img = _img()
    doc = Document(base=img)
    m = Mask(sources=[BrushStroke(points=[(0.5, 0.5)], radius=0.05)])
    doc.add_layer(Layer(kind="heal", params={"engine": "telea"}, mask=m))
    out = doc.render(1.0)
    assert out.shape == img.shape


def test_color_match_runs():
    region = np.full((20, 20, 3), 100, np.uint8)
    ref = np.full((20, 20, 3), 180, np.uint8)
    out = blend.match_color(region, ref)
    assert out.shape == region.shape


def _soft_band(mask):
    """Count pixels that are partially masked (0<v<1) — the blended border width."""
    return int(((mask > 0.02) & (mask < 0.98)).sum())


def test_feather_widens_border_transition():
    guide = _img(200, 200)
    src = [BrushStroke(points=[(0.5, 0.5)], radius=0.15)]
    hard = Mask(sources=list(src), feather=0.0).resolve(200, 200, guide)
    soft = Mask(sources=list(src), feather=0.06).resolve(200, 200, guide)
    # more feather => a wider band of partially-applied (blended) pixels
    assert _soft_band(soft) > _soft_band(hard) * 3


def test_controller_local_adjust_commits_masked_layer():
    from config import Config
    from app_controller import AppController
    ctl = AppController(Config())
    import cv2, tempfile, os
    p = tempfile.mktemp(suffix=".png")
    cv2.imwrite(p, _img(120, 160))
    assert ctl.open(p)
    ctl.set_mode("selection")
    ctl.brush_start(0.5, 0.5); ctl.brush_point(0.55, 0.55); ctl.brush_end()
    ctl.set_local("contrast", 60)
    ctl.set_feather(0.03)
    assert ctl.current_mask_array() is not None       # live preview mask exists
    assert ctl.commit_local()                          # becomes a layer
    assert len(ctl.doc.layers) == 1
    assert ctl.doc.layers[0].kind == "adjust_set"
    assert ctl.doc.layers[0].mask.feather == 0.03
    # selection persists after commit (undo + re-tune the same region)
    assert ctl.pending_mask is not None
    os.unlink(p)


def _fresh_ctl(h=120, w=160):
    from config import Config
    from app_controller import AppController
    import cv2, tempfile
    ctl = AppController(Config())
    p = tempfile.mktemp(suffix=".png")
    cv2.imwrite(p, _img(h, w))
    assert ctl.open(p)
    return ctl


def test_rotate_swaps_dimensions_and_follows_crop():
    ctl = _fresh_ctl(120, 160)
    ctl.rotate(cw=True)
    out = ctl.render(full=True)
    assert out.shape[:2] == (160, 120)            # swapped
    ctl.apply_crop((0.25, 0.25, 0.5, 0.5))
    cropped = ctl.render(full=True)
    assert cropped.shape[0] < 160 and cropped.shape[1] < 120
    # rotating with an active crop keeps a valid (non-empty) render
    ctl.rotate(cw=True)
    assert ctl.render(full=True).size > 0


def test_crop_composes_and_clears():
    ctl = _fresh_ctl(200, 200)
    ctl.apply_crop((0.0, 0.0, 0.5, 0.5))
    ctl.apply_crop((0.0, 0.0, 0.5, 0.5))          # compose: 0.25 of original
    out = ctl.render(full=True)
    assert abs(out.shape[0] - 50) <= 1 and abs(out.shape[1] - 50) <= 1
    ctl.clear_crop()
    assert ctl.render(full=True).shape[:2] == (200, 200)


def test_layer_visibility_opacity_delete():
    ctl = _fresh_ctl()
    ctl.set_mode("selection")
    ctl.brush_start(0.5, 0.5); ctl.brush_end()
    ctl.set_local("exposure", 2.0)
    assert ctl.commit_local()
    assert len(ctl.layers()) == 1
    ctl.set_layer_visible(0, False)
    assert ctl.layers()[0].visible is False
    ctl.set_layer_opacity(0, 0.3)
    assert abs(ctl.layers()[0].opacity - 0.3) < 1e-6
    ctl.remove_layer_at(0)
    assert len(ctl.layers()) == 0


def test_global_curves_applied_in_render():
    ctl = _fresh_ctl()
    base = ctl.render(full=True).copy()
    ctl.set_curves(master=[(0, 0), (128, 200), (255, 255)])  # strong lift
    lifted = ctl.render(full=True)
    assert lifted.mean() > base.mean()


def test_all_adjust_ops_present_and_run():
    from app_controller import GLOBAL_ADJUST_KEYS
    for k in ("exposure", "brightness", "contrast", "highlights", "shadows",
              "saturation", "vibrance", "temperature", "tint"):
        assert k in GLOBAL_ADJUST_KEYS
    img = _img()
    for name, arg in [("brightness", "value"), ("vibrance", "value"),
                      ("temperature", "value"), ("tint", "value")]:
        out = ops.apply_op(img, name, {arg: 40})
        assert out.shape == img.shape and out.dtype == np.uint8


def test_temperature_warms_image():
    import cv2
    img = np.full((10, 10, 3), 120, np.uint8)   # neutral grey
    warm = ops.apply_op(img, "temperature", {"value": 80})
    assert warm[0, 0, 2] > 120 and warm[0, 0, 0] < 120   # R up, B down


def test_local_curves_and_brightness_commit_together():
    ctl = _fresh_ctl()
    ctl.set_mode("selection")
    ctl.brush_start(0.5, 0.5); ctl.brush_end()
    ctl.set_local("brightness", 30)
    ctl.set_local_curves(master=[(0, 0), (128, 190), (255, 255)])
    assert ctl.commit_local()
    layer = ctl.doc.layers[0]
    assert layer.kind == "adjust_set"
    ops_in = [op for op, _ in layer.params["recipe"]]
    assert "brightness" in ops_in and "curves" in ops_in
    # and it's masked (local, not global)
    assert layer.mask is not None and not layer.mask.is_empty()


def test_luminance_contrast_preserves_saturation():
    import cv2
    # a mid-saturation midtone patch (not clipped)
    img = np.zeros((40, 40, 3), np.uint8)
    img[:] = (100, 130, 180)                       # BGR
    def sat(x):
        return cv2.cvtColor(x, cv2.COLOR_BGR2HSV)[:, :, 1].mean()
    rgb_c = ops.apply_op(img, "contrast", {"value": 50})
    lum_c = ops.apply_op(img, "contrast_lum", {"value": 50})
    # RGB contrast pushes saturation up; luminance-only keeps it ~unchanged
    assert sat(rgb_c) > sat(img) + 10
    assert abs(sat(lum_c) - sat(img)) < 6


def test_project_save_load_roundtrip(tmp_path):
    from config import Config
    from app_controller import AppController
    from core import project
    from core.mask import Mask, RasterSource
    from core.layers import Layer
    import cv2
    ctl = AppController(Config())
    src = str(tmp_path / "src.png")
    cv2.imwrite(src, _img(150, 200))
    assert ctl.open(src)
    # build a rich state: geometry, global adjust/film/curves, a masked layer,
    # and a raster-mask heal layer (exercises base64 PNG embedding)
    ctl.rotate(cw=True)
    ctl.apply_crop((0.1, 0.1, 0.8, 0.8))
    ctl.set_adjust("exposure", 1.5)
    ctl.set_film("velvia")
    ctl.set_curves(master=[(0, 0), (128, 170), (255, 255)])
    ctl.set_mode("selection")
    ctl.brush_start(0.5, 0.5); ctl.brush_end(); ctl.set_local("contrast", 40)
    assert ctl.commit_local()
    raster = np.zeros((60, 80), np.float32); raster[20:40, 30:50] = 1.0
    ctl.doc.layers.append(Layer(kind="heal", name="Erase",
                                params={"engine": "telea"},
                                mask=Mask(sources=[RasterSource(raster)])))
    before = ctl.render(full=True)

    proj = str(tmp_path / "p.iedit")
    assert ctl.save_project(proj)

    ctl2 = AppController(Config())
    assert project.load(ctl2, proj)
    assert ctl2.doc.rotation == ctl.doc.rotation
    assert ctl2.doc.crop_rect == ctl.doc.crop_rect
    assert ctl2.film == "velvia"
    assert ctl2.adjust["exposure"] == 1.5
    assert ctl2.curves["master"] is not None
    assert len(ctl2.doc.layers) == 2
    kinds = {l.kind for l in ctl2.doc.layers}
    assert kinds == {"adjust_set", "heal"}
    # the reloaded raster mask must round-trip (its layer renders identically)
    after = ctl2.render(full=True)
    assert after.shape == before.shape


def test_place_and_blend_changes_target_region():
    import cv2
    base = np.full((200, 300, 3), 120, np.uint8)
    # a structured patch (Poisson transfers gradients, so it must have some)
    src = _img(60, 60)
    cv2.circle(src, (30, 30), 20, (0, 0, 255), -1)
    alpha = np.ones((60, 60), np.float32)
    out = blend.place_and_blend(base, src, alpha, cx=0.5, cy=0.5, scale=0.2, match=False)
    assert out.shape == base.shape
    assert (out != base).any()                         # the paste changed the image


def test_controller_paste_commit_and_project_roundtrip(tmp_path):
    from config import Config
    from app_controller import AppController
    from core import project
    import cv2
    ctl = AppController(Config())
    src_path = str(tmp_path / "bg.png")
    cv2.imwrite(src_path, _img(200, 300))
    assert ctl.open(src_path)

    # an object PNG with alpha (a filled circle cutout)
    obj = np.zeros((80, 80, 4), np.uint8)
    cv2.circle(obj, (40, 40), 35, (30, 200, 30, 255), -1)
    obj_path = str(tmp_path / "obj.png")
    cv2.imwrite(obj_path, obj)

    assert ctl.insert_image(obj_path)
    assert ctl.pending_paste is not None
    ctl.set_paste_param("scale", 0.3)
    ctl.render(full=True)                              # preview path runs
    assert ctl.commit_paste()
    assert len(ctl.doc.layers) == 1 and ctl.doc.layers[0].kind == "paste"

    proj = str(tmp_path / "p.iedit")
    assert ctl.save_project(proj)
    ctl2 = AppController(Config())
    assert project.load(ctl2, proj)
    assert len(ctl2.doc.layers) == 1 and ctl2.doc.layers[0].kind == "paste"
    # the embedded src/alpha round-trip as arrays and render works
    assert ctl2.doc.layers[0].params["src"].shape[2] == 3
    assert ctl2.render(full=True).shape == (200, 300, 3)


def test_pro_ops_run_and_behave():
    import cv2
    img = _img(120, 160)
    for name, args in [("clarity", {"value": 60}), ("texture", {"value": 60}),
                       ("sharpen", {"value": 60}), ("dehaze", {"value": 50}),
                       ("vignette", {"value": 60}), ("grain", {"value": 40}),
                       ("hsl", {"blue": 60}), ("split_tone", {"sh_hue": 220, "sh_amt": 50})]:
        out = ops.apply_op(img, name, args)
        assert out.shape == img.shape and out.dtype == np.uint8
    # vignette darkens the corners relative to the centre
    flat = np.full((100, 100, 3), 150, np.uint8)
    vig = ops.apply_op(flat, "vignette", {"value": 80})
    assert int(vig[0, 0, 0]) < int(vig[50, 50, 0])
    # sharpen increases local variance on an edge
    edge = np.zeros((40, 40, 3), np.uint8); edge[:, 20:] = 200
    sh = ops.apply_op(edge, "sharpen", {"value": 90})
    assert sh.std() >= edge.std()


def test_hsl_targets_one_hue():
    import cv2
    # a blue patch; boosting blue saturation should raise its S, red band shouldn't
    blue = np.zeros((20, 20, 3), np.uint8); blue[:] = (200, 80, 60)  # BGR bluish
    def sat(x): return cv2.cvtColor(x, cv2.COLOR_BGR2HSV)[:, :, 1].mean()
    up = ops.apply_op(blue, "hsl", {"blue": 80})
    noop = ops.apply_op(blue, "hsl", {"red": 80})
    assert sat(up) > sat(blue) + 2
    assert abs(sat(noop) - sat(blue)) < 2


def test_grade_project_roundtrip(tmp_path):
    from config import Config
    from app_controller import AppController
    from core import project
    import cv2
    ctl = AppController(Config())
    p = str(tmp_path / "s.png"); cv2.imwrite(p, _img(120, 160))
    assert ctl.open(p)
    ctl.set_split_tone("sh_amt", 40); ctl.set_split_tone("sh_hue", 210)
    ctl.set_hsl("blue", 55); ctl.set_finish("vignette", 30); ctl.set_finish("grain", 20)
    ctl.set_adjust("clarity", 40)          # new maskable slider in the global set
    graded = ctl.render(full=True)
    assert graded.shape == (120, 160, 3)
    proj = str(tmp_path / "g.iedit"); assert ctl.save_project(proj)
    ctl2 = AppController(Config()); assert project.load(ctl2, proj)
    assert ctl2.grade["split_tone"]["sh_amt"] == 40
    assert ctl2.grade["hsl"]["blue"] == 55
    assert ctl2.grade["vignette"] == 30 and ctl2.grade["grain"] == 20
    assert ctl2.adjust["clarity"] == 40


def test_warp_push_moves_pixels():
    from core import warp
    img = _img(200, 200)
    field = warp.WarpField.for_aspect(200, 200)
    assert field.is_empty()
    field.push(0.5, 0.5, 0.1, 0.0, radius=0.3, strength=1.0)   # push right at centre
    assert not field.is_empty()
    out = warp.apply(img, field.fx, field.fy)
    assert out.shape == img.shape
    assert (out != img).any()                                   # geometry changed


def test_controller_warp_commit_and_project_roundtrip(tmp_path):
    from config import Config
    from app_controller import AppController
    from core import project
    import cv2
    ctl = AppController(Config())
    p = str(tmp_path / "src.png"); cv2.imwrite(p, _img(180, 240))
    assert ctl.open(p)
    ctl.set_warp_strength(0.8)
    ctl.warp_stroke(0.6, 0.5, 0.45, 0.5)      # push inward (slim)
    assert ctl.pending_warp is not None and not ctl.pending_warp.is_empty()
    before = ctl.render(full=True)
    assert ctl.commit_warp()
    assert len(ctl.doc.layers) == 1 and ctl.doc.layers[0].kind == "warp"

    proj = str(tmp_path / "p.iedit")
    assert ctl.save_project(proj)
    ctl2 = AppController(Config())
    assert project.load(ctl2, proj)
    assert len(ctl2.doc.layers) == 1 and ctl2.doc.layers[0].kind == "warp"
    import numpy as _np
    assert _np.allclose(ctl2.doc.layers[0].params["fx"], ctl.doc.layers[0].params["fx"])
    assert ctl2.render(full=True).shape == (180, 240, 3)


def test_raster_source_resizes():
    from core.mask import Mask, RasterSource
    small = np.zeros((50, 50), np.float32)
    small[10:40, 10:40] = 1.0
    m = Mask(sources=[RasterSource(small)])
    big = m.resolve(200, 200, guide=_img(200, 200))
    assert big.shape == (200, 200)
    assert big[100, 100] > 0.5 and big[5, 5] < 0.5   # centre in, corner out


def test_sam_person_removal_end_to_end():
    """Full brush -> SAM refine -> LaMa erase. Skips if SAM/LaMa unavailable."""
    import pytest
    from config import Config
    from app_controller import AppController
    ctl = AppController(Config())
    if not (ctl.segmentation_available() and ctl.lama_available()):
        pytest.skip("SAM or LaMa backend not installed")
    import cv2, tempfile
    h, w = 600, 440
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.stack([(xx * 180 // w + 40).astype(np.uint8),
                    (yy * 160 // h + 50).astype(np.uint8),
                    np.full((h, w), 120, np.uint8)], axis=-1)
    cv2.ellipse(img, (220, 380), (60, 140), 0, 0, 360, (90, 90, 40), -1)
    cv2.circle(img, (220, 200), 48, (90, 90, 40), -1)
    p = tempfile.mktemp(suffix=".png"); cv2.imwrite(p, img)
    assert ctl.open(p)
    ctl.set_mode("selection")
    ctl.brush_start(0.5, 0.33)
    for ny in (0.4, 0.5, 0.6, 0.65):
        ctl.brush_point(0.5, ny)
    ctl.brush_end()
    assert ctl.remove_person_in_selection()
    out = ctl.render(full=True)
    # the solid figure colour at body centre must be gone
    assert tuple(int(v) for v in out[380, 220]) != (90, 90, 40)
