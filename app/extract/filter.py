"""Zero-shot filtering of event drafts (semantic armed-conflict gate)."""

from __future__ import annotations

from app.extract.base import EventDraft
from app.extract.classifier import DEFAULT_THRESHOLD, ZeroShotConflictClassifier, slug_to_text


def filter_by_zero_shot(
    drafts: list[EventDraft],
    classifier: ZeroShotConflictClassifier,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[EventDraft]:
    """Drop drafts whose source URL slug doesn't classify as armed conflict.

    Drafts without a source URL are kept (the adapter's root-code filter has
    already been applied; no semantic signal is available).
    """
    kept: list[EventDraft] = []
    for draft in drafts:
        if not draft.source_url:
            kept.append(draft)
            continue
        is_conflict, _ = classifier.classify(slug_to_text(draft.source_url), threshold)
        if is_conflict:
            kept.append(draft)
    return kept
