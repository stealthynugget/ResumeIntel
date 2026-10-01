"""Construct fixed-size JD/candidate review pools from two retrieval methods."""
import json
import re
from pathlib import Path

from backend.db import connect
from backend.matching import keyword_candidates

ROOT = Path(__file__).resolve().parents[1]


def main():
    smoke = json.loads((ROOT / "evaluation" / "smoke_results.json").read_text(encoding="utf-8"))
    output = []
    with connect() as db:
        for run in smoke["runs"]:
            name = run["job"]
            job = db.execute("SELECT * FROM jobs WHERE id=?", (run["job_id"],)).fetchone()
            requirements = [dict(row) for row in db.execute("SELECT * FROM requirements WHERE job_id=?", (job["id"],))]
            keyword = keyword_candidates(db, requirements, job["title"], limit=30)
            hybrid = [row["candidate_id"] for row in db.execute(
                "SELECT candidate_id FROM results WHERE run_id=? ORDER BY rank", (run["run_id"],))]
            selected = []
            for rank in range(max(len(keyword), len(hybrid))):
                for sequence in (hybrid, keyword):
                    if rank < len(sequence) and sequence[rank] not in selected:
                        selected.append(sequence[rank])
                    if len(selected) >= 16:
                        break
                if len(selected) >= 16:
                    break
            negative_category = "AVIATION" if name == "hr_analyst" else "CHEF"
            negative_ids = [row["id"] for row in db.execute(
                "SELECT id FROM candidates WHERE category=? ORDER BY id LIMIT 20", (negative_category,))]
            for cid in negative_ids:
                if cid not in selected:
                    selected.append(cid)
                if len(selected) >= 18:
                    break
            pool = []
            for cid in selected:
                row = db.execute("""SELECT c.category,d.text FROM candidates c JOIN documents d ON d.candidate_id=c.id
                    WHERE c.id=?""", (cid,)).fetchone()
                result = db.execute("SELECT assessments_json FROM results WHERE run_id=? AND candidate_id=?", (run["run_id"], cid)).fetchone()
                assessments = json.loads(result["assessments_json"]) if result else []
                pool.append({"candidate_id": cid, "category": row["category"],
                             "resume_preview": re.sub(r"\s+", " ", row["text"][:1200]),
                             "assessments": [{"label": a["label"], "status": a["status"], "quote": a["quote"]}
                                             for a in assessments]})
            output.append({"job": name, "job_id": job["id"], "run_id": run["run_id"],
                           "keyword_top_five": keyword[:5], "hybrid_top_five": hybrid[:5],
                           "keyword_top_ten": keyword[:10], "hybrid_top_ten": hybrid[:10],
                           "pool": pool})
    target = ROOT / "evaluation" / "review_pool.json"
    target.write_text(json.dumps(output, indent=2), encoding="utf-8")
    for item in output:
        print(item["job"], "pool", len(item["pool"]), "keyword", item["keyword_top_five"],
              "hybrid", item["hybrid_top_five"])


if __name__ == "__main__":
    main()
