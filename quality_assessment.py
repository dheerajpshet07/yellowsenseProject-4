"""
quality_assessment.py

Core quality checks for contactless (phone camera) fingerprint captures.
5 metric functions, a composite scorer, and quality_gate() which ties it
all together. Used by both test_quality.py and quality_app.py.
"""

from __future__ import annotations

import time
from typing import Optional

import cv2
import numpy as np

DEFAULT_THRESHOLDS = {
    "blur_min": 10.0,
    "brightness_dark": 50.0,
    "brightness_bright": 210.0,
    "glare_fraction_max": 0.05,
    "roi_fraction_min": 0.15,
    "ridge_min": 15.0,
}

DEFAULT_WEIGHTS = {
    "blur": 0.25,
    "brightness": 0.15,
    "glare": 0.15,
    "roi": 0.15,
    "ridge": 0.30,
}

# longest side we ever process at. phone photos come in at 12MP+ and none
# of these checks need that much detail, downscaling first keeps us inside
# the 300ms budget and also makes the blur score resolution-independent
MAX_PROCESSING_DIM = 800


def _to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _resize_for_processing(img: np.ndarray, max_dim: int = MAX_PROCESSING_DIM) -> np.ndarray:
    h, w = img.shape[:2]
    longest = max(h, w)
    if longest <= max_dim:
        return img
    scale = max_dim / longest
    return cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


def _segment_finger_mask(img: np.ndarray) -> np.ndarray:
    """
    Rough finger vs background split, used by the ROI and ridge checks.
    Otsu picks a good threshold automatically but has no idea which side
    of the split is actually the finger, so we just check whether the
    center of the frame ended up foreground and flip if not (capture
    instructions tell people to center the finger, so this holds up ok
    in practice - see notes on where this fell apart in testing).
    """
    small = _resize_for_processing(img)
    gray = _to_gray(small)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    h, w = mask.shape
    cy, cx = h // 2, w // 2
    center_patch = mask[max(cy - 5, 0):cy + 5, max(cx - 5, 0):cx + 5]
    if center_patch.size and np.mean(center_patch) < 127:
        mask = cv2.bitwise_not(mask)

    # clean up speckle noise then just keep the biggest blob
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        largest = max(contours, key=cv2.contourArea)
        clean_mask = np.zeros_like(mask)
        cv2.drawContours(clean_mask, [largest], -1, 255, thickness=cv2.FILLED)
        mask = clean_mask

    return mask


def _clip01(v: float) -> float:
    return float(min(max(v, 0.0), 1.0))


# ---- metric 1: blur ----

def check_blur(image_bgr: np.ndarray, threshold: float = DEFAULT_THRESHOLDS["blur_min"]) -> dict:
    # laplacian variance - sharp edges give a wide spread of 2nd derivative
    # values, blurry/flat regions don't. classic cheap blur detector.
    small = _resize_for_processing(image_bgr)
    gray = _to_gray(small)
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return {"blur_score": blur_score, "is_blurry": blur_score < threshold}


# ---- metric 2: brightness ----

def check_brightness(
    image_bgr: np.ndarray,
    dark_threshold: float = DEFAULT_THRESHOLDS["brightness_dark"],
    bright_threshold: float = DEFAULT_THRESHOLDS["brightness_bright"],
) -> dict:
    small = _resize_for_processing(image_bgr)
    gray = _to_gray(small)
    brightness = float(np.mean(gray))
    return {
        "brightness": brightness,
        "too_dark": brightness < dark_threshold,
        "too_bright": brightness > bright_threshold,
    }


# ---- metric 3: glare ----

def check_glare(
    image_bgr: np.ndarray,
    pixel_threshold: int = 240,
    fraction_threshold: float = DEFAULT_THRESHOLDS["glare_fraction_max"],
) -> dict:
    small = _resize_for_processing(image_bgr)
    gray = _to_gray(small)
    glare_fraction = float(np.count_nonzero(gray > pixel_threshold) / gray.size)
    return {"has_glare": glare_fraction > fraction_threshold, "glare_fraction": glare_fraction}


# ---- metric 4: roi completeness ----

def check_roi_completeness(
    image_bgr: np.ndarray,
    fraction_threshold: float = DEFAULT_THRESHOLDS["roi_fraction_min"],
    mask: Optional[np.ndarray] = None,
) -> dict:
    # mask param just lets quality_gate() pass in a mask it already
    # computed instead of segmenting twice, still works standalone
    if mask is None:
        mask = _segment_finger_mask(image_bgr)
    roi_fraction = float(np.count_nonzero(mask) / mask.size)
    return {"roi_fraction": roi_fraction, "roi_complete": roi_fraction >= fraction_threshold}


# ---- metric 5: ridge clarity ----

def check_ridge_clarity(
    image_bgr: np.ndarray,
    threshold: float = DEFAULT_THRESHOLDS["ridge_min"],
    mask: Optional[np.ndarray] = None,
) -> dict:
    # gabor filter bank tuned to ridge-like periodic texture. ridges run in
    # different directions across the finger so we try 4 orientations and
    # keep whichever responded strongest at each pixel, then look at how
    # much that response varies inside the finger region only - flat worn
    # skin gives a pretty uniform response, real ridges swing high/low
    small = _resize_for_processing(image_bgr)
    gray = _to_gray(small)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    gray_f = gray.astype(np.float32) / 255.0

    if mask is None:
        mask = _segment_finger_mask(image_bgr)
    if mask.shape != gray.shape:
        mask = cv2.resize(mask, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_NEAREST)

    responses = []
    for theta_deg in (0, 45, 90, 135):
        kernel = cv2.getGaborKernel(
            ksize=(21, 21), sigma=4.0, theta=np.deg2rad(theta_deg),
            lambd=8.0, gamma=0.5, psi=0, ktype=cv2.CV_32F,
        )
        responses.append(cv2.filter2D(gray_f, cv2.CV_32F, kernel))

    ridge_response = np.max(np.stack(responses, axis=0), axis=0)
    roi_pixels = ridge_response[mask > 0]

    if roi_pixels.size == 0:
        ridge_score = 0.0
    else:
        ridge_score = float(np.var(roi_pixels) * 1000)  # just scaling to a saner range of numbers

    return {"ridge_score": ridge_score, "ridges_clear": ridge_score >= threshold}


