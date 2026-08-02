# Changelog — Assignment 4 (Fingerprint Quality Assessment & Scoring Pipeline)

Chronological record of everything built, every change made, and — most
importantly — **why**. Keep this updated as the project evolves so you
always have a clear story of how it got to its current state.

> This folder is currently tracked in git (not excluded). If you'd rather
> keep it private like `private_reference/`, just say so and it'll be added
> to `.gitignore`.

---

## 2026-08-02 — Session 1: Initial build

### What was created
- `quality_assessment.py` — all 5 Part A metric functions, Part B composite
  scoring, Part C `quality_gate()` / `quality_gate_from_array()`.
- `quality_app.py` — Part E Streamlit interface.
- `test_quality.py` — Part D batch test runner.
- `requirements.txt`, `README.md`, `.gitignore`.
- Folder scaffolding: `test_images/{good,blurry,dark,glare}/`, `screenshots/`.
- `private_reference/PROJECT_NOTES.md` — interview-prep deep dive (gitignored).
- `report_answers.md` — draft answers to the 5 report questions.

### Why each design decision was made

**Metric functions kept independently callable.** Each function's public
signature is exactly what the spec shows (`check_blur(image_bgr)`, etc.),
with all thresholds as optional keyword args defaulting to the spec's
suggested values. This makes each function testable/usable standalone *and*
lets `quality_gate()` pass in shared work (see next point) without changing
the public contract.

**Shared ROI mask, computed once.** `check_roi_completeness` and
`check_ridge_clarity` both need to know "which pixels are the finger."
Rather than segmenting the image twice, `_segment_finger_mask()` is a
private helper that `quality_gate()` calls once and passes into both
functions via an optional `mask=` parameter. Reason: segmentation
(Otsu threshold + morphology + contour finding) is the most expensive
non-Gabor step in the pipeline — doing it twice would be pure waste.

**Otsu thresholding + "trust the center" heuristic for finger segmentation.**
Otsu automatically finds a good foreground/background split per-image (no
manual brightness cutoff, since lighting varies a lot between phone
captures), but it doesn't know *which* side is the finger. Since the Part D
capture instructions assume a roughly centered finger, checking whether the
image's center pixels land in the foreground or background class (and
inverting if needed) is a cheap, defensible prior. **This was the hardest
part of the whole assignment to get right** — see `private_reference/PROJECT_NOTES.md`
§4 for the full story of what broke first.

