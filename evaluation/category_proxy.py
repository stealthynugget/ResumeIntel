"""Exploratory category-label retrieval diagnostic, not JD relevance evaluation."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from backend.db import connect
from backend.matching import keyword_candidates, retrieve

ROOT = Path(__file__).resolve().parents[1]


def score(ids, labels, category):
    hits = [int(labels.get(candidate_id) == category) for candidate_id in ids[:5]]
    hits += [0] * (5 - len(hits))
    ideal = min(5, sum(label == category for label in labels.values()))
    denominator = sum(1 / math.log2(index + 2) for index in range(ideal))
    return {"precision_at_5": round(sum(hits) / 5, 3),
            "ndcg_at_5": round(sum(hit / math.log2(index + 2) for index, hit in enumerate(hits)) / denominator, 3)
            if denominator else 0.0}


def main():
    with connect() as db:
        labels = {row["id"]: row["category"] for row in db.execute(
            "SELECT id,category FROM candidates WHERE source_type='csv' AND owner_user_id IS NULL AND category IS NOT NULL")}
    categories = sorted(set(labels.values()))
    rows = []
    for category in categories:
        title = category.replace('-', ' ').replace('_', ' ').title()
        with connect() as db:
            keyword = [candidate_id for candidate_id in keyword_candidates(db, [], title, limit=100)
                       if candidate_id in labels][:5]
        hybrid = [item["candidate_id"] for item in retrieve(
            f"{title} role", [], title, limit=100) if item["candidate_id"] in labels][:5]
        rows.append({"category": category, "candidate_count": sum(value == category for value in labels.values()),
                     "keyword": score(keyword, labels, category), "hybrid": score(hybrid, labels, category)})
        print(category, rows[-1]["keyword"]["precision_at_5"], rows[-1]["hybrid"]["precision_at_5"])
    artifact = {"generated_utc": datetime.now(timezone.utc).isoformat(), "shared_candidates": len(labels),
                "method": "Query each dataset category name against shared CSV resumes; score top five by exact dataset category label agreement. Binary category labels are weak proxies, not JD relevance judgments.",
                "categories": rows}
    (ROOT / 'evaluation' / 'category_proxy_results.json').write_text(json.dumps(artifact, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
