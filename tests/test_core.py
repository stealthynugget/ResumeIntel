from backend.ingest import split_spans
from backend.matching import _evidence_for_requirement, parse_job
from backend.agents import explainability_validation_agent


def test_span_offsets_preserve_exact_source_text():
    text = "Python and SQL projects.\n\nMachine learning delivery."
    spans = split_spans(text, target=25)
    assert spans
    assert all(text[start:end] == value for start, end, value in spans)


def test_parser_separates_preferred_skills():
    _, requirements = parse_job("Data Scientist\nRequired: Python and SQL.\nPreferred: AWS and Tableau.")
    by_label = {item["label"]: item for item in requirements}
    assert by_label["Python"]["mandatory"] is True
    assert by_label["AWS"]["mandatory"] is False


def test_parser_respects_separate_preferred_qualifications_heading():
    _, requirements = parse_job("Backend Engineer\nRequired qualifications\nPython and SQL\nPreferred qualifications\nDocker and AWS")
    by_label = {item["label"]: item for item in requirements}
    assert by_label["Python"]["mandatory"] is True
    assert by_label["Docker"]["mandatory"] is False
    assert by_label["AWS"]["mandatory"] is False


def test_no_evidence_does_not_become_a_match():
    req = {"label": "Python", "kind": "skill"}
    status, span, quote, _ = _evidence_for_requirement(req, [{"id": 1, "text": "Experienced in Java and SQL."}])
    assert status == "no_evidence"
    assert span is None and quote is None


def test_negated_python_is_not_a_match():
    req = {"label": "Python", "kind": "skill"}
    status, span, quote, _ = _evidence_for_requirement(req, [{"id": 1, "text": "No Python experience; worked only in Java."}])
    assert status == "no_evidence" and span is None and quote is None


def test_learning_mention_needs_review():
    req = {"label": "Python", "kind": "skill"}
    status, span, quote, _ = _evidence_for_requirement(req, [{"id": 1, "text": "Interested in learning Python."}])
    assert status == "needs_review" and span["id"] == 1 and quote == "Python"


def test_limited_skill_list_needs_review():
    req = {"label": "Linux", "kind": "skill"}
    spans = [{"id": 1, "text": "Qualifications: Red Hat (limited), Ubuntu (limited)."},
             {"id": 2, "text": "Skills: Netware, Red Hat, Router, Switching."}]
    status, _, _, _ = _evidence_for_requirement(req, spans)
    assert status == "needs_review"


def test_student_exposure_needs_review_but_project_work_matches():
    req = {"label": "Data analysis", "kind": "skill"}
    status, _, _, _ = _evidence_for_requirement(req, [{"id": 1, "text": "MS of Data Analytics graduate student with exposure to data analysis and modeling skills."}])
    assert status == "needs_review"
    req = {"label": "Machine learning", "kind": "skill"}
    spans = [{"id": 1, "text": "Fascinated by learning cutting edge technologies such as Machine Learning."},
             {"id": 2, "text": "Built a project using machine learning predictive models."}]
    status, span, _, _ = _evidence_for_requirement(req, spans)
    assert status == "matched" and span["id"] == 2


def test_degree_mention_does_not_verify_data_analysis():
    req = {"label": "Data analysis", "kind": "skill"}
    spans = [{"id": 1, "text": "MS of Data Analytics graduate student with exposure to data analysis."},
             {"id": 2, "text": "Education and Training Master of Science, Data Analytics 2018 University of Houston, Data Analytics."}]
    status, _, _, _ = _evidence_for_requirement(req, spans)
    assert status == "needs_review"


def test_work_context_is_preferred_to_bare_skill_list():
    req = {"label": "Active Directory", "kind": "skill"}
    spans = [{"id": 1, "text": "Highlights: Active Directory, Excel, SQL."},
             {"id": 2, "text": "Managed the Active Directory domain controllers for branch offices."}]
    status, span, _, reason = _evidence_for_requirement(req, spans)
    assert status == "matched" and span["id"] == 2 and "work" in reason


def test_duration_does_not_verify_role_specific_experience():
    req = {"label": "3 years experience", "kind": "experience"}
    status, span, quote, _ = _evidence_for_requirement(req, [{"id": 1, "text": "6 years of experience in the software industry."}])
    assert status == "needs_review" and span["id"] == 1 and quote == "6 years of experience"


def test_excel_verb_is_not_spreadsheet_evidence():
    req = {"label": "Excel", "kind": "skill"}
    status, _, _, _ = _evidence_for_requirement(req, [{"id": 1, "text": "Able to excel in fast-paced work."}])
    assert status == "no_evidence"
    status, _, quote, _ = _evidence_for_requirement(req, [{"id": 1, "text": "Built reports in Microsoft Excel."}])
    assert status == "matched" and quote == "Excel"


def test_validator_rejects_other_candidate_span_and_missing_quote():
    assessment = {"requirement_id": 1, "label": "Python", "kind": "skill", "mandatory": True,
                  "status": "matched", "span_id": 9, "quote": "Python", "reason": "Direct mention"}
    other_span = {"id": 9, "candidate_id": 2, "text": "Python developer", "start_offset": 0, "end_offset": 16}
    reviewed, rejected = explainability_validation_agent(1, [assessment], [other_span])
    assert reviewed[0]["status"] == "needs_review" and rejected == ["Python"]
    own_span = {**other_span, "candidate_id": 1, "text": "Java developer"}
    reviewed, rejected = explainability_validation_agent(1, [assessment], [own_span])
    assert reviewed[0]["status"] == "needs_review" and rejected == ["Python"]
def test_category_proxy_scores_dataset_labels_only():
    from evaluation.category_proxy import score
    labels = {1: 'CHEF', 2: 'CHEF', 3: 'AVIATION', 4: 'CHEF', 5: 'AVIATION'}
    result = score([1, 3, 2, 5, 4], labels, 'CHEF')
    assert result['precision_at_5'] == 0.6
    assert 0 < result['ndcg_at_5'] < 1


def test_all_dataset_role_templates_have_reviewable_criteria():
    from backend.demo_roles import all_roles
    from backend.matching import parse_job
    roles = all_roles()
    assert len(roles) == 27
    for role in roles:
        title, requirements = parse_job(role['text'])
        assert title == role['title']
        assert requirements, role['id']
        if not role['evaluated']:
            assert any(item['mandatory'] for item in requirements), role['id']
            assert any(not item['mandatory'] for item in requirements), role['id']
