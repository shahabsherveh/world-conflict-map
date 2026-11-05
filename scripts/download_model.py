"""Pre-download the zero-shot model (run once; requires network).

Run from anywhere:
    python scripts/download_model.py

Downloads `cross-encoder/nli-deberta-v3-small` (~130 MB) into the HuggingFace
cache. After this completes, the zero-shot filter in app/extract/classifier.py
works offline. To use a larger, higher-quality model instead, edit the
`MODEL` constant below (e.g. `facebook/bart-large-mnli`, ~1.6 GB) and re-run.
"""

from __future__ import annotations

MODEL = "cross-encoder/nli-deberta-v3-small"
LABELS = ["armed conflict", "not armed conflict"]


def main() -> None:
    from huggingface_hub import snapshot_download
    from transformers import pipeline

    print(f"Downloading {MODEL} (this may take several minutes)...")
    snapshot_download(MODEL)
    print("Download complete. Running sanity check...")

    clf = pipeline("zero-shot-classification", model=MODEL)
    result = clf("missile strike kills 20 civilians", LABELS)
    scores = dict(zip(result["labels"], result["scores"]))
    print(
        f"sanity check: 'missile strike kills 20 civilians' -> armed conflict={scores['armed conflict']:.3f}"
    )
    print("Model ready.")


if __name__ == "__main__":
    main()
