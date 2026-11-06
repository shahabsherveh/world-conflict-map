"""Evaluate conflict filters against the labeled fixture."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.extract.classifier import ZeroShotConflictClassifier, slug_to_text

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/eval/labeled_sample.json"


def load_articles() -> list[dict]:
    data = json.loads(FIXTURE.read_text())
    by_url: dict[str, dict] = {}
    for item in data:
        raw = item["raw"]
        url = raw.get("source_url") or raw.get("global_event_id")
        rec = by_url.setdefault(url, {"raw": raw, "label": 0})
        rec["label"] = max(rec["label"], item["label"])
    return list(by_url.values())


def metrics(preds: list[int], truths: list[int]) -> tuple[float, float, float, int, int, int]:
    tp = sum(1 for p, t in zip(preds, truths) if p == 1 and t == 1)
    fp = sum(1 for p, t in zip(preds, truths) if p == 1 and t == 0)
    fn = sum(1 for p, t in zip(preds, truths) if p == 0 and t == 1)
    prec = tp / max(1, tp + fp)
    rec = tp / max(1, tp + fn)
    f1 = 2 * prec * rec / max(1e-9, prec + rec)
    return prec, rec, f1, tp, fp, fn


def main() -> None:
    articles = load_articles()
    truths = [a["label"] for a in articles]
    print(f"unique articles: {len(articles)}, conflict articles: {sum(truths)}")

    print("BASELINE (keep all):", metrics([1] * len(articles), truths))

    print("Loading model...")
    clf = ZeroShotConflictClassifier()
    preds: list[int] = []
    for a in articles:
        text = slug_to_text(a["raw"].get("source_url", "")) or "unknown"
        keep, _ = clf.classify(text)
        preds.append(1 if keep else 0)

    print("ZERO-SHOT (slug):", metrics(preds, truths))

    print("\ndisagreements:")
    for a, p, t in zip(articles, preds, truths):
        if p != t:
            tag = "FP" if p == 1 else "FN"
            print(
                f"  [{tag}] label={t} pred={p}  {slug_to_text(a['raw'].get('source_url', ''))[:90]}"
            )


if __name__ == "__main__":
    main()