# ---- composite score ----

def _normalize_metrics(metrics: dict, thresholds: dict) -> dict:
    # each metric gets mapped to a 0-1 "goodness" value before combining.
    # reject threshold = 0, some more comfortable value = 1, linear between.
    # brightness is the odd one out since it's a sweet spot, not a ramp.
    blur_n = _clip01(
        (metrics["blur"]["blur_score"] - thresholds["blur_min"]) / (150.0 - thresholds["blur_min"])
    )

    center = (thresholds["brightness_dark"] + thresholds["brightness_bright"]) / 2
    half_range = (thresholds["brightness_bright"] - thresholds["brightness_dark"]) / 2
    brightness_n = _clip01(1 - abs(metrics["brightness"]["brightness"] - center) / half_range)

    glare_n = _clip01(1 - metrics["glare"]["glare_fraction"] / thresholds["glare_fraction_max"])

    roi_n = _clip01(
        (metrics["roi"]["roi_fraction"] - thresholds["roi_fraction_min"]) / (0.5 - thresholds["roi_fraction_min"])
    )

    ridge_n = _clip01(
        (metrics["ridge"]["ridge_score"] - thresholds["ridge_min"]) / (thresholds["ridge_min"] * 2)
    )

    return {"blur": blur_n, "brightness": brightness_n, "glare": glare_n, "roi": roi_n, "ridge": ridge_n}


def compute_composite_score(metrics: dict, thresholds: dict, weights: dict = None) -> float:
    weights = weights or DEFAULT_WEIGHTS
    normalized = _normalize_metrics(metrics, thresholds)
    score = sum(weights[k] * normalized[k] for k in weights)
    return round(score * 100, 1)


def _build_guidance(metrics: dict) -> str:
    issues = []
    if metrics["blur"]["is_blurry"]:
        issues.append("Too blurry, hold your hand steady and retry")
    if metrics["brightness"]["too_dark"]:
        issues.append("Too dark, move to better lighting or remove any flash cover")
    if metrics["brightness"]["too_bright"]:
        issues.append("Too bright, reduce lighting or move away from direct flash")
    if metrics["glare"]["has_glare"]:
        issues.append("Glare detected, avoid direct light/flash reflecting off the finger")
    if not metrics["roi"]["roi_complete"]:
        issues.append("Finger too small in frame, move closer and fill more of the frame")
    if not metrics["ridge"]["ridges_clear"]:
        issues.append("Ridge pattern unclear, clean/dry the finger and refocus before retrying")

    if not issues:
        return "Good capture, ready for processing"
    return " | ".join(issues)


def quality_gate(
    image_path: str,
    thresholds: dict = None,
    weights: dict = None,
    pass_score: float = 60.0,
) -> dict:
    """Run all 5 checks on an image file, return pass/fail + guidance."""
    thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    weights = weights or DEFAULT_WEIGHTS

    image_bgr = cv2.imread(image_path)
    if image_bgr is None:
        raise FileNotFoundError(f"Could not read image: {image_path}")

    return _quality_gate_from_array(image_bgr, thresholds, weights, pass_score)


def quality_gate_from_array(
    image_bgr: np.ndarray,
    thresholds: dict = None,
    weights: dict = None,
    pass_score: float = 60.0,
) -> dict:
    """Same thing but for an already-decoded image (this is what quality_app.py calls)."""
    thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    weights = weights or DEFAULT_WEIGHTS
    return _quality_gate_from_array(image_bgr, thresholds, weights, pass_score)


def _quality_gate_from_array(image_bgr: np.ndarray, thresholds: dict, weights: dict, pass_score: float) -> dict:
    # resize + segment once here and hand it down, otherwise roi and ridge
    # would each redo the same otsu/morphology work
    small = _resize_for_processing(image_bgr)
    mask = _segment_finger_mask(small)

    blur = check_blur(small, threshold=thresholds["blur_min"])
    brightness = check_brightness(
        small, dark_threshold=thresholds["brightness_dark"], bright_threshold=thresholds["brightness_bright"]
    )
    glare = check_glare(small, fraction_threshold=thresholds["glare_fraction_max"])
    roi = check_roi_completeness(small, fraction_threshold=thresholds["roi_fraction_min"], mask=mask)
    ridge = check_ridge_clarity(small, threshold=thresholds["ridge_min"], mask=mask)

    metrics = {"blur": blur, "brightness": brightness, "glare": glare, "roi": roi, "ridge": ridge}
    composite_score = compute_composite_score(metrics, thresholds, weights)

    return {
        "passed": composite_score >= pass_score,
        "composite_score": composite_score,
        "blur": blur,
        "brightness": brightness,
        "glare": glare,
        "roi": roi,
        "ridge": ridge,
        "guidance": _build_guidance(metrics),
    }


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python quality_assessment.py <image_path>")
        sys.exit(1)

    t0 = time.perf_counter()
    result = quality_gate(sys.argv[1])
    elapsed_ms = (time.perf_counter() - t0) * 1000

    print(json.dumps(result, indent=2))
    print(f"\nElapsed: {elapsed_ms:.1f} ms")
