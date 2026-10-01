"""Acceptance checks for the five recruiter questions in the capstone brief."""
import json

from fastapi.testclient import TestClient

from backend import chat_service, db
from backend.api import app


QUESTIONS = [
    "Which candidates are most relevant for this Data Scientist position?",
    "Which candidates have Python, SQL and machine learning experience?",
    "What skills are missing for this candidate compared with the job description?",
    "Why was this candidate matched with the role?",
    "Which candidates satisfy the mandatory requirements?",
]


def _fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "capstone.db")
    monkeypatch.setattr(chat_service, "configuration", lambda: {"configured": False})
    db.init_db()
    client = TestClient(app)
    signup = client.post("/api/auth/signup", json={"email": "panel@example.test", "display_name": "Panel",
                                                   "password": "long-unique-passphrase"})
    assert signup.status_code == 201
    csrf = signup.json()["csrf_token"]
    with db.connect() as connection:
        owner = connection.execute("SELECT id FROM users WHERE email='panel@example.test'").fetchone()[0]
        job = connection.execute("INSERT INTO jobs(title,text,owner_user_id) VALUES('Data Scientist','Required Python SQL machine learning and 3 years experience',?)", (owner,)).lastrowid
        labels = [("Python", "skill"), ("SQL", "skill"), ("Machine learning", "skill"), ("3 years experience", "experience")]
        reqs = {label: connection.execute("INSERT INTO requirements(job_id,label,kind,mandatory) VALUES(?,?,?,1)", (job, label, kind)).lastrowid for label, kind in labels}
        run = connection.execute("INSERT INTO match_runs(job_id,requirements_version,trace_json,owner_user_id) VALUES(?,1,'{}',?)", (job, owner)).lastrowid
        candidates = []
        for rank, passages, statuses in (
            (1, ["At work, built Python data tools.", "At work, used SQL for reporting.", "Built a machine learning project."], ["matched", "matched", "matched", "no_evidence"]),
            (2, ["Built Python tools.", "Used SQL.", "No machine learning experience."], ["matched", "matched", "no_evidence", "no_evidence"]),
            (3, ["Built Python data tools.", "Used SQL at work.", "Built a machine learning project.", "4 years of experience in analytics."], ["matched"] * 4),
        ):
            candidate = connection.execute("INSERT INTO candidates(source_type,checksum,owner_user_id) VALUES('txt',?,?)", (f"capstone-{rank}", owner)).lastrowid
            source = "\n".join(passages)
            document = connection.execute("INSERT INTO documents(candidate_id,filename,text) VALUES(?,'panel.txt',?)", (candidate, source)).lastrowid
            spans = [connection.execute("INSERT INTO spans(document_id,candidate_id,start_offset,end_offset,text) VALUES(?,?,?,?,?)",
                       (document, candidate, source.index(passage), source.index(passage) + len(passage), passage)).lastrowid for passage in passages]
            assessments = []
            for index, (label, kind) in enumerate(labels):
                matched = statuses[index] == "matched"
                assessments.append({"requirement_id": reqs[label], "label": label, "kind": kind, "mandatory": True,
                                    "status": statuses[index], "span_id": spans[index] if matched else None,
                                    "quote": ("machine learning" if index == 2 else label) if matched and index < 3 else "4 years of experience" if matched else None,
                                    "reason": "Saved evidence mention" if matched else "No explicit support"})
            connection.execute("""INSERT INTO results(run_id,candidate_id,rank,match_index,mandatory_status,score_json,assessments_json,trace_json)
                VALUES(?,?,?,?,?,'{}',?,'{}')""", (run, candidate, rank, 85-rank*5,
                "satisfied" if rank == 3 else "incomplete", json.dumps(assessments)))
            candidates.append(candidate)
    return client, csrf, run, candidates, spans


def _ask(client, csrf, conversation, question):
    response = client.post(f"/api/chat/conversations/{conversation}/messages", headers={"X-CSRF-Token": csrf}, json={"question": question})
    assert response.status_code == 200, response.text
    return response.json()


