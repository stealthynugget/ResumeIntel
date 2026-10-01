import json
import csv
import logging
import threading
import uuid
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from io import BytesIO
from pydantic import BaseModel, Field

from .db import connect, init_db, interrupt_running_imports
from .import_jobs import create_job as create_import_job, enqueue, job_status
from .ingest import docx_text, embed, import_candidate, pdf_text
from .llm_review import ReviewError, ReviewNotFound, ReviewUnavailable, public_status, probe_gateway, review_candidate, fallback_review
from .matching import parse_job, run_match
from .findings_pdf import render_findings_pdf
from . import auth
from . import chat
from .demo_roles import all_roles
from .chat_service import Context as ChatContext, service as chat_service, validate_context

ROOT = Path(__file__).resolve().parents[1]

app = FastAPI(title="Resume Intelligence API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def startup():
    init_db()
    interrupt_running_imports()
    def warm_search():
        try:
            embed(["resume search warmup"])
            from .matching import _matrix
            with connect() as db:
                _matrix(db)
        except Exception:
            logging.exception("Search warmup failed")
    threading.Thread(target=warm_search, daemon=True, name="search-warmup").start()


class JobIn(BaseModel):
    text: str = Field(min_length=30)


class RequirementIn(BaseModel):
    label: str = Field(min_length=1, max_length=160)
    kind: Literal["skill", "experience", "education", "certification", "other"] = "skill"
    mandatory: bool = True


class RequirementsIn(BaseModel):
    requirements: list[RequirementIn] = Field(min_length=1, max_length=30)


class CredentialsIn(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1)


class SignupIn(CredentialsIn):
    display_name: str = Field(min_length=1, max_length=100)


class ProfileIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)


class PasswordIn(BaseModel):
    current_password: str
    new_password: str


class UserUpdateIn(BaseModel):
    role: Literal["admin", "recruiter"] | None = None
    active: bool | None = None


class AiPreferenceIn(BaseModel):
    enabled: bool


class ConversationIn(BaseModel):
    scope: Literal["general", "corpus", "run", "candidate"] = "candidate"
    run_id: int | None = None
    candidate_id: int | None = None


class ChatQuestionIn(BaseModel):
    question: str = Field(min_length=3, max_length=800)
    context: ChatContext | None = None


@app.post("/api/auth/signup", status_code=201)
def signup(body: SignupIn, request: Request, response: Response):
    if "@" not in body.email:
        raise HTTPException(422, "Enter a valid email")
    return auth.signup(request, response, body.email, body.display_name, body.password)


@app.post("/api/auth/signin")
def signin(body: CredentialsIn, request: Request, response: Response):
    return auth.signin(request, response, body.email, body.password)


@app.get("/api/auth/me")
def me(user=Depends(auth.require_user)):
    return auth.public_user(user, user["csrf_token"])


@app.post("/api/auth/signout")
def signout(request: Request, response: Response, user=Depends(auth.require_user)):
    return auth.signout(request, response, user)


@app.patch("/api/auth/me")
def update_profile(body: ProfileIn, user=Depends(auth.require_user)):
    with connect() as db:
        db.execute("UPDATE users SET display_name=? WHERE id=?", (body.display_name.strip(), user["id"]))
        row = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    return auth.public_user(row, user["csrf_token"])


@app.post("/api/auth/change-password")
def update_password(body: PasswordIn, request: Request, user=Depends(auth.require_user)):
    return auth.change_password(user, body.current_password, body.new_password, request.cookies[auth.COOKIE])


@app.get("/api/admin/users")
def list_users(user=Depends(auth.require_admin)):
    with connect() as db:
        return [auth.public_user(row) for row in db.execute("SELECT * FROM users ORDER BY id")]


@app.patch("/api/admin/users/{target_id}")
def update_user(target_id: int, body: UserUpdateIn, user=Depends(auth.require_admin)):
    with connect() as db:
        target = db.execute("SELECT * FROM users WHERE id=?", (target_id,)).fetchone()
        if not target:
            raise HTTPException(404, "User not found")
        role = body.role if body.role is not None else target["role"]
        active = body.active if body.active is not None else bool(target["active"])
        if target["role"] == "admin" and target["active"] and (role != "admin" or not active):
            count = db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
            if count <= 1:
                raise HTTPException(409, "The last active admin cannot be disabled or demoted")
        db.execute("UPDATE users SET role=?,active=? WHERE id=?", (role, int(active), target_id))
        if not active:
            db.execute("DELETE FROM sessions WHERE user_id=?", (target_id,))
        row = db.execute("SELECT * FROM users WHERE id=?", (target_id,)).fetchone()
    return auth.public_user(row)


