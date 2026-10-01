import json
import re
import threading
from collections import defaultdict

import numpy as np

from .agents import candidate_matching_agent, skill_gap_agent, qualification_agent, explainability_validation_agent
from .db import connect
from .ingest import embed

_index_lock = threading.Lock()
_index_state = None
_index_data = None

SKILLS = {
    "Python": ["python"], "SQL": ["sql", "postgresql", "mysql", "sqlite"],
    "Machine learning": ["machine learning", "ml models", "predictive modeling"],
    "Deep learning": ["deep learning", "neural network", "pytorch", "tensorflow"],
    "Data analysis": ["data analysis", "data analytics", "analytical analysis"],
    "Statistics": ["statistics", "statistical analysis"],
    "Natural language processing": ["natural language processing", "nlp"],
    "AWS": ["aws", "amazon web services"], "Azure": ["azure"],
    "Docker": ["docker", "containerization"], "Kubernetes": ["kubernetes", "k8s"],
    "React": ["react", "reactjs", "react.js"], "TypeScript": ["typescript"],
    "JavaScript": ["javascript", "node.js", "nodejs"], "Java": ["java", "spring boot"],
    "FastAPI": ["fastapi"], "REST APIs": ["rest api", "restful api", "api development"],
    "ETL": ["etl", "data pipeline"], "Spark": ["spark", "pyspark"],
    "Tableau": ["tableau"], "Power BI": ["power bi", "powerbi"],
    "Excel": ["excel", "spreadsheet"], "Recruiting": ["recruiting", "recruitment", "talent acquisition"],
    "Stakeholder management": ["stakeholder management", "stakeholder engagement"],
    "Communication": ["communication", "communicating"],
    "Project management": ["project management", "project manager"],
    "Windows Server": ["windows server", "windows servers"],
    "Active Directory": ["active directory"],
    "VMware": ["vmware", "vsphere", "esxi"],
    "Linux": ["linux", "red hat", "ubuntu"],
    "Network administration": ["network administration", "network administrator", "network infrastructure"],
}
RELATED = {
    "Machine learning": ["deep learning", "neural network", "predictive analytics"],
    "Deep learning": ["machine learning", "neural network"],
    "Data analysis": ["business intelligence", "data visualization"],
    "Natural language processing": ["text mining", "language models"],
    "AWS": ["cloud computing", "azure", "google cloud"],
    "React": ["frontend development", "angular", "vue"],
    "Project management": ["project coordination", "program management"],
}


def contains(text, phrase):
    return bool(re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text, re.I))


def parse_job(text):
    lines = [line.strip(" \t-•*:") for line in text.splitlines() if line.strip()]
    title = lines[0][:100] if lines else "Untitled role"
    found = []
    lower = text.lower()
    line_priorities = []
    section_preferred = False
    for line in lines:
        lowered = line.lower()
        if re.match(r"^(preferred(?: qualifications| skills| requirements)?|nice to have|desirable(?: qualifications| skills)?)\b", lowered):
            section_preferred = True
        elif re.match(r"^(required(?: qualifications| skills| requirements)?|mandatory(?: qualifications| skills)?|must have|minimum qualifications)\b", lowered):
            section_preferred = False
        explicit_preferred = bool(re.search(r"\b(preferred|nice to have|bonus|desirable)\b", line, re.I))
        explicit_required = bool(re.search(r"\b(required|mandatory|must have|essential)\b", line, re.I))
        line_priorities.append((line, not (explicit_preferred or section_preferred) or explicit_required and not explicit_preferred))
    for label, aliases in SKILLS.items():
        positions = [(lower.find(a), a) for a in aliases if contains(text, a)]
        if not positions:
            continue
        first = min(p for p, _ in positions)
        mentions = [mandatory for line, mandatory in line_priorities if any(contains(line, a) for a in aliases)]
        found.append({"label": label, "kind": "skill", "mandatory": any(mentions), "position": first})
    found.sort(key=lambda item: item.pop("position"))
    for match in re.finditer(r"(?:at least\s+|minimum\s+)?(\d+)\+?\s+years?(?: of)?\s+(?:professional\s+|relevant\s+)?experience", text, re.I):
        found.append({"label": f"{match.group(1)} years experience", "kind": "experience", "mandatory": True})
    for match in re.finditer(r"\b(?:bachelor'?s?|master'?s?|ph\.?d\.?|mba)\b(?:\s+degree)?", text, re.I):
        label = match.group(0).strip().title()
        if not any(r["label"] == label for r in found):
            found.append({"label": label, "kind": "education", "mandatory": True})
    for certificate in ("PMP", "CPA", "CFA", "CISSP", "AWS Certified Solutions Architect"):
        if contains(text, certificate):
            found.append({"label": certificate, "kind": "certification", "mandatory": True})
    for line in lines[1:]:
        explicit = re.match(r"^(required|mandatory|preferred|nice to have)\s*:\s*(.{3,100})$", line, re.I)
        if not explicit:
            continue
        label = explicit.group(2).strip().rstrip(".")
        if any(label.lower() == alias.lower() for aliases in SKILLS.values() for alias in aliases):
            continue
        if any(label.lower() == item["label"].lower() for item in found):
            continue
        found.append({"label": label, "kind": "other",
                      "mandatory": explicit.group(1).lower() in {"required", "mandatory"}})
    if not found:
        for line in lines[1:8]:
            if len(line) <= 85:
                found.append({"label": line, "kind": "other", "mandatory": True})
    return title, found[:25]


