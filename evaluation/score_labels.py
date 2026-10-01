"""Compute pool-relative P@5 and nDCG@5 for exploratory manual labels."""
import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def ndcg(ids, labels):
    gains = [2 ** labels[cid] - 1 for cid in ids]
    dcg = sum(gain / math.log2(rank + 2) for rank, gain in enumerate(gains))
    best = sorted(labels.values(), reverse=True)[:len(ids)]
    ideal = sum((2 ** grade - 1) / math.log2(rank + 2) for rank, grade in enumerate(best))
    return dcg / ideal if ideal else 0.0


def calculate_metrics():
    pool = json.loads((ROOT / "evaluation" / "review_pool_manifest.json").read_text(encoding="utf-8"))
    with (ROOT / "evaluation" / "labels.csv").open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    labels_by_role = {}
    for row in rows:
        labels_by_role.setdefault(row["job"], {})[int(row["candidate_id"])] = int(row["relevance"])
    results = []
    for role in pool:
        labels = labels_by_role[role["job"]]
        pool_ids = set(role["pool_candidate_ids"])
        if len(role["pool_candidate_ids"]) != 18 or set(labels) != pool_ids:
            raise ValueError(f"Expected exactly 18 judged pool candidates for {role['job']}")
        for method in ("keyword", "hybrid"):
            ids = role[f"{method}_top_five"]
            missing = set(ids) - set(labels)
            if missing:
                raise ValueError(f"Missing {role['job']} labels: {sorted(missing)}")
            results.append({"job": role["job"], "method": method, "pool_size": len(labels),
                            "precision_at_5": sum(labels[cid] >= 2 for cid in ids) / len(ids),
                            "ndcg_at_5": round(ndcg(ids, labels), 3)})
    return results


def main():
    results = calculate_metrics()
    target = ROOT / "evaluation" / "metrics.json"
    target.write_text(json.dumps(results, indent=2), encoding="utf-8")
    for result in results:
        print(result)


if __name__ == "__main__":
    main()