def job_payload(db, job_id, user=None):
    job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        raise HTTPException(404, "Job not found")
    if user is not None:
        auth.check_owner(user, job["owner_user_id"], "Job")
    reqs = [dict(row) for row in db.execute("SELECT id,label,kind,mandatory FROM requirements WHERE job_id=? ORDER BY id", (job_id,))]
    for req in reqs:
        req["mandatory"] = bool(req["mandatory"])
    return {"id": job["id"], "title": job["title"], "text": job["text"],
            "requirements_version": job["requirements_version"], "requirements": reqs}


def create_job(text, owner_user_id=None):
    title, requirements = parse_job(text)
    with connect() as db:
        cur = db.execute("INSERT INTO jobs(title,text,owner_user_id) VALUES(?,?,?)", (title, text, owner_user_id))
        for req in requirements:
            db.execute("INSERT INTO requirements(job_id,label,kind,mandatory) VALUES(?,?,?,?)",
                       (cur.lastrowid, req["label"], req["kind"], int(req["mandatory"])))
        return job_payload(db, cur.lastrowid)


def _check_run(db, run_id, user):
    row = db.execute("SELECT owner_user_id FROM match_runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Match run not found")
    auth.check_owner(user, row["owner_user_id"], "Match run")


@app.get("/api/dashboard")
def dashboard(user=Depends(auth.require_user)):
    visible = "(owner_user_id=? OR (owner_user_id IS NULL AND source_type='csv'))"
    where, args = ("1=1", ()) if user["role"] == "admin" else (visible, (user["id"],))
    with connect() as db:
        accessible = db.execute(f"SELECT COUNT(*) FROM candidates WHERE {where}", args).fetchone()[0]
        corpus = accessible
        types = [dict(row) for row in db.execute(f"SELECT source_type AS label,COUNT(*) AS count FROM candidates WHERE {where} GROUP BY source_type ORDER BY count DESC", args)]
        categories = [dict(row) for row in db.execute(f"SELECT COALESCE(category,'Uploaded') AS label,COUNT(*) AS count FROM candidates WHERE {where} GROUP BY category ORDER BY count DESC", args)]
        scope = "1=1" if user["role"] == "admin" else "owner_user_id=?"
        run_scope = "1=1" if user["role"] == "admin" else "mr.owner_user_id=?"
        owner_args = () if user["role"] == "admin" else (user["id"],)
        imports = [dict(row) for row in db.execute(f"""SELECT id,filename,status,total_rows,processed_rows,imported,duplicate,invalid,failed,
            duration_seconds,started_at FROM import_jobs WHERE {scope} ORDER BY id DESC LIMIT 5""", owner_args)]
        runs = [dict(row) for row in db.execute(f"""SELECT mr.id,mr.created_at,j.title,COUNT(r.candidate_id) AS analyzed
            FROM match_runs mr JOIN jobs j ON j.id=mr.job_id LEFT JOIN results r ON r.run_id=mr.id
            WHERE {run_scope} GROUP BY mr.id ORDER BY mr.id DESC LIMIT 5""", owner_args)]
    benchmarks = json.loads((ROOT / "evaluation" / "benchmark_full.json").read_text(encoding="utf-8"))
    audit = json.loads((ROOT / "evaluation" / "claim_audit_results.json").read_text(encoding="utf-8"))
    return {"corpus_size": corpus, "accessible_size": accessible,
            "corpus_scope": "all indexed candidates" if user["role"] == "admin" else "candidates accessible to you",
            "source_types": types, "categories": categories,
            "recent_imports": imports, "recent_runs": runs,
            "highlights": {"warm_search_medians_ms": [item["warm_median_ms"] for item in benchmarks],
                           "citation_integrity_failures": len(audit["quote_integrity_failures"]),
                           "evaluation_label": "Exploratory implementer-judged evaluation"}}