def _matrix(db):
    global _index_state, _index_data
    version = db.execute("SELECT COUNT(*) AS n, COALESCE(MAX(id),0) AS max_id FROM spans").fetchone()
    state = (str(db.execute("PRAGMA database_list").fetchone()[2]), version["n"], version["max_id"])
    with _index_lock:
        if _index_state != state:
            rows = db.execute("SELECT id,candidate_id,embedding FROM spans WHERE embedding IS NOT NULL ORDER BY id").fetchall()
            if rows:
                vectors = np.stack([np.frombuffer(row["embedding"], dtype=np.float32) for row in rows])
                _index_data = (vectors, np.array([row["candidate_id"] for row in rows]),
                               np.array([row["id"] for row in rows]))
            else:
                _index_data = None
            _index_state = state
        return _index_data


def _lexical_query(requirements, title):
    phrases = []
    for req in requirements:
        if req["kind"] == "experience":
            continue
        phrases.extend(SKILLS.get(req["label"], [req["label"]])[:2])
    if title:
        phrases.append(title)
    phrases = list(dict.fromkeys(p.strip().lower() for p in phrases if len(p.strip()) > 1))[:24]
    return " OR ".join('"' + phrase.replace('"', '') + '"' for phrase in phrases)


def keyword_candidates(db, requirements, title, limit=100):
    query = _lexical_query(requirements, title)
    if not query:
        return []
    rows = db.execute("""SELECT s.candidate_id, bm25(spans_fts) AS weight FROM spans_fts
        JOIN spans s ON s.id=spans_fts.rowid WHERE spans_fts MATCH ? ORDER BY weight LIMIT 3000""", (query,)).fetchall()
    return list(dict.fromkeys(row["candidate_id"] for row in rows))[:limit]


def retrieve(job_text, requirements, title, limit=30, viewer_id=None, is_admin=True):
    query = embed([job_text])[0]
    with connect() as db:
        visible = None if is_admin else {row[0] for row in db.execute(
            "SELECT id FROM candidates WHERE owner_user_id=? OR (owner_user_id IS NULL AND source_type='csv')", (viewer_id,))}
        index = _matrix(db)
        if index is None:
            return []
        vectors, candidate_ids, span_ids = index
        similarities = vectors @ query
        semantic = {}
        for cid, sid, score in zip(candidate_ids, span_ids, similarities):
            cid = int(cid)
            if visible is not None and cid not in visible:
                continue
            if cid not in semantic or score > semantic[cid][0]:
                semantic[cid] = (float(score), int(sid))
        semantic_ranks = sorted(semantic, key=lambda cid: semantic[cid][0], reverse=True)
        lexical = keyword_candidates(db, requirements, title, limit=3000)
        if visible is not None:
            lexical = [cid for cid in lexical if cid in visible][:100]
        else:
            lexical = lexical[:100]
        combined = defaultdict(float)
        for rank, cid in enumerate(semantic_ranks[:100], 1):
            combined[cid] += 1 / (60 + rank)
        for rank, cid in enumerate(lexical, 1):
            combined[cid] += 1 / (60 + rank)
        return [{"candidate_id": cid, "retrieval_score": combined[cid], "semantic_score": semantic[cid][0],
                 "best_span_id": semantic[cid][1]} for cid in sorted(combined, key=combined.get, reverse=True)[:limit]]


