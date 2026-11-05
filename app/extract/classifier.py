"""Zero-shot armed-conflict classifier (pretrained NLI model, no task training)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

CONFLICT_LABEL = "armed conflict"
NOT_CONFLICT_LABEL = "not armed conflict"
DEFAULT_THRESHOLD = 0.7


def slug_to_text(url: str) -> str:
    """Turn an article URL slug into a headline-like text for display/classification."""
    path = urlparse(url).path
    slug = path.rsplit("/", 1)[-1]
    slug = re.sub(r"\.(html?|php|aspx?)$", "", slug)
    slug = re.sub(r"^\d{6,}[-_]", "", slug)  # leading article id, e.g. 2087359569-
    text = re.sub(r"[-_]+", " ", slug).strip()
    text = re.sub(r"\s+\d{5,}$", "", text)  # trailing article id
    return re.sub(r"\s+", " ", text).strip()


class ZeroShotConflictClassifier:
    def __init__(self, model: str = "cross-encoder/nli-deberta-v3-small") -> None:
        from transformers import pipeline

        self._pipeline = pipeline("zero-shot-classification", model=model)
        self._labels = [CONFLICT_LABEL, NOT_CONFLICT_LABEL]

    def classify(self, text: str, threshold: float = DEFAULT_THRESHOLD) -> tuple[bool, float]:
        """Return (is_conflict, confidence) for a text."""
        text = (text or "").strip()
        if not text:
            return False, 0.0
        result = self._pipeline(text, self._labels)
        scores = dict(zip(result["labels"], result["scores"]))
        score = scores[CONFLICT_LABEL]
        return score >= threshold, score
