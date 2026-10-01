"""Check every source record outcome and source-to-index integrity."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from backend.db import connect

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / "data" / "source" / "Resume.csv"
    with source.open(encoding="utf-8-sig", newline="") as file:
        source_rows = list(csv.DictReader(file))
    with connect() as db:
        job = db.execute("""SELECT * FROM import_jobs WHERE filename='Resume.csv' AND total_rows=?
            AND imported>0 ORDER BY id LIMIT 1""", (len(source_rows),)).fetchone()
        assert job, "Full-corpus import job not found"
        outcomes = db.execute("SELECT row_number,status,candidate_id FROM import_job_rows WHERE job_id=? ORDER BY row_number", (job["id"],)).fetchall()
        assert len(outcomes) == len(source_rows)
        assert [row["row_number"] for row in outcomes] == list(range(1, len(source_rows) + 1))
        counts = Counter(row["status"] for row in outcomes)
        candidates = db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        spans = db.execute("SELECT COUNT(*) FROM spans").fetchone()[0]
        fts = db.execute("SELECT COUNT(*) FROM spans_fts").fetchone()[0]
        bad_offsets = db.execute("""SELECT COUNT(*) FROM spans s JOIN documents d ON d.id=s.document_id
            WHERE substr(d.text,s.start_offset+1,s.end_offset-s.start_offset) != s.text""").fetchone()[0]
        assert spans == fts and bad_offsets == 0
        assert counts["imported"] + counts["duplicate"] + counts["invalid"] + counts["failed"] == len(source_rows)
        checked_source = set()
        for source_row in source_rows:
            text = source_row.get("Resume_str") or ""
            if len(text.strip()) < 40:
                continue
            checksum = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
            if checksum in checked_source:
                continue
            checked_source.add(checksum)
            document = db.execute("""SELECT d.text FROM documents d JOIN candidates c ON c.id=d.candidate_id
                WHERE c.checksum=?""", (checksum,)).fetchone()
            assert document and document["text"] == text, f"Source cell mismatch for ID {source_row.get('ID')}"
        examples = {}
        for category, term in (("INFORMATION-TECHNOLOGY", "Active Directory"),
                               ("HR", "recruitment"), ("ENGINEERING", "Python")):
            row = db.execute("""SELECT c.id,s.id AS span_id FROM spans_fts
                JOIN spans s ON s.id=spans_fts.rowid JOIN candidates c ON c.id=s.candidate_id
                WHERE spans_fts MATCH ? AND c.category=? LIMIT 1""", (f'"{term}"', category)).fetchone()
            assert row, f"No indexed {term} evidence found in {category}"
            examples[category] = {"candidate_id": row["id"], "span_id": row["span_id"], "term": term}
    result = {"source_rows": len(source_rows), "import_job_id": job["id"], "outcomes": dict(counts),
              "candidates": candidates, "spans": spans, "fts_rows": fts, "bad_offsets": bad_offsets,
              "exact_source_documents": len(checked_source),
              "searched_examples": examples, "import_seconds": job["duration_seconds"],
              "peak_process_rss_mb": job["peak_rss_mb"]}
    target = ROOT / "evaluation" / "import_verification.json"
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
