# Getting a Professional Look — a Recipe

A short, repeatable workflow for turning a snapshot into a professional-looking image
**using image-editor's tools**. It follows the order the pros use (see the research in
[analysis.md §11](analysis.md)): fix the basics first, then tone, then colour, then
local work, then finish. Small, deliberate moves beat big ones.

> Golden rule: **edit in order, and less is more.** If a slider looks obvious, back it
> off. Everything here is non-destructive — undo freely, and **Save Project** (`.iedit`)
> before a big session so you can always come back.

---

## The 7 steps

### 1 · Get the basics right (Adjust tab · Whole image)
- **White balance** — set **Temperature** (warmer/cooler) and **Tint** until whites look
  neutral and skin looks natural. This one step fixes most "amateur" colour.
- **Exposure** — make the overall brightness correct.
- **Highlights** down / **Shadows** up — recover blown skies and open dark areas.

### 2 · Shape the tone (contrast)
- Add a gentle **Contrast**, or better, an **S-curve** in the **Curves** tab (lift the
  top, drop the bottom) — this is what gives an image "pop" without looking harsh.

### 3 · Add dimension (Adjust tab)
- **Clarity** ≈ +15 to +25 for midtone punch. **Texture** a touch for fine detail.
- **Dehaze** only if the shot looks flat or hazy.
- Leave **Sharpen** for the very end (step 7).

### 4 · Grade the colour (Color tab)
- **Split-tone**: cool shadows (hue ≈ 210°) + warm highlights (hue ≈ 45°), amounts
  around **15–30**. This is the single biggest "cinematic" lever.
- **HSL**: nudge **Blue** up for skies, ease **Orange/Red** down if skin is too warm,
  lift **Green** for foliage. Keep moves small.

### 5 · Make the subject pop (Selection only)
- Switch **Adjust → Selection only**, brush over your subject, and nudge **Exposure**
  and **Clarity** up a little. Keep **Border smoothing** high so it blends. Toggle
  **Show selection outline** off to judge the result, then **Apply to selection**.
- This is digital **dodge & burn** — brightening what matters, and (with a second
  selection and lower exposure) darkening what doesn't.

### 6 · Retouch (optional)
- **Erase** distractions (🩹) or a whole person (🧍). Heal small blemishes.
- **Reshape** (🫳) for subtle body/object tweaks. **Paste** (📎) to add an element.

### 7 · Finish
- **Vignette** ≈ +15 to +25 to gently draw the eye to the centre.
- **Sharpen** last, modestly. Optionally a little **Film grain** for a filmic feel.
- **Save As** at full resolution (JPEG at high quality, or PNG/TIFF for lossless).

---

## Quick presets to try

| Look | Do this |
|------|---------|
| **Clean & natural** | WB neutral · gentle S-curve · Clarity +15 · Vignette +12 · Sharpen +30 |
| **Warm portrait** | WB slightly warm · Highlights −20 · Split-tone warm highlights (45°, 20) · HSL orange −10 · Clarity +10 |
| **Moody cinematic** | Contrast up · Split-tone cool shadows (210°, 25) + warm highlights (45°, 20) · Vignette +25 · Saturation −10 |
| **Punchy landscape** | Dehaze +20 · Clarity +25 · HSL blue +30 / green +15 · Vignette +15 |
| **Black & white** | Film look → *Monochrome* (or *Acros*) · Contrast up · Clarity +20 · Grain +15 |

---

## Common mistakes to avoid

- **Over-saturation** — prefer **Vibrance** over Saturation; grade with HSL, not the
  master saturation slider.
- **Halos** from too much Clarity/Sharpen — back them off until edges look clean.
- **Obvious local edits** — keep **Border smoothing** up and effects subtle; use
  *Show selection outline* to check the blend.
- **Editing a small JPEG** — start from the largest, highest-quality file you have.
  For the very best quality, do white-balance/exposure on the **RAW** in a free RAW
  processor (Darktable / RawTherapee), export a high-quality file, then finish here.

---

## Where image-editor fits in a pro pipeline

image-editor is strongest at **tone, colour grading, local work, retouch, reshape, and
finishing**. For the two steps it doesn't do yet — **RAW development** and **AI
denoise / upscaling** — pair it with a free RAW tool for now; those are on the roadmap
(see [plan.md](plan.md) Phase 9, the backend tier).
