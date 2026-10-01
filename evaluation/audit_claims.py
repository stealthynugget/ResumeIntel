"""Check quote integrity for a separately hand-reviewed semantic sample."""
import csv
import json
from collections import Counter
from pathlib import Path

from backend.db import connect

ROOT = Path(__file__).resolve().parents[1]


def main():
    runs = {row["job"]: row["run_id"] for row in json.loads(
        (ROOT / "evaluation" / "smoke_results.json").read_text(encoding="utf-8"))["runs"]}
    with (ROOT / "evaluation" / "claim_audit.csv").open(encoding="utf-8", newline="") as file:
        reviewed = list(csv.DictReader(file))
    integrity_failures = []
    with connect() as db:
        for item in reviewed:
            cid = int(item["candidate_id"])
            result = db.execute("SELECT assessments_json FROM results WHERE run_id=? AND candidate_id=?",
                                (runs[item["job"]], cid)).fetchone()
            assert result, f"Candidate {cid} missing from reviewed run"
            assessment = next(a for a in json.loads(result["assessments_json"])
                              if a["label"] == item["requirement"])
            item["app_status"] = assessment["status"]
            item["has_quote"] = bool(assessment["quote"])
            if assessment["quote"]:
                span = db.execute("""SELECT s.text,s.start_offset,s.end_offset,d.text AS source
                    FROM spans s JOIN documents d ON d.id=s.document_id
                    WHERE s.id=? AND s.candidate_id=?""", (assessment["span_id"], cid)).fetchone()
                if not span or span["source"][span["start_offset"]:span["end_offset"]] != span["text"] \
                        or assessment["quote"].lower() not in span["text"].lower():
                    integrity_failures.append(f"{item['job']}:{cid}:{item['requirement']}")
    assert not integrity_failures, integrity_failures
    result = {"claims_reviewed": len(reviewed),
              "quotes_checked": sum(row["has_quote"] for row in reviewed),
              "quote_integrity_failures": integrity_failures,
              "semantic_judgments": dict(Counter(row["semantic_judgment"] for row in reviewed)),
              "status_counts": dict(Counter(row["app_status"] for row in reviewed))}
    (ROOT / "evaluation" / "claim_audit_results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
