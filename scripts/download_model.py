"""Ensure the zero-shot model is in the shared cache (network, or a copied cache).

Run from anywhere:
    python scripts/download_model.py            # download if missing
    python scripts/download_model.py --check    # verify only, no network

The cache location comes from HF_HOME. scripts/_data-dir.sh exports it to
<GCM_DATA_DIR>/hf-cache, and the container uses the same path (the Dockerfile
sets HF_HOME=/data/hf-cache over the mounted data dir). Note that this only
applies when a script sources _data-dir.sh: running this file directly with
HF_HOME unset uses ~/.cache/huggingface, which the pipeline will NOT load — the
script warns when that happens. To target the shared cache explicitly:

    HF_HOME=/var/lib/global-conflict-map/db/hf-cache python scripts/download_model.py

If this machine cannot reach HuggingFace's large-file CDN (cdn-lfs times out),
larger downloads stall and leave *.incomplete blobs. In that case copy a complete
cache from a machine that has one — no need to download here:

    rsync -a ~/.cache/huggingface/hub/models--cross-encoder--nli-deberta-v3-small \\
          "$GCM_DATA_DIR/hf-cache/hub/"

(`scripts/cutover-data.sh` also copies an existing <data dir>/hf-cache.)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

MODEL = "cross-encoder/nli-deberta-v3-small"
LABELS = ["armed conflict", "not armed conflict"]
# transformers loads the PyTorch weights, not the repo's onnx/*.onnx files, so a
# cache holding only ONNX is still incomplete for this app. A usable cache needs
# *any one* of these — the repo publishes both, and transformers prefers
# safetensors when present.
WEIGHT_FILES = ("pytorch_model.bin", "model.safetensors")


def cache_root() -> Path:
    return Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))


def warn_if_default_cache() -> None:
    """Point out a cache the deployed stack does not read.

    HF_HOME is normally exported by scripts/_data-dir.sh (which sets it to
    <GCM_DATA_DIR>/hf-cache, the volume the container mounts). Running this
    script by hand, or `python -m app.extract.run` directly, does not source
    that file, so the model lands in ~/.cache/huggingface instead — a second
    copy the pipeline then downloads again. Say so rather than let it drift.
    """
    if os.environ.get("HF_HOME"):
        return
    print(
        "warning: HF_HOME is not set, so this uses ~/.cache/huggingface.\n"
        "          scripts/daily.sh and the container use <GCM_DATA_DIR>/hf-cache,\n"
        "          so a model downloaded here is not the one they will load.\n"
        "          Use the shared location: source scripts/_data-dir.sh first,\n"
        "          or run: HF_HOME=$GCM_DATA_DIR/hf-cache python scripts/download_model.py",
        file=sys.stderr,
    )


def snapshot_dir() -> Path:
    # Local layout only (the hub cache stores models--<org>--<name>).
    return cache_root() / "hub" / f"models--{MODEL.replace('/', '--')}" / "snapshots"


def has_weights() -> bool:
    """True when any snapshot holds a PyTorch weight file (one is enough)."""
    snapshots = snapshot_dir()
    if not snapshots.is_dir():
        return False
    for snap in snapshots.iterdir():
        if snap.is_dir() and any((snap / name).exists() for name in WEIGHT_FILES):
            return True
    return False


def incomplete_blobs() -> list[Path]:
    blobs = snapshot_dir().parent / "blobs"
    return sorted(blobs.glob("*.incomplete")) if blobs.is_dir() else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="only verify the cache; exit 1 (without downloading) if weights are missing",
    )
    args = parser.parse_args(argv)

    root = cache_root()
    print(f"cache: {root}")
    warn_if_default_cache()

    partials = incomplete_blobs()
    if has_weights():
        print(f"model present: {MODEL}")
        if partials:
            print(f"note: {len(partials)} stale *.incomplete blob(s) can be deleted")
        print("Model ready.")
        return 0

    if partials:
        print(f"warning: {len(partials)} partial download(s) found — a previous run stalled.")
    if args.check:
        print(
            f"FAIL: no PyTorch weights ({' or '.join(WEIGHT_FILES)}) cached for {MODEL}\n"
            "Copy a complete cache from another machine into "
            f"{root}/hub/ (see the module docstring), or re-run without --check on a "
            "network that can reach cdn-lfs.huggingface.co.",
            file=sys.stderr,
        )
        return 1

    print(f"Downloading {MODEL} (~570 MB; this may take several minutes)...")
    from huggingface_hub import snapshot_download
    from transformers import pipeline

    snapshot_download(MODEL, max_workers=1)
    print("Download complete. Running sanity check...")

    clf = pipeline("zero-shot-classification", model=MODEL)
    result = clf("missile strike kills 20 civilians", LABELS)
    scores = dict(zip(result["labels"], result["scores"], strict=False))
    score = scores["armed conflict"]
    print(f"sanity check: 'missile strike kills 20 civilians' -> armed conflict={score:.3f}")
    print("Model ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
