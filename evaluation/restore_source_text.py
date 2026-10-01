"""One-time migration of older, trimmed CSV documents to exact source-cell text."""
import csv
import hashlib
from pathlib import Path

from backend.db import connect

SOURCE = Path(__file__).resolve().parents[1] / "data" / "source" / "Resume.csv"


def main():
    restored = already_exact = duplicate_rows = invalid = 0
    seen = set()
    with SOURCE.open(encoding="utf-8-sig", newline="") as file, connect() as db:
        for row in csv.DictReader(file):
            text = row.get("Resume_str") or ""
            if len(text.strip()) < 40:
                invalid += 1
                continue
            checksum = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
            candidate = db.execute("SELECT id FROM candidates WHERE checksum=?", (checksum,)).fetchone()
            if candidate is None:
                raise RuntimeError(f"Unindexed source ID {row.get('ID')}")
            cid = candidate["id"]
            if cid in seen:
                duplicate_rows += 1
                continue
            seen.add(cid)
            document = db.execute("SELECT id,text FROM documents WHERE candidate_id=?", (cid,)).fetchone()
            if document["text"] == text:
                already_exact += 1
                continue
            if document["text"] != text.strip():
                raise RuntimeError(f"Source text differs beyond edge whitespace for candidate {cid}")
            leading = len(text) - len(text.lstrip())
            db.execute("UPDATE documents SET text=? WHERE id=?", (text, document["id"]))
            db.execute("""UPDATE spans SET start_offset=start_offset+?,end_offset=end_offset+?
                WHERE candidate_id=?""", (leading, leading, cid))
            restored += 1
    print({"restored": restored, "already_exact": already_exact,
           "duplicate_source_rows": duplicate_rows, "invalid_source_rows": invalid})


if __name__ == "__main__":
    main()
