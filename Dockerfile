# Global Conflict Map — CPU-only runtime image.
#
# Note: no ENTRYPOINT/CMD here; both are set in docker-compose.yml so the
# one-shot `pipeline` service can accept extra CLI args cleanly.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # Model cache lives on the persistent /data volume so a container recreate
    # doesn't re-download the ~570 MB zero-shot model.
    HF_HOME=/data/hf-cache

WORKDIR /app

# No apt-get layer: nothing here needs a system package. torch's CPU wheel
# bundles its own libgomp.so.1 (OpenMP), so `import torch` works on slim images
# without installing libgomp1 — verified with a bare python:3.12-slim.

# One install from the lock: every version and hash is fixed, and the file names
# the PyTorch CPU index so torch resolves to the `+cpu` wheel rather than the
# multi-GB CUDA build. Hashes mean pip rejects an unexpected artifact.
# requirements-ci.txt (pytest, ruff, ty, pymarkdown, pip-audit) is deliberately
# absent: those belong to the gates, not the runtime image.
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

COPY . .
