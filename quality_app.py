"""
quality_app.py

Streamlit front end for quality_gate(). Upload a fingerprint photo, see
each metric pass/fail plus the overall composite score.

Run with: streamlit run quality_app.py
"""

import time

import cv2
import numpy as np
import streamlit as st

from quality_assessment import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS, quality_gate_from_array

st.set_page_config(page_title="Fingerprint Quality Gate", page_icon="🔍", layout="centered")

# sidebar - all thresholds adjustable, nothing hardcoded
st.sidebar.header("Quality thresholds")

blur_min = st.sidebar.slider("Blur - min Laplacian variance", 0.0, 200.0, DEFAULT_THRESHOLDS["blur_min"], 1.0)
brightness_dark = st.sidebar.slider("Brightness - dark cutoff", 0, 255, int(DEFAULT_THRESHOLDS["brightness_dark"]))
brightness_bright = st.sidebar.slider(
    "Brightness - bright cutoff", 0, 255, int(DEFAULT_THRESHOLDS["brightness_bright"])
)
glare_fraction_max = st.sidebar.slider(
    "Glare - max overexposed fraction", 0.0, 0.5, DEFAULT_THRESHOLDS["glare_fraction_max"], 0.01
)
roi_fraction_min = st.sidebar.slider(
    "ROI - min finger fraction of frame", 0.0, 1.0, DEFAULT_THRESHOLDS["roi_fraction_min"], 0.01
)
ridge_min = st.sidebar.slider("Ridge clarity - min score", 0.0, 100.0, DEFAULT_THRESHOLDS["ridge_min"], 1.0)

st.sidebar.divider()
pass_score = st.sidebar.slider("Composite pass score", 0, 100, 60)

thresholds = {
    "blur_min": blur_min,
    "brightness_dark": brightness_dark,
    "brightness_bright": brightness_bright,
    "glare_fraction_max": glare_fraction_max,
    "roi_fraction_min": roi_fraction_min,
    "ridge_min": ridge_min,
}

st.title("🔍 Fingerprint Quality Gate")
st.caption("FP-03 quality control for contactless phone camera fingerprint captures")

uploaded_file = st.file_uploader("Upload a fingerprint image", type=["jpg", "jpeg", "png", "bmp"])

if uploaded_file is None:
    st.info("Upload an image to run the quality gate.")
else:
    file_bytes = np.frombuffer(uploaded_file.read(), dtype=np.uint8)
    image_bgr = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)

    if image_bgr is None:
        st.error("Could not decode this image. Please upload a valid JPG/PNG.")
    else:
        st.image(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB), caption="Uploaded capture", use_container_width=True)

        t0 = time.perf_counter()
        result = quality_gate_from_array(image_bgr, thresholds=thresholds, weights=DEFAULT_WEIGHTS, pass_score=pass_score)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        score = result["composite_score"]
        color = "green" if result["passed"] else "red"
        st.markdown(f"<h1 style='color:{color};'>{score:.1f} / 100</h1>", unsafe_allow_html=True)

        st.success(result["guidance"]) if result["passed"] else st.error(result["guidance"])

        st.subheader("Metric breakdown")

        def badge(ok: bool) -> str:
            return "✅ PASS" if ok else "❌ FAIL"

        col1, col2 = st.columns(2)

        with col1:
            st.metric("Blur (Laplacian var)", f"{result['blur']['blur_score']:.1f}")
            st.write(badge(not result["blur"]["is_blurry"]))

            st.metric("Brightness (mean pixel)", f"{result['brightness']['brightness']:.1f}")
            st.write(badge(not result["brightness"]["too_dark"] and not result["brightness"]["too_bright"]))

            st.metric("Glare fraction", f"{result['glare']['glare_fraction']:.3f}")
            st.write(badge(not result["glare"]["has_glare"]))

        with col2:
            st.metric("ROI fraction", f"{result['roi']['roi_fraction']:.3f}")
            st.write(badge(result["roi"]["roi_complete"]))

            st.metric("Ridge clarity score", f"{result['ridge']['ridge_score']:.1f}")
            st.write(badge(result["ridge"]["ridges_clear"]))

        st.divider()
        st.caption(f"Processed in {elapsed_ms:.1f} ms (budget: 300 ms)")