**Gabor filter bank (4 orientations) for ridge clarity, measured inside the
ROI only.** Fingerprint ridges are a locally-oriented periodic texture — a
Gabor filter is the standard tool for detecting exactly that pattern
(it's the same building block used in real minutiae-extraction pipelines).
Four orientations (0°/45°/90°/135°) are probed and the max response per
pixel is kept, since ridge direction varies across the finger. Restricting
the variance calculation to the segmented ROI (rather than the whole frame)
matters — without it, background texture dilutes the signal and you end up
scoring the desk, not the finger.

**Composite score uses continuous normalization, not boolean averaging.**
Each raw metric is linearly mapped to a 0-1 "goodness" value anchored at its
reject threshold, then combined as a weighted sum (blur 0.25, brightness
0.15, glare 0.15, roi 0.15, ridge 0.30 — weights sum to 1.0). Reason: a
hard pass/fail per metric throws away information right at the threshold
boundary (blur_score=9.9 and blur_score=2.0 both just say "blurry," but
they're very different). Ridge and blur got the highest weights because
they most directly determine whether minutiae extraction can succeed
downstream.

**`_resize_for_processing()` — standardize every image to 800px longest side
before any per-pixel math.** Two reasons: (1) performance — phone photos
can be 12MP+, and none of these metrics need full resolution to make a
pass/fail decision; (2) correctness — Laplacian variance (the blur metric)
is resolution-dependent, so without a fixed working resolution, a threshold
calibrated on one camera's output wouldn't transfer to another.

---

## 2026-08-02 — Session 1 (continued): Performance bug found and fixed

### What happened
First working version ran `check_blur()` and `check_brightness()` directly
on the full-resolution input image (only `check_ridge_clarity` was already
downscaling, since it needed the mask anyway). Smoke-testing on a synthetic
4032×3024 image (typical phone photo resolution) measured **510-560ms total
— nearly double the 300ms budget.**

### Root cause (profiled, not guessed)
```
blur         239ms   <- full-resolution Laplacian
brightness    50ms   <- full-resolution mean
glare         24ms
segment       39ms
roi          0.1ms
ridge        129ms   (already downscaled)
```

### The fix
Added the `_resize_for_processing()` call inside `check_blur`,
`check_brightness`, and `check_glare` too, and made `_quality_gate_from_array()`
resize **once** up front and pass the small image into every check — each
function's internal resize call becomes a free no-op once the image is
already small, so running the full pipeline doesn't pay for 5 separate
resizes.

### Result after fix
```
blur          11ms
brightness   1.7ms
glare        0.9ms
segment        8ms
roi         0.08ms
ridge         89ms
```
Full pipeline (post-decode): **~146ms average** over 5 runs on a stress-test
image — well inside the 300ms budget, with headroom to spare.

### Side discovery worth remembering
Because Laplacian variance scales with the intensity range of the image, a
synthetically *darkened* (not blurred) test image was also getting flagged
as blurry — variance drops roughly with the square of the intensity-range
scale factor. This isn't a bug so much as a real, defensible observation:
blur and brightness aren't fully independent signals. A capture that's both
very dark and blurry-scored genuinely does have less recoverable ridge
detail. Worth mentioning if asked "are your 5 metrics independent?"

---

## 2026-08-02 — Session 2: Full requirement audit + robustness verification

### What was checked
1. **Requirement-by-requirement diff** of `quality_assessment.py` against
   every Part A/B/C spec line (exact function signatures, exact return dict
   keys, exact threshold values/directions). All matched.
2. **Stable performance re-measurement** — 5 repeated runs of
   `quality_gate_from_array()` on a 4032×3024 stress-test image:
   `[172.6, 145.3, 137.7, 142.3, 133.8]` ms, average **146.3ms**. Confirms
   the earlier fix holds up under repeated measurement, not just a single
   lucky run.
3. **Edge-case testing** — ran the full pipeline against:
   - a grayscale (2D, no color channel) input
   - a 20×20 tiny image
   - an all-black image
   - an all-white image
   - a nonexistent file path

   None of these crashed the pipeline; each produced a sensible low
   composite score (or a clean `FileNotFoundError` for the missing file).
   This matters because real phone captures will sometimes be genuinely bad
   in ways beyond the 4 designed defect categories, and the gate needs to
   fail gracefully, not throw.
4. **Live Streamlit smoke test** — launched `quality_app.py` headlessly
   (`streamlit run ... --server.headless true`) and confirmed it serves
   HTTP 200 with no runtime errors in the log. This is a stronger check
   than `py_compile`, which only catches syntax errors, not import-time or
   Streamlit-API-version issues (e.g., a removed/renamed parameter would
   pass `py_compile` but crash on actual launch).

### What's still outstanding (requires your action, not more code)
- **Part D: 20 real phone photos** — `test_images/{good,blurry,dark,glare}/`
  are currently empty. Nothing in the code can substitute for this; the
  assignment explicitly wants real captures.
- **4 screenshots** — depends on Part D photos existing first, then running
  `streamlit run quality_app.py` and uploading one image per defect category.
- **report.pdf** — `report_answers.md` is drafted (all 5 questions answered),
  but Q1 has a `[TODO]` marker that needs your actual
  `test_quality.py` output numbers once Part D images exist. Convert to PDF
  last, after that's filled in.

### No code changes were made in this session
This was a verification pass only — everything tested against spec on the
first check, aside from the performance issue already fixed in Session 1.