def test_five_capstone_questions_use_saved_results_and_owned_evidence(tmp_path, monkeypatch):
    client, csrf, run, candidates, _ = _fixture(tmp_path, monkeypatch)
    run_chat = client.post("/api/chat/conversations", headers={"X-CSRF-Token": csrf}, json={"scope": "run", "run_id": run}).json()["id"]
    candidate_chat = client.post("/api/chat/conversations", headers={"X-CSRF-Token": csrf}, json={"scope": "candidate", "run_id": run, "candidate_id": candidates[0]}).json()["id"]
    corpus_chat = client.post("/api/chat/conversations", headers={"X-CSRF-Token": csrf}, json={"scope": "corpus"}).json()["id"]
    no_role = _ask(client, csrf, corpus_chat, QUESTIONS[0])
    assert "Select a saved match run" in no_role["content"] and no_role["citations"] == []

    ranked = _ask(client, csrf, run_chat, QUESTIONS[0])
    assert "top ranked of 3 analyzed" in ranked["content"]
    assert ranked["content"].index("#1") < ranked["content"].index("#2") < ranked["content"].index("#3")
    assert "match index" in ranked["content"] and "mandatory evidence" in ranked["content"]
    assert [item["candidate_id"] for item in ranked["citations"]] == candidates
    assert [item["candidate_name"] for item in ranked["citations"]] == [f"Candidate {item}" for item in candidates]

    conjunction = _ask(client, csrf, run_chat, QUESTIONS[1])
    cited = {item["candidate_id"] for item in conjunction["citations"]}
    assert cited == {candidates[0], candidates[2]}
    for candidate in cited:
        assert {item["requirement"] for item in conjunction["citations"] if item["candidate_id"] == candidate} == {"Python", "SQL", "Machine learning"}
    assert "not verified experience" in conjunction["content"]

    monkeypatch.setattr(chat_service, "parse_job", lambda *_: (_ for _ in ()).throw(AssertionError("JD parser misroute")))
    gaps = _ask(client, csrf, candidate_chat, QUESTIONS[2])
    assert "Required skills: none flagged" in gaps["content"]
    assert "Required experience and qualifications: 3 years experience" in gaps["content"]
    assert "No evidence" in gaps["content"] and "does not mean the candidate lacks" in gaps["content"]

    why = _ask(client, csrf, candidate_chat, QUESTIONS[3])
    assert "80.0" in why["content"] and "3 years experience" in why["content"]
    assert {item["requirement"] for item in why["citations"]} == {"Python", "SQL", "Machine learning"}

    mandatory = _ask(client, csrf, run_chat, QUESTIONS[4])
    assert "1 of 3 analyzed" in mandatory["content"]
    assert [item["candidate_id"] for item in mandatory["citations"]] == [candidates[2]]
    for answer in (ranked, conjunction, why, mandatory):
        for citation in answer["citations"]:
            source = client.get(f"/api/candidates/{citation['candidate_id']}/source").json()
            span = next(item for item in source["spans"] if item["id"] == citation["span_id"])
            assert citation["quote"] in source["text"][span["start_offset"]:span["end_offset"]]


def test_mandatory_zero_of_analyzed_does_not_claim_corpus_exhaustion(tmp_path, monkeypatch):
    client, csrf, run, candidates, _ = _fixture(tmp_path, monkeypatch)
    with db.connect() as connection:
        connection.execute("UPDATE results SET mandatory_status='incomplete' WHERE run_id=?", (run,))
    conversation = client.post("/api/chat/conversations", headers={"X-CSRF-Token": csrf}, json={"scope": "run", "run_id": run}).json()["id"]
    answer = _ask(client, csrf, conversation, QUESTIONS[4])
    assert "0 of 3 analyzed" in answer["content"] and "elsewhere in the corpus" in answer["content"]
    assert answer["citations"] == []
