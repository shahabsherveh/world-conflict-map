"""Zero-shot filtering of event drafts (semantic armed-conflict gate)."""

from __future__ import annotations

from app.extract.base import EventDraft
from app.extract.classifier import (
    DEFAULT_THRESHOLD,
    BinaryClassifier,
    Classifier,
    slug_to_text,
)


def filter_by_zero_shot(
    drafts: list[EventDraft],
    classifier: Classifier,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[EventDraft]:
    """Drop drafts whose source URL slug doesn't classify as armed conflict.

    Drafts without a source URL are kept (the adapter's root-code filter has
    already been applied; no semantic signal is available). Slugs are deduped
    before inference because GDELT often has many events per article.
    """
    indexed = [
        (index, slug_to_text(draft.source_url))
        for index, draft in enumerate(drafts)
        if draft.source_url
    ]
    unique_texts = list(dict.fromkeys(text for _, text in indexed))

    if isinstance(classifier, BinaryClassifier):
        results = classifier.classify_many(unique_texts, threshold)
    else:
        results = [classifier.classify(text, threshold) for text in unique_texts]
    by_text = dict(zip(unique_texts, results, strict=True))

    keep = [not draft.source_url for draft in drafts]
    for index, text in indexed:
        keep[index] = by_text[text][0]
    return [draft for draft, accepted in zip(drafts, keep, strict=True) if accepted]
