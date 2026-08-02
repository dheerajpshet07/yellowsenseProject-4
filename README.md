# Assignment 4 — Fingerprint Quality Assessment & Scoring Pipeline

Multi-metric image quality gate for contactless (phone-camera) fingerprint
captures. Maps to FP-03 (Quality Control) in the YellowSense SDK.

## Setup

```bash
pip install -r requirements.txt
```

## Files

- `quality_assessment.py` — the 5 metric functions, composite score, and `quality_gate()`
- `quality_app.py` — Streamlit UI (`streamlit run quality_app.py`)
- `test_quality.py` — batch runner over `test_images/` (`python test_quality.py`)
- `test_images/{good,blurry,dark,glare}/` — your 20 self-captured phone photos (5 each)
- `screenshots/` — the 4 required UI screenshots (one per defect type)
- `report_answers.md` — draft answers to the 5 report questions (convert to `report.pdf` before submitting)

## Quick check on a single image

```bash
python quality_assessment.py path/to/image.jpg
```

## Test images (Part D)

Take 20 photos of your own fingertip with your phone:

- 5 good (clear, well-lit, steady) → `test_images/good/`
- 5 blurry (move hand slightly while capturing) → `test_images/blurry/`
- 5 too dark (dark room or covered flash) → `test_images/dark/`
- 5 glare (bright lamp/torch pointed at finger) → `test_images/glare/`

Then run:

```bash
python test_quality.py
```
