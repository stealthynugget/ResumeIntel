"""Read-only current-corpus retrieval audit; leaves historical benchmark untouched."""

import json
import platform
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

from backend.db import connect
from backend.demo_roles import all_roles
from backend.matching import _lexical_query, parse_job, retrieve

ROOT = Path(__file__).resolve().parents[1]


def audit():
    process = psutil.Process()
    with connect() as db:
        candidates = db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        spans = db.execute("SELECT COUNT(*) FROM spans").fetchone()[0]
        fts = db.execute("SELECT COUNT(*) FROM spans_fts").fetchone()[0]
    roles = []
    for role in (item for item in all_roles() if item["evaluated"]):
        title, requirements = parse_job(role["text"])
        query = _lexical_query(requirements, title)
        with connect() as db:
            lexical = db.execute("""SELECT s.candidate_id FROM spans_fts
                JOIN spans s ON s.id=spans_fts.rowid WHERE spans_fts MATCH ?
                ORDER BY bm25(spans_fts) LIMIT 3000""", (query,)).fetchall()
        text = role["text"] + " " + " ".join(item["label"] for item in requirements)
        timings = []
        for _ in range(6):
            start = time.perf_counter()
            hits = retrieve(text, requirements, title, limit=30)
            timings.append(round(1000 * (time.perf_counter() - start), 1))
        roles.append({"role": role["id"], "lexical_span_hits_capped_3000": len(lexical),
                      "lexical_unique_candidates_in_cap": len({row["candidate_id"] for row in lexical}),
                      "retrieved": len(hits), "first_call_ms": timings[0],
                      "warm_calls_ms": timings[1:], "warm_median_ms": round(statistics.median(timings[1:]), 1)})
    return {"version": 1, "generated_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "current local database; read-only retrieval; no rankings or labels recomputed",
            "method": "unchanged FTS5 + MiniLM + RRF", "candidates": candidates,
            "spans": spans, "fts_rows": fts, "environment": {
                "system": platform.system(), "python": platform.python_version(),
                "process": "one Python process", "logical_cpus": psutil.cpu_count(),
                "processor": platform.processor() or "not recorded"},
            "peak_process_rss_mb": round(process.memory_info().peak_wset / 1_000_000, 1)
                if hasattr(process.memory_info(), "peak_wset") else None,
            "roles": roles}


def main():
    result = audit()
    target = ROOT / "evaluation" / "retrieval_audit_v1.json"
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