@app.get("/api/evaluation")
def evaluation(user=Depends(auth.require_user)):
    folder = ROOT / "evaluation"
    scope = "1=1" if user["role"] == "admin" else "(c.owner_user_id=? OR (c.owner_user_id IS NULL AND c.source_type='csv'))"
    args = () if user["role"] == "admin" else (user["id"],)
    with connect() as db:
        current_candidates = db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        current_spans = db.execute("SELECT COUNT(*) FROM spans").fetchone()[0]
        current_fts = db.execute("SELECT COUNT(*) FROM spans_fts").fetchone()[0]
        repeat = db.execute("SELECT id,imported,duplicate,invalid,failed,duration_seconds FROM import_jobs ORDER BY id LIMIT 1 OFFSET 1").fetchone()
        categories = [dict(row) for row in db.execute(f"""SELECT COALESCE(c.category,'Uploaded') AS category,
            COUNT(DISTINCT c.id) AS candidates, COUNT(s.id) AS indexed_spans,
            COUNT(DISTINCT CASE WHEN s.id IS NOT NULL THEN c.id END) AS candidates_with_spans
            FROM candidates c LEFT JOIN spans s ON s.candidate_id=c.id
            WHERE {scope} GROUP BY COALESCE(c.category,'Uploaded') ORDER BY candidates DESC,category""", args)]
    smoke = json.loads((folder / "smoke_results.json").read_text(encoding="utf-8"))
    with (folder / "gap_status_audit.csv").open(encoding="utf-8", newline="") as file:
        gap_rows = list(csv.DictReader(file))
    first_import = json.loads((folder / "import_verification.json").read_text(encoding="utf-8"))
    import_outcomes = {key: first_import[key] for key in
                       ("source_rows", "outcomes", "exact_source_documents", "bad_offsets",
                        "import_seconds", "peak_process_rss_mb")}
    import_outcomes["verification_snapshot"] = {
        "candidates": first_import["candidates"], "spans": first_import["spans"],
        "fts_rows": first_import["fts_rows"],
        "label": "Post-benchmark import verification; not the ranking/latency denominator"}
    return {"metrics": json.loads((folder / "metrics.json").read_text(encoding="utf-8")),
            "benchmarks": json.loads((folder / "benchmark_full.json").read_text(encoding="utf-8")),
            "citation_audit": json.loads((folder / "claim_audit_results.json").read_text(encoding="utf-8")),
            "import_verification": import_outcomes,
            "snapshot": {"benchmark_candidates": smoke["corpus"]["candidates"],
                         "benchmark_spans": smoke["corpus"]["spans"],
                         "current_candidates": current_candidates, "current_spans": current_spans,
                         "current_fts_rows": current_fts, "current_scope": "admin-visible database"},
            "source_link_checks": {"checked": sum(item["citations_checked"] for item in smoke["runs"]),
                                   "failures": sum(len(item["invalid_citations"]) for item in smoke["runs"])},
            "repeat_import": {**dict(repeat), "source": "saved second import job"} if repeat else None,
            "gap_status_audit": {"reviewed": len(gap_rows),
                                 "possible_false_negatives": sum(row["manual_judgment"] == "possible_false_negative" for row in gap_rows),
                                 "observations": [{"candidate_id": int(row["candidate_id"]),
                                                   "requirement": row["requirement"],
                                                   "saved_status": row["saved_status"],
                                                   "judgment": row["manual_judgment"],
                                                   "observation": row["manual_observation"]} for row in gap_rows]},
            "functional_validation": {"five_questions": json.loads((folder / "capstone_browser_smoke_results.json").read_text(encoding="utf-8"))["fiveExamples"],
                                      "gateway_citation_checked": json.loads((folder / "gateway_chat_live_results.json").read_text(encoding="utf-8"))["validated_citations"],
                                      "review_fallback": json.loads((folder / "full_browser_smoke_results.json").read_text(encoding="utf-8"))["reviewFallback"],
                                      "chat_fallback": json.loads((folder / "full_browser_smoke_results.json").read_text(encoding="utf-8"))["chatFallback"],
                                      "labeled_question_benchmark": None},
            "category_coverage": categories,
            "category_scope": "all indexed candidates" if user["role"] == "admin" else "candidates accessible to you",
            "category_proxy": json.loads((folder / "category_proxy_results.json").read_text(encoding="utf-8")),
            "judgment_method": "18-candidate pools per role, selected from keyword and hybrid results plus nonmatches; graded by the implementer after viewing output.",
            "disclosure": "Exploratory relevance checks only; not hiring accuracy or fairness validation."}


@app.get("/api/demo-roles")
def demo_roles(user=Depends(auth.require_user)):
    return all_roles()


