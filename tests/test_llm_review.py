import json

import httpx
import pytest

from backend import db, llm_review


def _result(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "review.db")
    db.init_db()
    with db.connect() as connection:
        candidate_id = connection.execute("""INSERT INTO candidates(external_id,category,source_type,checksum)
            VALUES('source-42','ENGINEERING','csv','review-test')""").lastrowid
        source = "Built Python services. Contact jane@example.com."
        document_id = connection.execute("INSERT INTO documents(candidate_id,filename,text) VALUES(?,?,?)",
                                         (candidate_id, "Resume.csv", source)).lastrowid
        span_id = connection.execute("""INSERT INTO spans(document_id,candidate_id,start_offset,end_offset,text)
            VALUES(?,?,?,?,?)""", (document_id, candidate_id, 0, len(source), source)).lastrowid
        job_id = connection.execute("INSERT INTO jobs(title,text) VALUES('Backend Engineer','Required: Python')").lastrowid
        requirement_id = connection.execute("""INSERT INTO requirements(job_id,label,kind,mandatory)
            VALUES(?,'Python','skill',1)""", (job_id,)).lastrowid
        run_id = connection.execute("""INSERT INTO match_runs(job_id,requirements_version,trace_json)
            VALUES(?,1,'{}')""", (job_id,)).lastrowid
        assessment = {"requirement_id": requirement_id, "label": "Python", "kind": "skill",
                      "mandatory": True, "status": "matched", "span_id": span_id,
                      "quote": "Python", "reason": "Work context supports a mention."}
        connection.execute("""INSERT INTO results(run_id,candidate_id,rank,match_index,mandatory_status,
            score_json,assessments_json,trace_json) VALUES(?,?,1,70,'satisfied','{}',?,'{}')""",
                           (run_id, candidate_id, json.dumps([assessment])))
    return run_id, candidate_id, requirement_id, span_id


def test_gateway_review_uses_validated_source_and_cache(tmp_path, monkeypatch):
    run_id, candidate_id, requirement_id, span_id = _result(tmp_path, monkeypatch)
    monkeypatch.setenv("RESUMEINTEL_LLM_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setenv("RESUMEINTEL_LLM_API_KEY", "test-key")
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "gpt-4o-mini"
        assert payload["response_format"]["type"] == "json_schema"
        assert "jane@example.com" not in payload["messages"][1]["content"]
        content = {"summary": "The saved resume mentions Python work; verify depth in an interview.",
                   "highlights": [{"requirement_id": requirement_id, "span_id": span_id,
                                   "note": "The excerpt mentions Python services."}],
                   "follow_up_questions": ["Which Python services did you build?"]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})

    original_client = httpx.Client
    monkeypatch.setattr(llm_review.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(handler), **kwargs))
    first = llm_review.review_candidate(run_id, candidate_id)
    second = llm_review.review_candidate(run_id, candidate_id)
    assert first["cached"] is False and second["cached"] is True
    assert len(calls) == 1
    assert first["highlights"][0]["quote"] == "Python"
    assert first["affects_ranking"] is False
    assert first["brief"]["counts"] == {"required_supported": 1, "required_total": 1,
                                           "preferred_supported": 0, "preferred_total": 0}
    assert first["brief"]["supported"][0]["span_id"] == span_id
    assert first["brief"]["supported"][0]["excerpt"].startswith("Built Python")
    monkeypatch.setenv("RESUMEINTEL_LLM_BASE_URL", "https://second-gateway.example/v1")
    switched = llm_review.review_candidate(run_id, candidate_id)
    assert switched["cached"] is False and len(calls) == 2


def test_invalid_first_draft_is_retried_and_refresh_bypasses_cache(tmp_path, monkeypatch):
    run_id, candidate_id, requirement_id, span_id = _result(tmp_path, monkeypatch)
    monkeypatch.setenv('RESUMEINTEL_LLM_BASE_URL', 'https://gateway.example/v1')
    monkeypatch.setenv('RESUMEINTEL_LLM_API_KEY', 'test-key')
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        summary = ('The saved resume mentions 99 years of Python experience.' if len(calls) == 1
                   else 'The saved resume mentions Python work; verify depth.')
        draft = {'summary': summary,
                 'highlights': [{'requirement_id': requirement_id, 'span_id': span_id,
                                 'note': 'The excerpt mentions Python services.'}],
                 'follow_up_questions': ['Which Python services did you build?']}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(draft)}}]})
    original_client = httpx.Client
    monkeypatch.setattr(llm_review.httpx, 'Client', lambda **kwargs: original_client(
        transport=httpx.MockTransport(handler), **kwargs))
    first = llm_review.review_candidate(run_id, candidate_id)
    assert first['cached'] is False and len(calls) == 2
    assert 'failed source validation' in calls[1]['messages'][-1]['content']
    assert llm_review.review_candidate(run_id, candidate_id)['cached'] is True
    fresh = llm_review.review_candidate(run_id, candidate_id, force_refresh=True)
    assert fresh['cached'] is False and len(calls) == 3


