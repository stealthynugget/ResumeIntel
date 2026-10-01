"""Measure retrieval and full ranking on the local corpus."""
import json
import statistics
import time
from pathlib import Path

from backend.db import connect
from backend.matching import parse_job, retrieve, run_match

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("data_scientist", "it_infrastructure_engineer", "hr_analyst")


def main():
    results = []
    for name in ROLES:
        text = (ROOT / "data" / "demo" / f"{name}_jd.txt").read_text(encoding="utf-8")
        title, requirements = parse_job(text)
        query = text + " " + " ".join(req["label"] for req in requirements)
        started = time.perf_counter()
        hits = retrieve(query, requirements, title, 30)
        cold = time.perf_counter() - started
        warm = []
        for _ in range(5):
            started = time.perf_counter()
            retrieve(query, requirements, title, 30)
            warm.append(time.perf_counter() - started)
        with connect() as db:
            cur = db.execute("INSERT INTO jobs(title,text) VALUES(?,?)", (title, text))
            for req in requirements:
                db.execute("INSERT INTO requirements(job_id,label,kind,mandatory) VALUES(?,?,?,?)",
                           (cur.lastrowid, req["label"], req["kind"], int(req["mandatory"])))
            job_id = cur.lastrowid
        started = time.perf_counter()
        run_id = run_match(job_id)
        end_to_end = time.perf_counter() - started
        with connect() as db:
            ranked = db.execute("SELECT candidate_id,match_index,mandatory_status FROM results WHERE run_id=? ORDER BY rank LIMIT 5", (run_id,)).fetchall()
        results.append({"role": name, "job_id": job_id, "run_id": run_id, "retrieved": len(hits),
                        "cold_retrieval_ms": round(cold * 1000, 1),
                        "warm_retrieval_ms": [round(value * 1000, 1) for value in warm],
                        "warm_median_ms": round(statistics.median(warm) * 1000, 1),
                        "full_match_ms": round(end_to_end * 1000, 1),
                        "top_five": [dict(row) for row in ranked]})
    target = ROOT / "evaluation" / "benchmark_full.json"
    target.write_text(json.dumps(results, indent=2), encoding="utf-8")
    for result in results:
        print(result["role"], "retrieved", result["retrieved"], "warm median ms", result["warm_median_ms"],
              "full match ms", result["full_match_ms"])


if __name__ == "__main__":
    main()
