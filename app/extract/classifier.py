"""Zero-shot armed-conflict classifier (pretrained NLI model, no task training)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

CONFLICT_LABEL = "armed conflict"
NOT_CONFLICT_LABEL = "not armed conflict"
DEFAULT_THRESHOLD = 0.7
DEFAULT_BATCH_SIZE = 16


def slug_to_text(url: str) -> str:
    """Turn an article URL slug into a headline-like text for display/classification."""
    # GDELT source URLs frequently end with a slash; without rstrip the slug is
    # empty and every such event is silently dropped by the zero-shot filter.
    path = urlparse(url).path.rstrip("/")
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

    def classify_many(
        self, texts: list[str], threshold: float = DEFAULT_THRESHOLD
    ) -> list[tuple[bool, float]]:
        """Classify a list in batches; empty texts are dropped before inference."""
        if not texts:
            return []
        non_empty = [text for text in texts if text.strip()]
        results = (
            self._pipeline(non_empty, self._labels, batch_size=DEFAULT_BATCH_SIZE)
            if non_empty
            else []
        )
        if isinstance(results, dict):  # single-item input fallback
            results = [results]
        result_iter = iter(results)
        out: list[tuple[bool, float]] = []
        for text in texts:
            if not text.strip():
                out.append((False, 0.0))
                continue
            result = next(result_iter)
            scores = dict(zip(result["labels"], result["scores"]))
            score = scores[CONFLICT_LABEL]
            out.append((score >= threshold, score))
        return out
