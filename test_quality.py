"""
test_quality.py

Runs quality_gate() over the 20 self-captured test images and prints a
results table so you can check each defect category actually got flagged
correctly.

Expects images under test_images/<category>/*, category is one of:
good, blurry, dark, glare (5 images each, per the assignment brief).
"""

import time
from pathlib import Path

from quality_assessment import quality_gate

TEST_IMAGES_DIR = Path(__file__).parent / "test_images"
CATEGORIES = ["good", "blurry", "dark", "glare"]
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}


def find_test_images() -> list[tuple[str, Path]]:
    found = []
    for category in CATEGORIES:
        folder = TEST_IMAGES_DIR / category
        if not folder.exists():
            continue
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() in IMAGE_EXTENSIONS:
                found.append((category, path))
    return found


def main() -> None:
    images = find_test_images()
    if not images:
        print(f"No test images found under {TEST_IMAGES_DIR}.")
        print("Add 5 images each into test_images/good, blurry, dark, glare (see Part D).")
        return

    header = (
        f"{'category':<9} {'file':<22} {'score':>7} {'pass':>6} "
        f"{'blur':>6} {'dark':>6} {'bright':>7} {'glare':>7} {'roi':>6} {'ridge':>7} {'ms':>7}"
    )
    print(header)
    print("-" * len(header))

    rows = []
    for category, path in images:
        t0 = time.perf_counter()
        result = quality_gate(str(path))
        elapsed_ms = (time.perf_counter() - t0) * 1000

        row = (
            f"{category:<9} {path.name:<22} {result['composite_score']:>7.1f} "
            f"{'PASS' if result['passed'] else 'FAIL':>6} "
            f"{'BLUR' if result['blur']['is_blurry'] else 'ok':>6} "
            f"{'DARK' if result['brightness']['too_dark'] else 'ok':>6} "
            f"{'BRIGHT' if result['brightness']['too_bright'] else 'ok':>7} "
            f"{'GLARE' if result['glare']['has_glare'] else 'ok':>7} "
            f"{'ok' if result['roi']['roi_complete'] else 'SMALL':>6} "
            f"{'ok' if result['ridge']['ridges_clear'] else 'UNCLR':>7} "
            f"{elapsed_ms:>7.1f}"
        )
        print(row)
        rows.append((category, path.name, result, elapsed_ms))

    print("\nSummary")
    print("-" * len(header))
    for category in CATEGORIES:
        cat_rows = [r for r in rows if r[0] == category]
        if not cat_rows:
            continue
        avg_ms = sum(r[3] for r in cat_rows) / len(cat_rows)
        n_pass = sum(1 for r in cat_rows if r[2]["passed"])
        print(f"{category:<9} {len(cat_rows)} images, {n_pass} passed, avg {avg_ms:.1f} ms")


if __name__ == "__main__":
    main()