def test_openai_names_and_gateway_json_fallback_preserve_match(tmp_path, monkeypatch):
    run_id, candidate_id, requirement_id, span_id = _result(tmp_path, monkeypatch)
    monkeypatch.delenv("RESUMEINTEL_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("RESUMEINTEL_LLM_API_KEY", raising=False)
    monkeypatch.delenv("RESUMEINTEL_LLM_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    assert llm_review.public_status()["configured"] is True
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload["response_format"])
        assert "candidate_reference" not in payload["messages"][1]["content"]
        assert "jane@example.com" not in payload["messages"][1]["content"]
        if payload["response_format"] != "json":
            return httpx.Response(422, json={"detail": [{"loc": ["body", "response_format"]}]})
        content = {"summary": "The saved resume mentions Python work; verify depth.",
                   "highlights": [{"requirement_id": requirement_id, "span_id": span_id,
                                   "note": "The excerpt mentions Python services."}],
                   "follow_up_questions": ["Which services were built?"]}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                                                    "message": {"content": json.dumps(content)}}]})

    original_client = httpx.Client
    monkeypatch.setattr(llm_review.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(handler), **kwargs))
    with db.connect() as connection:
        original = dict(connection.execute("SELECT match_index,mandatory_status,assessments_json FROM results WHERE run_id=? AND candidate_id=?",
                                           (run_id, candidate_id)).fetchone())
    first = llm_review.review_candidate(run_id, candidate_id)
    second = llm_review.review_candidate(run_id, candidate_id)
    assert first["response_format"] == "json_mode" and first["cached"] is False
    assert second["cached"] is True and len(calls) == 3
    assert calls[0]["type"] == "json_schema" and calls[1]["type"] == "json_object" and calls[2] == "json"
    with db.connect() as connection:
        unchanged = dict(connection.execute("SELECT match_index,mandatory_status,assessments_json FROM results WHERE run_id=? AND candidate_id=?",
                                            (run_id, candidate_id)).fetchone())
    assert unchanged == original


def test_gateway_cannot_cite_another_span():
    content = json.dumps({"summary": "The saved resume mentions Python.", "highlights": [
        {"requirement_id": 1, "span_id": 999, "note": "Unsupported claim"}],
        "follow_up_questions": []})
    with pytest.raises(llm_review.ReviewError, match="outside"):
        llm_review._validate_review(content, {(1, 4): {"label": "Python", "status": "matched", "quote": "Python"}})
    invented_status = json.dumps({"summary": "A summary", "highlights": [],
                                  "follow_up_questions": [], "match_index": 100})
    with pytest.raises(llm_review.ReviewError):
        llm_review._validate_review(invented_status, {})
    invented_years = json.dumps({"summary": "This candidate has 12 years of production experience.",
                                 "highlights": [], "follow_up_questions": []})
    with pytest.raises(llm_review.ReviewError, match="unsupported"):
        llm_review._validate_review(invented_years, {})


def test_review_can_name_saved_gap_only_as_a_gap():
    allowed = {(1, 4): {'label': 'Python', 'status': 'matched', 'quote': 'Python'}}
    base = {'highlights': [{'requirement_id': 1, 'span_id': 4,
                            'note': 'The excerpt mentions Python services.'}],
            'follow_up_questions': []}
    cautious = base | {'summary': 'The saved resume mentions Python. The saved assessment does not establish SQL.'}
    assert llm_review._validate_review(json.dumps(cautious), allowed, ['SQL'])['summary'] == cautious['summary']
    unsupported = base | {'summary': 'The saved resume mentions Python and SQL.'}
    with pytest.raises(llm_review.ReviewError, match='unsupported evidence'):
        llm_review._validate_review(json.dumps(unsupported), allowed, ['SQL'])


def test_structured_fallback_has_counts_gaps_and_questions(tmp_path, monkeypatch):
    run_id, candidate_id, _, span_id = _result(tmp_path, monkeypatch)
    review = llm_review.fallback_review(run_id, candidate_id)
    assert review["response_kind"] == "fallback"
    assert review["brief"]["mandatory_status"] == "satisfied"
    assert review["brief"]["supported"][0]["span_id"] == span_id
    assert len(review["follow_up_questions"]) >= 1


def test_gateway_outage_has_clear_error(tmp_path, monkeypatch):
    run_id, candidate_id, _, _ = _result(tmp_path, monkeypatch)
    monkeypatch.delenv("RESUMEINTEL_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("RESUMEINTEL_LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    original_client = httpx.Client
    monkeypatch.setattr(llm_review.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(503)), **kwargs))
    with pytest.raises(llm_review.ReviewUnavailable, match="Gateway unavailable \\(HTTP 503\\)"):
        llm_review.review_candidate(run_id, candidate_id)


def test_gateway_is_opt_in(monkeypatch):
    monkeypatch.delenv("RESUMEINTEL_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("RESUMEINTEL_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert llm_review.public_status()["configured"] is False
    with pytest.raises(llm_review.ReviewUnavailable):
        llm_review.review_candidate(1, 1)
