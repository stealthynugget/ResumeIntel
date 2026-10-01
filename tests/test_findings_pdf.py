"""Saved findings must be private, reproducible, and independent of later JD edits."""

import json
from io import BytesIO

import pdfplumber
from fastapi.testclient import TestClient

from backend import db
from backend.api import app


def _signup(client, email):
    response = client.post("/api/auth/signup", json={"email": email, "display_name": "Reviewer",
                                                      "password": "a-local-test-passphrase"})
    assert response.status_code == 201
    return response.json()


def _saved_run(owner_id):
    with db.connect() as connection:
        candidate_id = connection.execute(
            "INSERT INTO candidates(external_id,name,category,source_type,checksum,owner_user_id) VALUES(?,?,?,?,?,?)",
            ("source-101", "Long <Research & Analysis> Candidate " * 8, "ENGINEERING", "pdf", "pdf-one", owner_id)).lastrowid
        source = "Built Python services and data pipelines. " * 22
        document_id = connection.execute("INSERT INTO documents(candidate_id,text) VALUES(?,?)",
                                         (candidate_id, source)).lastrowid
        span_id = connection.execute(
            "INSERT INTO spans(document_id,candidate_id,start_offset,end_offset,text) VALUES(?,?,?,?,?)",
            (document_id, candidate_id, 0, len(source), source)).lastrowid
        job_id = connection.execute("INSERT INTO jobs(title,text,owner_user_id) VALUES('Data Engineer','Required Python',?)",
                                    (owner_id,)).lastrowid
        requirement_id = connection.execute(
            "INSERT INTO requirements(job_id,label,kind,mandatory) VALUES(?,'Python','skill',1)", (job_id,)).lastrowid
        run_id = connection.execute(
            "INSERT INTO match_runs(job_id,requirements_version,trace_json,owner_user_id) VALUES(?,1,?,?)",
            (job_id, json.dumps({"retrieval": {"candidates": 30}, "analysis": {"candidates": 30}}), owner_id)).lastrowid
        assessments = [
            {"requirement_id": requirement_id, "label": "Python", "kind": "skill", "mandatory": True,
             "status": "matched", "span_id": span_id, "quote": "Python", "reason": "Resume mention"},
            {"requirement_id": 999, "label": "3 years experience", "kind": "experience", "mandatory": True,
             "status": "no_evidence", "span_id": None, "quote": None, "reason": "No duration"},
        ]
        connection.execute("""INSERT INTO results(run_id,candidate_id,rank,match_index,mandatory_status,
            score_json,assessments_json,trace_json) VALUES(?,?,1,72.5,'incomplete','{}',?,'{}')""",
                           (run_id, candidate_id, json.dumps(assessments)))
    return job_id, run_id


def _text(payload):
    with pdfplumber.open(BytesIO(payload)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def test_report_requires_session_and_owner_and_does_not_mutate_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "reports.db")
    db.init_db()
    owner, other = TestClient(app), TestClient(app)
    assert owner.get("/api/match-runs/1/report.pdf").status_code == 401
    owner_id = _signup(owner, "report-owner@example.test")["id"]
    _signup(other, "report-other@example.test")
    _, run_id = _saved_run(owner_id)
    with db.connect() as connection:
        before = list(connection.iterdump())
    assert other.get(f"/api/match-runs/{run_id}/report.pdf").status_code == 404
    response = owner.get(f"/api/match-runs/{run_id}/report.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "private, no-store"
    assert f"resumeintel-run-{run_id}-findings.pdf" in response.headers["content-disposition"]
    text = _text(response.content)
    assert "Data Engineer" in text and "30 retrieved" in text and "30 analyzed" in text
    assert "Python" in text and "3 years experience" in text and "span #" in text
    assert "Built Python services" in text
    assert "Research & Analysis" in text  # Escaped markup remains readable source data.
    with db.connect() as connection:
        assert list(connection.iterdump()) == before


def test_report_uses_frozen_assessments_after_requirement_edit(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "frozen.db")
    db.init_db()
    client = TestClient(app)
    user = _signup(client, "frozen@example.test")
    job_id, run_id = _saved_run(user["id"])
    previous = client.get(f"/api/match-runs/{run_id}/report.pdf")
    assert previous.status_code == 200
    changed = client.patch(f"/api/jobs/{job_id}/requirements",
                           headers={"X-CSRF-Token": user["csrf_token"]},
                           json={"requirements": [{"label": "Rust", "kind": "skill", "mandatory": True}]})
    assert changed.status_code == 200
    current = client.get(f"/api/match-runs/{run_id}/report.pdf")
    assert current.status_code == 200
    assert current.content == previous.content
    text = _text(current.content)
    assert "Python" in text and "Rust" not in text
