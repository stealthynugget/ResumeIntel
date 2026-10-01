"""Run the documented local API journey and audit exact quote/span integrity."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api import app

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("data_scientist", "it_infrastructure_engineer", "hr_analyst")


def main():
    reports = []
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert health["candidates"] > 0, "Seed the local corpus first"
        for name in ROLES:
            text = (ROOT / "data" / "demo" / f"{name}_jd.txt").read_text(encoding="utf-8")
            response = client.post("/api/jobs", json={"text": text})
            assert response.status_code == 200, response.text
            job = response.json()
            response = client.post(f"/api/jobs/{job['id']}/matches")
            assert response.status_code == 200, response.text
            run = response.json()
            checked = 0
            invalid = []
            for candidate in run["candidates"]:
                cid = candidate["id"]
                detail = client.get(f"/api/match-runs/{run['id']}/candidates/{cid}").json()
                source = client.get(f"/api/candidates/{cid}/source").json()
                spans = {span["id"]: span for span in source["spans"]}
                for assessment in detail["assessments"]:
                    if not assessment["quote"]:
                        continue
                    checked += 1
                    span = spans.get(assessment["span_id"])
                    excerpt = source["text"][span["start_offset"]:span["end_offset"]] if span else ""
                    if not span or assessment["quote"].lower() not in excerpt.lower():
                        invalid.append({"candidate_id": cid, "requirement": assessment["label"]})
            reports.append({"job": name, "job_id": job["id"], "run_id": run["id"],
                            "requirements": len(job["requirements"]), "retrieved": run["trace"]["retrieval"]["candidates"],
                            "analyzed": run["trace"]["analysis"]["candidates"],
                            "displayed": len(run["candidates"]), "citations_checked": checked, "invalid_citations": invalid,
                            "top_five": [{"candidate_id": c["id"], "external_id": c["external_id"],
                                          "match_index": c["match_index"], "mandatory_status": c["mandatory_status"]}
                                         for c in run["candidates"][:5]]})
    output = ROOT / "evaluation" / "smoke_results.json"
    output.write_text(json.dumps({"corpus": health, "runs": reports}, indent=2), encoding="utf-8")
    print(output)
    for report in reports:
        print(report["job"], "analyzed", report["analyzed"], "citations", report["citations_checked"],
              "invalid", len(report["invalid_citations"]))
    assert all(not report["invalid_citations"] for report in reports)


if __name__ == "__main__":
    main()
