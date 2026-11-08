# Global Conflict Map — CPU-only runtime image.
#
# Note: no ENTRYPOINT/CMD here; both are set in docker-compose.yml so the
# one-shot `pipeline` service can accept extra CLI args cleanly.
FROM python:3.11-slim

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

# Install torch CPU-only first. requirements.txt lists bare `torch`, so strip
# that line for the second install — otherwise pip "upgrades" to the multi-GB
# CUDA wheel from PyPI.
COPY requirements.txt ./
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && grep -v '^torch' requirements.txt > requirements-no-torch.txt \
    && pip install --no-cache-dir -r requirements-no-torch.txt \
    && rm requirements-no-torch.txt

COPY . .