def _evidence_for_requirement(req, spans):
    label = req["label"]
    kind = req["kind"]
    aliases = SKILLS.get(label, [label])
    ambiguous = None
    negated = False
    positive = None
    if kind == "experience":
        years = re.search(r"\d+", label)
        if years:
            needed = int(years.group())
            for span in spans:
                for match in re.finditer(r"\b(\d+)\+?\s+years?(?: of)?\s+(?:professional\s+|relevant\s+)?experience\b", span["text"], re.I):
                    state = _mention_state(span["text"], match)
                    if state == "negative":
                        negated = True
                    elif int(match.group(1)) >= needed and state == "positive":
                        return "needs_review", span, match.group(0), "Duration is stated, but the relevant work and depth need human review."
        return "no_evidence", None, None, "Experience duration is negated or not explicitly supported." if negated else "No explicit duration supports this requirement."
    for span in spans:
        for alias in aliases:
            flags = 0 if label == "Excel" and alias == "excel" else re.I
            phrase = "Excel" if label == "Excel" and alias == "excel" else alias
            for match in re.finditer(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", span["text"], flags):
                state = _mention_state(span["text"], match)
                if state == "negative":
                    negated = True
                elif state == "ambiguous":
                    ambiguous = ambiguous or (span, match.group(0))
                else:
                    # A later bare skills-list entry does not override an
                    # explicit limitation elsewhere in the same resume.
                    following = span["text"][match.end():match.end() + 20]
                    if ambiguous and re.match(r"\s*,", following):
                        continue
                    positive = positive or (span, match.group(0))
                    context = re.split(r"[.;\n]", span["text"][max(0, match.start() - 110):match.start()])[-1]
                    if re.search(r"\b(?:built|developed|designed|configured|configuring|managed|managing|administered|administering|used|using|implemented|supported|supporting|maintained|maintaining|planned|planning|analyzed|analyzing)\b", context, re.I):
                        return "matched", span, match.group(0), "Resume describes work involving this requirement; proficiency remains a human judgment."
    if positive:
        return "matched", positive[0], positive[1], "Resume mentions this requirement; proficiency remains a human judgment."
    if ambiguous:
        return "needs_review", ambiguous[0], ambiguous[1], "The resume mentions this in an ambiguous context; review the source."
    if kind == "skill":
        for span in spans:
            for related in RELATED.get(label, []):
                match = re.search(r"(?<!\w)" + re.escape(related) + r"(?!\w)", span["text"], re.I)
                if match and _mention_state(span["text"], match) == "positive":
                    return "partial", span, match.group(0), "Related experience appears in the resume; the exact requirement is not confirmed."
    return "no_evidence", None, None, "Resume text negates this skill." if negated else "No direct evidence found in the resume."


def _mention_state(text, match):
    raw_before = text[max(0, match.start() - 150):match.start()].lower()
    before = re.split(r"[.;,\n]", raw_before)[-1]
    after = re.split(r"[.;,\n]", text[match.end():match.end() + 55])[0].lower()
    if re.search(r"\b(?:no|not|never|without|lacks?|lack of)\b(?:\W+\w+){0,5}\W*$", before):
        return "negative"
    if re.match(r"\W*(?:not|never|lacking|isn't|wasn't)\b", after):
        return "negative"
    if re.search(r"\b(?:learning|studying|interested in|exposure to|familiar with|course in|beginner in)\b(?:\W+\w+){0,4}\W*$", before):
        return "ambiguous"
    if re.search(r"\bfascinated by learning\b.{0,120}$", raw_before):
        return "ambiguous"
    if re.search(r"\b(?:master of science|university|education and training)\b.{0,90}$", raw_before):
        return "ambiguous"
    if re.match(r"\W*(?:beginner|novice|only theoretical|limited|graduate student\b.*exposure to)\b", after):
        return "ambiguous"
    return "positive"


def analyze_candidate(candidate_id, requirements, semantic_score, retrieval_score):
    with connect() as db:
        spans = [dict(row) for row in db.execute("SELECT id,candidate_id,start_offset,end_offset,text FROM spans WHERE candidate_id=? ORDER BY id", (candidate_id,))]
    matching = candidate_matching_agent(requirements, spans, _evidence_for_requirement)
    gaps = skill_gap_agent(matching)
    qualifications = qualification_agent(matching)
    validated, rejected = explainability_validation_agent(candidate_id, matching, spans)
    mandatory = [x for x in validated if x["mandatory"]]
    preferred = [x for x in validated if not x["mandatory"]]
    qualification_kinds = {"experience", "education", "certification"}
    mandatory_core = [x for x in mandatory if x["kind"] not in qualification_kinds]
    preferred_core = [x for x in preferred if x["kind"] not in qualification_kinds]
    coverage = lambda xs: sum(1 if x["status"] == "matched" else 0.5 if x["status"] == "partial" else 0 for x in xs) / len(xs) if xs else 1.0
    mandatory_cov, preferred_cov = coverage(mandatory), coverage(preferred)
    mandatory_core_cov = coverage(mandatory_core)
    preferred_core_cov = coverage(preferred_core)
    qual_cov = coverage(qualifications) if qualifications else 0.0
    semantic_norm = max(0.0, min(1.0, (semantic_score + 1) / 2))
    weights = {"mandatory": 0.5 if mandatory_core else 0.0, "preferred": 0.2 if preferred_core else 0.0,
               "semantic": 0.2, "qualification": 0.1 if qualifications else 0.0}
    total_weight = sum(weights.values())
    score = round(100 * (weights["mandatory"] * mandatory_core_cov + weights["preferred"] * preferred_core_cov +
                         weights["semantic"] * semantic_norm + weights["qualification"] * qual_cov) / total_weight, 1)
    status = "satisfied" if mandatory and all(x["status"] == "matched" for x in mandatory) else "incomplete" if mandatory else "no_mandatory_requirements"
    breakdown = {"mandatory_coverage": round(mandatory_cov, 3), "preferred_coverage": round(preferred_cov, 3),
                 "mandatory_nonqualification_coverage": round(mandatory_core_cov, 3),
                 "semantic_relevance": round(semantic_norm, 3), "qualification_evidence": round(qual_cov, 3),
                 "retrieval_score": round(retrieval_score, 5)}
    trace = {"candidate_matching_agent": {"assessments": len(matching)},
             "skill_gap_agent": {"gaps": gaps},
             "qualification_agent": {"assessments": qualifications},
             "explainability_validation_agent": {"validated": len(validated) - len(rejected), "rejected": rejected}}
    return {"match_index": score, "mandatory_status": status, "score": breakdown, "assessments": validated, "trace": trace}


def run_match(job_id, owner_user_id=None, is_admin=True):
    with connect() as db:
        job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise ValueError("Job not found")
        requirements = [dict(row) for row in db.execute("SELECT * FROM requirements WHERE job_id=? ORDER BY id", (job_id,))]
    hits = retrieve(job["text"] + " " + " ".join(r["label"] for r in requirements), requirements, job["title"], 30,
                    viewer_id=owner_user_id, is_admin=is_admin)
    analyzed = []
    for hit in hits:
        result = analyze_candidate(hit["candidate_id"], requirements, hit["semantic_score"], hit["retrieval_score"])
        analyzed.append((hit, result))
    analyzed.sort(key=lambda pair: pair[1]["match_index"], reverse=True)
    with connect() as db:
        trace = {"retrieval": {"method": "requirement FTS5 + cached MiniLM cosine + reciprocal rank fusion", "candidates": len(hits)},
                 "analysis": {"candidates": len(analyzed), "model": "deterministic evidence matching"}}
        cur = db.execute("INSERT INTO match_runs(job_id,requirements_version,trace_json,owner_user_id) VALUES(?,?,?,?)",
                         (job_id, job["requirements_version"], json.dumps(trace), owner_user_id))
        run_id = cur.lastrowid
        for rank, (hit, result) in enumerate(analyzed, 1):
            db.execute("INSERT INTO results VALUES(?,?,?,?,?,?,?,?)", (run_id, hit["candidate_id"], rank,
                       result["match_index"], result["mandatory_status"], json.dumps(result["score"]),
                       json.dumps(result["assessments"]), json.dumps(result["trace"])))
    return run_id
