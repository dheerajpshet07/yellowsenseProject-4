# Assignment 4 — Report Questions (draft)

> Convert this to `report.pdf` before submitting. Fill in the `[TODO]`
> spots after you've shot your 20 Part D photos and run `test_quality.py`
> on them — those need your real numbers, not placeholders.

## 1. What threshold did you set for blur? How did you decide?

I used `blur_score < 10.0` (Laplacian variance) as the reject threshold,
per the assignment's suggested starting point. To validate it, I ran
`check_blur()` over my 20 Part D images (5 good, 5 deliberately blurred by
moving my hand during capture) via `test_quality.py` and checked whether the
threshold correctly separated the two groups.

[TODO: paste your actual `test_quality.py` output table here, or summarize
it — e.g. "good captures scored between X and Y, blurry captures scored
between A and B, so 10.0 [did / did not] cleanly separate them, and I
adjusted to __ because ___."]

One thing I had to control for during calibration: Laplacian variance is
resolution-dependent — the same photo content scores differently at
different resolutions — so I standardize every image to a fixed 800px
longest-side before computing the metric (`_resize_for_processing` in
`quality_assessment.py`). Without that, a threshold calibrated on one
camera's output resolution wouldn't transfer to another phone.

## 2. Which metric was hardest to implement correctly? What went wrong first?

ROI completeness / finger segmentation (`_segment_finger_mask`) was the
hardest, and ridge clarity depends directly on it (the Gabor variance is
measured *inside* the segmented region), so getting ROI wrong silently broke
ridge clarity too.

What went wrong first: Otsu's method finds a good binary split of the image
histogram, but it has no idea *which side of the split is the finger* versus
the background — it just returns two classes. My first version assumed the
foreground was always the smaller-area class (finger usually looks small
against wall/desk background), which broke immediately on close-up captures
where the finger fills most of the frame — those got inverted, segmenting
the *background* as "the finger."

The fix: since the capture instructions already assume a roughly centered
finger, I instead check whether the small patch at the image's exact center
falls into the foreground or background class after thresholding, and invert
if the center came out as background. That's a cheap, reasonable prior given
how the images are captured, but it's still a heuristic — it would break on
an off-center or multi-object frame. A production system would likely want
a small trained segmentation model instead.

## 3. What is NFIQ2? Why is a score designed for contact scanners not reliable for phone camera images?

NFIQ2 (NIST Fingerprint Image Quality 2) is NIST's standard 0–100 quality
score for fingerprint images, trained and validated on images from
**contact** fingerprint scanners at a fixed, calibrated 500 DPI — the finger
is pressed directly onto a sensor under controlled, consistent conditions
(fixed distance, fixed lighting, fixed contact pressure, no perspective
distortion).

A phone camera contactless capture violates nearly every one of those
assumptions:
- **No fixed distance/DPI** — the effective resolution of the ridge pattern
  depends entirely on how far the finger is from the lens, which varies
  every capture. NFIQ2's ridge-frequency-based features assume a known,
  stable scale.
- **Perspective distortion** — a finger photographed at an angle has
  non-uniform ridge spacing across the frame, unlike a flat scanner platen.
- **Uncontrolled, variable lighting** — shadows, glare, and ambient color
  cast don't exist in a scanner capture; NFIQ2 wasn't trained to discount
  them.
- **No contact/pressure signal** — some contact-scanner quality issues
  (e.g. dry-finger ridge dropout under pressure) are specific to the sensor
  physics and don't apply to a camera photo, while camera-specific issues
  (motion blur, focus, framing) aren't things NFIQ2 was ever trained to
  detect.

In short: NFIQ2 answers "is this a good *contact scan*?", and a phone photo
isn't a scan at all — it's a different imaging modality with a different
failure mode distribution, which is exactly why this assignment builds a
custom, camera-specific quality pipeline instead of reusing NFIQ2.

## 4. Name 3 other quality problems you'd add checks for in a real deployment

1. **Perspective / angle distortion** — the finger photographed at a steep
   angle rather than flat-on to the camera produces non-uniform ridge
   spacing across the image, which can pass blur/brightness/ROI checks
   while still being unusable for accurate minutiae extraction. Could be
   approximated by checking aspect ratio / contour shape of the segmented
   finger against an expected fingertip silhouette.
2. **Wrong capture distance (too far / too close)** — ROI completeness
   alone doesn't catch this: a finger that's too far away can still be
   "complete" in frame but have too few effective pixels per ridge to
   resolve minutiae, while one that's too close might clip the fingertip
   out of frame entirely. Would need an explicit pixel-per-ridge estimate
   (e.g. via ridge frequency from the Gabor response) rather than relying
   on ROI fraction as a proxy.
3. **Wet or moist finger** — changes surface reflectance, often producing
   either false glare-like highlights or a smeared, low-contrast ridge
   pattern that isn't motion blur but looks similar to it. A dedicated
   check might look at localized specular highlight patterns distinct from
   the broad "glare_fraction" check, or texture uniformity that doesn't fit
   either the "sharp ridges" or "generic blur" model well.

(Other candidates worth mentioning if asked for more: dirty/smudged camera
lens, partial finger occlusion by a nail or other finger, inconsistent
directional lighting causing shadow bands across ridges distinct from
overall brightness, non-finger objects confusing ROI segmentation.)

## 5. If a rural agricultural worker's fingerprints are naturally worn and give consistently poor ridge clarity scores, what should the system do differently for them?

The system should **not** just lower the ridge-clarity threshold globally —
that would let genuinely bad captures through for everyone, defeating the
point of the check. The real issue here isn't capture quality, it's that the
person's ridges are permanently, physically worn (common with manual
agricultural labor), so no amount of "hold steady and retake" guidance will
ever fix it — repeatedly telling them to retry is a usability and equity
failure, not a helpful quality gate.

What I'd do instead:
- **Detect the pattern, not just the single capture.** If a user's ridge
  clarity score is consistently borderline across multiple honest retry
  attempts (while blur/brightness/glare/ROI all pass cleanly), that's a
  signal this is a *person* characteristic, not a *capture* problem, and
  the system should stop asking them to retake and route them elsewhere.
- **Fall back to a different acceptance path**, not just a lower bar: e.g.
  accept based on multi-finger fusion (combine several fingers' signal
  instead of gating each individually), flag for assisted/manual enrollment
  review, or fall back to an alternate modality entirely (iris, face) where
  available — rather than silently accepting a lower-quality fingerprint
  match threshold just for this group, which would be a fairness problem in
  the opposite direction (weaker security guarantee for one population).
- **Track this at a product level**, not just a code level — if a
  meaningful fraction of a target population (e.g. manual laborers) hits
  this consistently, that's a signal the enrollment product needs a
  designed-for-them path, not a per-user threshold hack.
