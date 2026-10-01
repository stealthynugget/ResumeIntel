import hashlib
import io
import os
import re
import threading
from pathlib import Path

import numpy as np

from .db import connect

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_model = None
_model_lock = threading.Lock()
_encode_lock = threading.Lock()


def model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                cache = Path(__file__).resolve().parents[1] / "data" / "model_cache"
                cache.mkdir(parents=True, exist_ok=True)
                os.environ["HF_HOME"] = str(cache)
                os.environ["HF_HUB_DISABLE_XET"] = "1"
                from sentence_transformers import SentenceTransformer
                _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed(texts):
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    with _encode_lock:
        return np.asarray(model().encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False), dtype=np.float32)


def split_spans(text, target=650):
    # Preserve exact offsets so every displayed excerpt can be opened in its source.
    blocks = list(re.finditer(r"\S(?:.|\n)*?(?=\n\s*\n|\Z)", text))
    if not blocks:
        return []
    output = []
    start = end = None
    for block in blocks:
        if start is None:
            start = block.start()
        if end is not None and block.end() - start > target and end > start:
            output.append((start, end, text[start:end]))
            start = block.start()
        end = block.end()
        while end - start > target * 2:
            cut = text.rfind(" ", start + target // 2, start + target)
            if cut <= start:
                cut = start + target
            output.append((start, cut, text[start:cut]))
            start = cut + (text[cut:cut + 1] == " ")
    if start is not None and end > start:
        output.append((start, end, text[start:end]))
    return [part for part in output if part[2].strip()]


def pdf_text(data):
    import pdfplumber
    pages = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return "\n\f\n".join(pages)


def docx_text(data):
    from docx import Document
    return "\n\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs if p.text.strip())


def import_candidate(text, external_id=None, category=None, filename=None, source_type="csv", name=None, owner_user_id=None):
    if len(text.strip()) < 40:
        raise ValueError("Resume has too little extractable text")
    checksum = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    with connect() as db:
        row = db.execute("SELECT id FROM candidates WHERE checksum=?", (checksum,)).fetchone()
        if row:
            return row["id"], False
        if external_id:
            row = db.execute("SELECT id FROM candidates WHERE external_id=?", (str(external_id),)).fetchone()
            if row:
                return row["id"], False
        cur = db.execute("INSERT INTO candidates(external_id,name,category,source_type,checksum,owner_user_id) VALUES(?,?,?,?,?,?)",
                         (str(external_id) if external_id else None, name, category, source_type, checksum, owner_user_id))
        candidate_id = cur.lastrowid
        cur = db.execute("INSERT INTO documents(candidate_id,filename,text) VALUES(?,?,?)", (candidate_id, filename, text))
        document_id = cur.lastrowid
        parts = split_spans(text)
        vectors = embed([p[2] for p in parts])
        for (start, end, value), vector in zip(parts, vectors):
            page = text.count("\f", 0, start) + 1 if source_type.lower() == "pdf" else None
            db.execute("INSERT INTO spans(document_id,candidate_id,start_offset,end_offset,page,text,embedding) VALUES(?,?,?,?,?,?,?)",
                       (document_id, candidate_id, start, end, page, value, vector.tobytes()))
        return candidate_id, True
