"""Resumable, row-accounted CSV imports with bounded embedding batches."""
import csv
import hashlib
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import psutil

from .db import connect
from .ingest import embed, split_spans

BATCH_RESUMES = 24
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="resume-import")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_job(path: Path, filename: str | None = None, limit: int | None = None, owner_user_id: int | None = None) -> int:
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    if not path.is_file():
        raise FileNotFoundError(path)
    with connect() as db:
        cur = db.execute("INSERT INTO import_jobs(source_path,filename,limit_rows,status,owner_user_id) VALUES(?,?,?,'queued',?)",
                         (str(path.resolve()), filename or path.name, limit, owner_user_id))
        return cur.lastrowid


def enqueue(job_id: int):
    _executor.submit(run_job, job_id)


def job_status(job_id: int):
    with connect() as db:
        row = db.execute("SELECT * FROM import_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise ValueError("Import job not found")
        failures = [dict(item) for item in db.execute("""SELECT row_number,status,detail FROM import_job_rows
            WHERE job_id=? AND status IN ('invalid','failed') ORDER BY row_number LIMIT 20""", (job_id,))]
        fields = ("id", "filename", "status", "total_rows", "processed_rows", "imported", "duplicate",
                  "invalid", "failed", "error", "started_at", "finished_at", "duration_seconds", "peak_rss_mb")
        return {key: row[key] for key in fields} | {"failures": failures}


def _reader(path: Path):
    source = path.open(encoding="utf-8-sig", errors="replace", newline="")
    reader = csv.DictReader(source)
    if not reader.fieldnames:
        source.close()
        raise ValueError("CSV has no header")
    text_key = next((field for field in reader.fieldnames if field.lower() in {"resume_str", "resume", "text"}), None)
    if text_key is None:
        source.close()
        raise ValueError("CSV needs a Resume_str, Resume, or text column")
    return source, reader, text_key


def _total_rows(path: Path, limit: int | None):
    source, reader, _ = _reader(path)
    try:
        return sum(1 for ordinal, _ in enumerate(reader, 1) if limit is None or ordinal <= limit)
    finally:
        source.close()


def _record(db, job_id, row_number, status, detail=None, candidate_id=None):
    db.execute("""INSERT INTO import_job_rows(job_id,row_number,status,detail,candidate_id) VALUES(?,?,?,?,?)
        ON CONFLICT(job_id,row_number) DO UPDATE SET status=excluded.status,detail=excluded.detail,
        candidate_id=excluded.candidate_id""", (job_id, row_number, status, detail, candidate_id))


def _refresh_progress(db, job_id, peak_mb):
    counts = {row["status"]: row["n"] for row in db.execute(
        "SELECT status,COUNT(*) n FROM import_job_rows WHERE job_id=? GROUP BY status", (job_id,))}
    db.execute("""UPDATE import_jobs SET processed_rows=?,imported=?,duplicate=?,invalid=?,failed=?,peak_rss_mb=?
        WHERE id=?""", (sum(counts.values()), counts.get("imported", 0), counts.get("duplicate", 0),
                        counts.get("invalid", 0), counts.get("failed", 0), peak_mb, job_id))


def _process_batch(job_id: int, batch: list[tuple[int, dict]], text_key: str, filename: str, peak_mb: float | None):
    with connect() as db:
        owner_user_id = db.execute("SELECT owner_user_id FROM import_jobs WHERE id=?", (job_id,)).fetchone()[0]
        prior = {row["row_number"]: row["status"] for row in db.execute(
            "SELECT row_number,status FROM import_job_rows WHERE job_id=? AND row_number BETWEEN ? AND ?",
            (job_id, batch[0][0], batch[-1][0]))}
        outcomes = []
        accepted = []
        seen_checksums = set()
        seen_ids = set()
        for row_number, row in batch:
            if prior.get(row_number) in {"imported", "duplicate", "invalid"}:
                continue
            value = row.get(text_key)
            text = value if isinstance(value, str) else ""
            if len(text.strip()) < 40:
                outcomes.append((row_number, "invalid", "Resume has fewer than 40 extractable characters", None))
                continue
            # Canonical checksums keep imports compatible with existing rows, while
            # documents and span offsets retain the exact CSV cell text.
            checksum = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
            external_id = (row.get("ID") or "").strip() or None
            existing = db.execute("SELECT id FROM candidates WHERE checksum=?", (checksum,)).fetchone()
            if existing or checksum in seen_checksums:
                outcomes.append((row_number, "duplicate", "Identical resume checksum already indexed", existing["id"] if existing else None))
                continue
            if external_id:
                existing = db.execute("SELECT id,checksum FROM candidates WHERE external_id=?", (external_id,)).fetchone()
                if existing and existing["checksum"] != checksum:
                    outcomes.append((row_number, "failed", "Source ID already belongs to different resume text", existing["id"]))
                    continue
                if existing or external_id in seen_ids:
                    outcomes.append((row_number, "duplicate", "Source ID already indexed", existing["id"] if existing else None))
                    continue
            parts = split_spans(text)
            if not parts:
                outcomes.append((row_number, "invalid", "No searchable text spans", None))
                continue
            seen_checksums.add(checksum)
            if external_id:
                seen_ids.add(external_id)
            accepted.append((row_number, text, external_id, row.get("Category"), checksum, parts))

        # One model call covers all resume spans in this bounded batch.
        all_parts = [part[2] for item in accepted for part in item[5]]
        vectors = embed(all_parts)
        cursor = 0
        for row_number, text, external_id, category, checksum, parts in accepted:
            own_vectors = vectors[cursor:cursor + len(parts)]
            cursor += len(parts)
            try:
                cur = db.execute("INSERT INTO candidates(external_id,category,source_type,checksum,owner_user_id) VALUES(?,?,'csv',?,?)",
                                 (external_id, category, checksum, owner_user_id))
                candidate_id = cur.lastrowid
                cur = db.execute("INSERT INTO documents(candidate_id,filename,text) VALUES(?,?,?)",
                                 (candidate_id, filename, text))
                document_id = cur.lastrowid
                for (start, end, value), vector in zip(parts, own_vectors):
                    db.execute("""INSERT INTO spans(document_id,candidate_id,start_offset,end_offset,text,embedding)
                        VALUES(?,?,?,?,?,?)""", (document_id, candidate_id, start, end, value, vector.tobytes()))
                outcomes.append((row_number, "imported", None, candidate_id))
            except Exception:
                # The whole batch rolls back; retry reprocesses it without duplicate records.
                raise
        for outcome in outcomes:
            _record(db, job_id, *outcome)
        _refresh_progress(db, job_id, peak_mb)


def run_job(job_id: int):
    with connect() as db:
        job = db.execute("SELECT * FROM import_jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise ValueError("Import job not found")
        if job["status"] == "running":
            raise ValueError("Import job is already running")
        path = Path(job["source_path"])
        filename = job["filename"]
        limit = job["limit_rows"]
        db.execute("UPDATE import_jobs SET status='running',error=NULL,started_at=?,finished_at=NULL WHERE id=?",
                   (now(), job_id))
    started = time.perf_counter()
    peak = [0.0]
    stop = threading.Event()

    def monitor():
        process = psutil.Process(os.getpid())
        while not stop.is_set():
            peak[0] = max(peak[0], process.memory_info().rss / 1024**2)
            stop.wait(0.2)

    sampler = threading.Thread(target=monitor, daemon=True)
    sampler.start()
    try:
        total = _total_rows(path, limit)
        with connect() as db:
            db.execute("UPDATE import_jobs SET total_rows=? WHERE id=?", (total, job_id))
        source, reader, text_key = _reader(path)
        try:
            batch = []
            for ordinal, row in enumerate(reader, 1):
                if limit is not None and ordinal > limit:
                    break
                batch.append((ordinal, row))
                if len(batch) >= BATCH_RESUMES:
                    _process_batch(job_id, batch, text_key, filename, round(peak[0], 1))
                    batch = []
            if batch:
                _process_batch(job_id, batch, text_key, filename, round(peak[0], 1))
        finally:
            source.close()
        with connect() as db:
            row = db.execute("SELECT total_rows,processed_rows,failed FROM import_jobs WHERE id=?", (job_id,)).fetchone()
            if row["processed_rows"] != row["total_rows"]:
                raise RuntimeError(f"Only {row['processed_rows']} of {row['total_rows']} rows were accounted for")
            final = "completed_with_errors" if row["failed"] else "completed"
            db.execute("UPDATE import_jobs SET status=?,finished_at=?,duration_seconds=?,peak_rss_mb=? WHERE id=?",
                       (final, now(), round(time.perf_counter() - started, 2), round(peak[0], 1), job_id))
    except Exception as exc:
        with connect() as db:
            db.execute("UPDATE import_jobs SET status='failed',error=?,finished_at=?,duration_seconds=?,peak_rss_mb=? WHERE id=?",
                       (f"{type(exc).__name__}: {exc}", now(), round(time.perf_counter() - started, 2), round(peak[0], 1), job_id))
    finally:
        stop.set()
        sampler.join(timeout=1)
    return job_status(job_id)
