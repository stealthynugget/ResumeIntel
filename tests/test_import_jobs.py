import csv

import numpy as np

from backend import db, import_jobs, matching


def test_batch_import_accounts_for_every_row_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(import_jobs, "embed", lambda texts: np.zeros((len(texts), 384), dtype=np.float32))
    db.init_db()
    path = tmp_path / "resumes.csv"
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["ID", "Category", "Resume_str"])
        writer.writeheader()
        writer.writerows([
            {"ID": "1", "Category": "A", "Resume_str": "  " + "Python and SQL projects for data teams. " * 3 + "\n"},
            {"ID": "2", "Category": "A", "Resume_str": "Python and SQL projects for data teams. " * 3},
            {"ID": "3", "Category": "B", "Resume_str": "short"},
            {"ID": "4", "Category": "B", "Resume_str": "Recruiting and analytics for healthcare teams. " * 3},
        ])
    first = import_jobs.run_job(import_jobs.create_job(path))
    assert first["status"] == "completed"
    assert (first["total_rows"], first["processed_rows"], first["imported"], first["duplicate"], first["invalid"], first["failed"]) == (4, 4, 2, 1, 1, 0)
    with db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM spans_fts").fetchone()[0] == connection.execute("SELECT COUNT(*) FROM spans").fetchone()[0]
        document = connection.execute("SELECT text FROM documents WHERE candidate_id=1").fetchone()[0]
        assert document.startswith("  Python") and document.endswith("\n")
        assert connection.execute("""SELECT COUNT(*) FROM spans s JOIN documents d ON d.id=s.document_id
            WHERE substr(d.text,s.start_offset+1,s.end_offset-s.start_offset)!=s.text""").fetchone()[0] == 0
        initial_vectors = len(matching._matrix(connection)[1])
    second = import_jobs.run_job(import_jobs.create_job(path))
    assert (second["imported"], second["duplicate"], second["invalid"]) == (0, 3, 1)
    another = tmp_path / "another.csv"
    with another.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["ID", "Category", "Resume_str"])
        writer.writeheader()
        writer.writerow({"ID": "5", "Category": "B", "Resume_str": "Built reliable Linux and network infrastructure. " * 3})
    assert import_jobs.run_job(import_jobs.create_job(another))["imported"] == 1
    with db.connect() as connection:
        assert len(matching._matrix(connection)[1]) > initial_vectors


def test_failed_batch_retries_without_reinserting_completed_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "retry.db")
    db.init_db()
    path = tmp_path / "retry.csv"
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["ID", "Category", "Resume_str"])
        writer.writeheader()
        writer.writerows({"ID": str(i), "Category": "A",
                          "Resume_str": f"Candidate {i} built Python and SQL data tools for business teams. " * 2}
                         for i in range(25))
    calls = 0

    def flaky(texts):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("temporary model failure")
        return np.zeros((len(texts), 384), dtype=np.float32)

    monkeypatch.setattr(import_jobs, "embed", flaky)
    job_id = import_jobs.create_job(path)
    first = import_jobs.run_job(job_id)
    assert first["status"] == "failed" and first["processed_rows"] == 24 and first["imported"] == 24
    monkeypatch.setattr(import_jobs, "embed", lambda texts: np.zeros((len(texts), 384), dtype=np.float32))
    second = import_jobs.run_job(job_id)
    assert second["status"] == "completed"
    assert (second["processed_rows"], second["imported"], second["duplicate"], second["failed"]) == (25, 25, 0, 0)
    with db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 25