@app.get("/api/match-runs")
def list_runs(user=Depends(auth.require_user)):
    with connect() as db:
        scope = "1=1" if user["role"] == "admin" else "mr.owner_user_id=?"
        args = () if user["role"] == "admin" else (user["id"],)
        return [dict(row) for row in db.execute(f"""SELECT mr.id,mr.created_at,j.title,COUNT(r.candidate_id) AS candidates
            FROM match_runs mr JOIN jobs j ON j.id=mr.job_id LEFT JOIN results r ON r.run_id=mr.id
            WHERE {scope} GROUP BY mr.id ORDER BY mr.id DESC LIMIT 50""", args)]


def candidate_display(name, external_id, candidate_id):
    return name.strip() if name and name.strip() else f"Candidate {external_id or candidate_id}"


def _conversation(db, conversation_id, user):
    row = db.execute("""SELECT cc.*,j.title,c.external_id,c.name,c.category FROM assistant_conversations cc
        LEFT JOIN match_runs mr ON mr.id=cc.run_id LEFT JOIN jobs j ON j.id=mr.job_id
        LEFT JOIN candidates c ON c.id=cc.candidate_id WHERE cc.id=?""", (conversation_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Conversation not found")
    auth.check_owner(user, row["owner_user_id"], "Conversation")
    return row


@app.get("/api/chat/conversations")
def list_conversations(user=Depends(auth.require_user)):
    with connect() as db:
        scope = "1=1" if user["role"] == "admin" else "cc.owner_user_id=?"
        args = () if user["role"] == "admin" else (user["id"],)
        rows = db.execute(f"""SELECT cc.id,cc.scope,cc.run_id,cc.candidate_id,cc.updated_at,j.title,
            c.name,c.external_id,c.category FROM assistant_conversations cc
            LEFT JOIN match_runs mr ON mr.id=cc.run_id LEFT JOIN jobs j ON j.id=mr.job_id
            LEFT JOIN candidates c ON c.id=cc.candidate_id WHERE {scope} ORDER BY cc.updated_at DESC LIMIT 50""", args).fetchall()
        return [{"id": row["id"], "scope": row["scope"], "run_id": row["run_id"], "candidate_id": row["candidate_id"],
                 "updated_at": row["updated_at"], "title": row["title"] or row["scope"].title(),
                 "candidate_name": candidate_display(row["name"], row["external_id"], row["candidate_id"]) if row["candidate_id"] else None,
                 "candidate_category": row["category"]} for row in rows]


@app.post("/api/chat/conversations", status_code=201)
def create_conversation(body: ConversationIn, user=Depends(auth.require_user)):
    with connect() as db:
        context = ChatContext(scope=body.scope, run_id=body.run_id, candidate_id=body.candidate_id)
        validate_context(db, user, context)
        cur = db.execute("INSERT INTO assistant_conversations(owner_user_id,scope,run_id,candidate_id) VALUES(?,?,?,?)",
                         (user["id"], body.scope, body.run_id, body.candidate_id))
        return {"id": cur.lastrowid, "scope": body.scope, "run_id": body.run_id, "candidate_id": body.candidate_id}


@app.get("/api/chat/conversations/{conversation_id}")
def get_conversation(conversation_id: int, user=Depends(auth.require_user)):
    with connect() as db:
        row = _conversation(db, conversation_id, user)
        messages = [dict(item) | {"citations": json.loads(item["citations_json"]),
                                 "suggested_actions": json.loads(item["suggested_actions_json"])} for item in db.execute(
            "SELECT * FROM assistant_messages WHERE conversation_id=? ORDER BY id", (conversation_id,))]
        for message in messages:
            message.pop("citations_json")
            message.pop("suggested_actions_json")
            for index, citation in enumerate(message["citations"]):
                citation.setdefault("candidate_id", row["candidate_id"])
                citation.setdefault("run_id", row["run_id"])
                citation.setdefault("deep_link", f"/chat?conversation={conversation_id}&message={message['id']}&citation={index}")
                if citation.get("candidate_id") and "candidate_name" not in citation:
                    named = db.execute("SELECT name,external_id FROM candidates WHERE id=?", (citation["candidate_id"],)).fetchone()
                    if named:
                        citation["candidate_name"] = candidate_display(named["name"], named["external_id"], citation["candidate_id"])
        return {"id": row["id"], "scope": row["scope"], "run_id": row["run_id"], "candidate_id": row["candidate_id"],
                "title": row["title"] or row["scope"].title(),
                "candidate_name": candidate_display(row["name"], row["external_id"], row["candidate_id"]) if row["candidate_id"] else None,
                "candidate_category": row["category"],
                "messages": messages}


@app.post("/api/chat/conversations/{conversation_id}/messages")
def post_chat_message(conversation_id: int, body: ChatQuestionIn, user=Depends(auth.require_user)):
    with connect() as db:
        conversation = _conversation(db, conversation_id, user)
        context = body.context or ChatContext(scope=conversation["scope"], run_id=conversation["run_id"],
                                               candidate_id=conversation["candidate_id"])
    answer = chat_service.respond(user, conversation_id, body.question.strip(), context)
    with connect() as db:
        _conversation(db, conversation_id, user)
        db.execute("INSERT INTO assistant_messages(conversation_id,role,content) VALUES(?,'user',?)",
                   (conversation_id, body.question.strip()))
        cur = db.execute("""INSERT INTO assistant_messages(conversation_id,role,content,citations_json,response_kind,suggested_actions_json)
            VALUES(?,'assistant',?,?,?,?)""", (conversation_id, answer["text"], '[]', answer["response_type"],
                                                json.dumps(answer["suggested_actions"])))
        message_id = cur.lastrowid
        citations = []
        for index, item in enumerate(answer["citations"]):
            named = db.execute("SELECT name,external_id FROM candidates WHERE id=?", (item["candidate_id"],)).fetchone() if item.get("candidate_id") else None
            citations.append(item | {"deep_link": f"/chat?conversation={conversation_id}&message={message_id}&citation={index}",
                                     "candidate_name": candidate_display(named["name"], named["external_id"], item["candidate_id"]) if named else None})
        db.execute("UPDATE assistant_messages SET citations_json=? WHERE id=?", (json.dumps(citations), message_id))
        db.execute("UPDATE assistant_conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (conversation_id,))
        return {"id": message_id, "role": "assistant", "content": answer["text"], "text": answer["text"],
                "citations": citations, "response_kind": answer["response_type"],
                "response_type": answer["response_type"], "suggested_actions": answer["suggested_actions"]}


@app.get("/api/health")
def health(user=Depends(auth.require_user)):
    with connect() as db:
        if user["role"] == "admin":
            count = db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
            spans = db.execute("SELECT COUNT(*) FROM spans").fetchone()[0]
        else:
            count = db.execute("SELECT COUNT(*) FROM candidates WHERE owner_user_id=? OR (owner_user_id IS NULL AND source_type='csv')", (user["id"],)).fetchone()[0]
            spans = db.execute("""SELECT COUNT(*) FROM spans s JOIN candidates c ON c.id=s.candidate_id
                WHERE c.owner_user_id=? OR (c.owner_user_id IS NULL AND c.source_type='csv')""", (user["id"],)).fetchone()[0]
    return {"status": "ok", "candidates": count, "spans": spans}


@app.get("/api/ai/status")
def ai_status(user=Depends(auth.require_user)):
    return public_status() | {"enabled": bool(user["ai_enabled"])}


@app.patch("/api/ai/preference")
def ai_preference(body: AiPreferenceIn, user=Depends(auth.require_user)):
    with connect() as db:
        db.execute("UPDATE users SET ai_enabled=? WHERE id=?", (int(body.enabled), user["id"]))
    return public_status() | {"enabled": body.enabled}


@app.post("/api/ai/probe")
def ai_probe(user=Depends(auth.require_user)):
    if not user["ai_enabled"]:
        raise HTTPException(409, "Turn on the AI gateway to send a test request")
    try:
        return probe_gateway()
    except ReviewUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/resumes/import")
async def import_resumes(file: UploadFile = File(...), limit: int | None = Query(default=None, ge=1), user=Depends(auth.require_user)):
    filename = file.filename or "upload"
    max_size = 70_000_000 if filename.lower().endswith(".csv") else 30_000_000
    if filename.lower().endswith(".csv"):
        target_dir = Path(__file__).resolve().parents[1] / "data" / "imports"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{uuid.uuid4().hex}.csv"
        size = 0
        try:
            with target.open("wb") as output:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_size:
                        raise HTTPException(413, "CSV upload exceeds 70 MB")
                    output.write(chunk)
            job_id = create_import_job(target, filename=filename, limit=limit, owner_user_id=user["id"])
            enqueue(job_id)
            return JSONResponse(job_status(job_id), status_code=202)
        except Exception:
            target.unlink(missing_ok=True)
            raise
    data = await file.read(max_size + 1)
    if len(data) > max_size:
        raise HTTPException(413, f"Upload exceeds {max_size // 1_000_000} MB")
    try:
        if filename.lower().endswith(".pdf"):
            text = pdf_text(data)
        elif filename.lower().endswith(".docx"):
            text = docx_text(data)
        elif filename.lower().endswith(".txt"):
            text = data.decode("utf-8-sig")
        else:
            raise ValueError("Upload a CSV, PDF, DOCX, or TXT file")
        cid, created = import_candidate(text, filename=filename, source_type=filename.rsplit(".", 1)[-1], owner_user_id=user["id"])
        if not created:
            with connect() as db:
                row = db.execute("SELECT owner_user_id,source_type FROM candidates WHERE id=?", (cid,)).fetchone()
                if row["owner_user_id"] != user["id"] and not (row["owner_user_id"] is None and row["source_type"] == "csv"):
                    return {"imported": 0, "skipped": 1, "failed": 0, "candidate_id": None}
        return {"imported": int(created), "skipped": int(not created), "failed": 0, "candidate_id": cid}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/resumes/import-jobs/latest")
def latest_import_job(user=Depends(auth.require_user)):
    with connect() as db:
        row = db.execute("SELECT id FROM import_jobs WHERE owner_user_id=? ORDER BY id DESC LIMIT 1", (user["id"],)).fetchone()
    return job_status(row["id"]) if row else None


@app.get("/api/resumes/import-jobs/{job_id}")
def get_import_job(job_id: int, user=Depends(auth.require_user)):
    with connect() as db:
        row = db.execute("SELECT owner_user_id FROM import_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Import job not found")
        auth.check_owner(user, row["owner_user_id"], "Import job")
    try:
        return job_status(job_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/resumes/import-jobs/{job_id}/retry")
def retry_import_job(job_id: int, user=Depends(auth.require_user)):
    with connect() as db:
        row = db.execute("SELECT status,source_path FROM import_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Import job not found")
        owner = db.execute("SELECT owner_user_id FROM import_jobs WHERE id=?", (job_id,)).fetchone()[0]
        auth.check_owner(user, owner, "Import job")
        if row["status"] not in {"failed", "interrupted", "completed_with_errors"}:
            raise HTTPException(409, "Only interrupted or failed imports can be retried")
        if not Path(row["source_path"]).is_file():
            raise HTTPException(410, "Saved upload is unavailable; upload the CSV again")
        db.execute("UPDATE import_jobs SET status='queued',error=NULL WHERE id=?", (job_id,))
    enqueue(job_id)
    return JSONResponse(job_status(job_id), status_code=202)


@app.post("/api/jobs")
def post_job(body: JobIn, user=Depends(auth.require_user)):
    return create_job(body.text, user["id"])


@app.post("/api/jobs/upload")
async def upload_job(file: UploadFile = File(...), user=Depends(auth.require_user)):
    data = await file.read()
    if len(data) > 10_000_000:
        raise HTTPException(413, "Upload exceeds 10 MB")
    try:
        if (file.filename or "").lower().endswith(".pdf"):
            text = pdf_text(data)
        elif (file.filename or "").lower().endswith(".docx"):
            text = docx_text(data)
        elif (file.filename or "").lower().endswith(".txt"):
            text = data.decode("utf-8-sig")
        else:
            raise ValueError("Upload a PDF, DOCX, or TXT job description")
        if len(text.strip()) < 30:
            raise ValueError("Job description has too little extractable text")
        return create_job(text, user["id"])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int, user=Depends(auth.require_user)):
    with connect() as db:
        return job_payload(db, job_id, user)


@app.patch("/api/jobs/{job_id}/requirements")
def patch_requirements(job_id: int, body: RequirementsIn, user=Depends(auth.require_user)):
    with connect() as db:
        job_payload(db, job_id, user)
        db.execute("DELETE FROM requirements WHERE job_id=?", (job_id,))
        for req in body.requirements:
            db.execute("INSERT INTO requirements(job_id,label,kind,mandatory) VALUES(?,?,?,?)",
                       (job_id, req.label.strip(), req.kind, int(req.mandatory)))
        db.execute("UPDATE jobs SET requirements_version=requirements_version+1 WHERE id=?", (job_id,))
        return job_payload(db, job_id)


@app.post("/api/jobs/{job_id}/matches")
def post_matches(job_id: int, user=Depends(auth.require_user)):
    with connect() as db:
        job_payload(db, job_id, user)
    try:
        run_id = run_match(job_id, owner_user_id=user["id"], is_admin=user["role"] == "admin")
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return get_run(run_id, user)


@app.get("/api/match-runs/{run_id}")
def get_run(run_id: int, user=Depends(auth.require_user)):
    with connect() as db:
        run = db.execute("SELECT * FROM match_runs WHERE id=?", (run_id,)).fetchone()
        if not run:
            raise HTTPException(404, "Match run not found")
        auth.check_owner(user, run["owner_user_id"], "Match run")
        rows = db.execute("""SELECT r.*,c.external_id,c.category,c.name
          FROM results r JOIN candidates c ON c.id=r.candidate_id
          WHERE r.run_id=? ORDER BY r.rank LIMIT 10""", (run_id,)).fetchall()
        candidates = []
        for row in rows:
            assessments = json.loads(row["assessments_json"])
            candidates.append({"id": row["candidate_id"], "external_id": row["external_id"],
                               "name": row["name"], "category": row["category"], "rank": row["rank"],
                               "match_index": row["match_index"], "mandatory_status": row["mandatory_status"],
                               "score": json.loads(row["score_json"]),
                               "matched": [x["label"] for x in assessments if x["status"] == "matched"],
                               "gaps": [x["label"] for x in assessments if x["status"] != "matched"]})
        return {"id": run_id, "job_id": run["job_id"], "created_at": run["created_at"],
                "requirements_version": run["requirements_version"], "trace": json.loads(run["trace_json"]),
                "candidates": candidates}


@app.get("/api/match-runs/{run_id}/report.pdf")
def get_run_report(run_id: int, user=Depends(auth.require_user)):
    with connect() as db:
        _check_run(db, run_id, user)
        content = render_findings_pdf(db, run_id)
    return StreamingResponse(BytesIO(content), media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="resumeintel-run-{run_id}-findings.pdf"',
                                      "Cache-Control": "private, no-store"})


@app.get("/api/match-runs/{run_id}/candidates/{candidate_id}")
def get_candidate_detail(run_id: int, candidate_id: int, user=Depends(auth.require_user)):
    with connect() as db:
        _check_run(db, run_id, user)
        row = db.execute("SELECT * FROM results WHERE run_id=? AND candidate_id=?", (run_id, candidate_id)).fetchone()
        if not row:
            raise HTTPException(404, "Result not found")
        return {"candidate_id": candidate_id, "match_index": row["match_index"],
                "mandatory_status": row["mandatory_status"], "score": json.loads(row["score_json"]),
                "assessments": json.loads(row["assessments_json"]), "trace": json.loads(row["trace_json"])}


@app.post("/api/match-runs/{run_id}/candidates/{candidate_id}/ai-review")
def post_ai_review(run_id: int, candidate_id: int, refresh: bool = False, user=Depends(auth.require_user)):
    with connect() as db:
        _check_run(db, run_id, user)
    if not user["ai_enabled"]:
        return fallback_review(run_id, candidate_id)
    try:
        return review_candidate(run_id, candidate_id, force_refresh=refresh)
    except ReviewNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ReviewUnavailable, ReviewError):
        return fallback_review(run_id, candidate_id)


@app.get("/api/candidates/{candidate_id}/source")
def get_candidate_source(candidate_id: int, user=Depends(auth.require_user)):
    with connect() as db:
        candidate = db.execute("SELECT owner_user_id,source_type FROM candidates WHERE id=?", (candidate_id,)).fetchone()
        if not candidate or (user["role"] != "admin" and candidate["owner_user_id"] != user["id"] and not (candidate["owner_user_id"] is None and candidate["source_type"] == "csv")):
            raise HTTPException(404, "Candidate not found")
        doc = db.execute("SELECT * FROM documents WHERE candidate_id=?", (candidate_id,)).fetchone()
        if not doc:
            raise HTTPException(404, "Candidate not found")
        spans = [dict(row) for row in db.execute("SELECT id,start_offset,end_offset,page FROM spans WHERE candidate_id=? ORDER BY id", (candidate_id,))]
        return {"candidate_id": candidate_id, "filename": doc["filename"], "text": doc["text"], "spans": spans}
