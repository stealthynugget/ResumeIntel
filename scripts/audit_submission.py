"""Check the source-only ZIP for local data and common credential patterns."""
import os
import re
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

target = Path(__file__).resolve().parents[1] / "output" / "ResumeIntel_submission.zip"
root = target.parent.parent
forbidden_parts = {".env", "source", "imports", "node_modules", "model_cache", "__pycache__", "dist"}
forbidden_suffixes = {".db", ".sqlite", ".csv"}  # allow only reviewed evaluation labels/audit CSVs
safe_csv = {"ResumeIntel/evaluation/labels.csv", "ResumeIntel/evaluation/claim_audit.csv",
            "ResumeIntel/evaluation/gap_status_audit.csv"}
secret_patterns = [re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
                   re.compile(rb"(?:OPENAI_API_KEY|RESUMEINTEL_LLM_API_KEY)\s*=\s*[^\s#]+")]
with ZipFile(target) as archive:
    names = archive.namelist()
    assert archive.testzip() is None
    for name in names:
        path = Path(name)
        assert not forbidden_parts.intersection(path.parts), name
        assert "output" not in path.parts and "design_qa" not in path.parts, name
        assert path.suffix.lower() not in {".png", ".webp"}, name
        assert path.suffix.lower() not in {".db", ".sqlite", ".pyc", ".pdf", ".docx"}, name
        assert path.suffix.lower() != ".csv" or name in safe_csv, name
        payload = archive.read(name)
        assert not any(pattern.search(payload) for pattern in secret_patterns), name
        if name.endswith(".pptx"):
            with ZipFile(BytesIO(payload)) as nested:
                assert nested.testzip() is None
                for part in nested.namelist():
                    inner = nested.read(part)
                    assert not any(pattern.search(inner) for pattern in secret_patterns), f"{name}:{part}"
    assert "ResumeIntel/frontend/src/App.tsx" in names
    assert "ResumeIntel/frontend/src/EvaluationPage.tsx" in names
    assert "ResumeIntel/backend/findings_pdf.py" in names
    assert "ResumeIntel/tests/test_findings_pdf.py" in names
    assert "ResumeIntel/evaluation/retrieval_audit_v1.json" in names
    assert "ResumeIntel/frontend/src/Workbench.tsx" in names
    assert "ResumeIntel/backend/auth.py" in names
    assert "ResumeIntel/backend/chat.py" in names
    assert "ResumeIntel/backend/chat_service.py" in names
    assert "ResumeIntel/frontend/src/RecruiterChatPage.tsx" in names
    assert "ResumeIntel/frontend/scripts/recruiter-chat-browser-smoke.mjs" in names
    assert "ResumeIntel/evaluation/recruiter_chat_browser_smoke_results.json" in names
    assert "ResumeIntel/docs/demo.md" in names
    assert "ResumeIntel/docs/slack_integration.md" in names
    assert "ResumeIntel/docs/architecture.jpg" in names
    assert "ResumeIntel/docs/ResumeIntel_panel_presentation.pptx" in names
    assert "ResumeIntel/frontend/scripts/capstone-browser-smoke.mjs" in names
    assert "ResumeIntel/frontend/scripts/theme-browser-smoke.mjs" in names
    assert "ResumeIntel/frontend/scripts/admin-theme-browser-smoke.mjs" in names
    assert "ResumeIntel/evaluation/gap_status_audit.csv" in names
    assert "ResumeIntel/tests/test_capstone_questions.py" in names
    for current in ("README.md", "docs/demo.md", "docs/build_panel_deck.py",
                    "docs/ResumeIntel_panel_presentation.pptx", "evaluation/report.md",
                    "frontend/index.html", "frontend/src/App.tsx", "frontend/src/EvaluationPage.tsx",
                    "frontend/src/Workbench.tsx", "frontend/src/RecruiterChatPage.tsx",
                    "frontend/src/styles.css", "frontend/scripts/theme-browser-smoke.mjs",
                    "frontend/scripts/admin-theme-browser-smoke.mjs"):
        assert archive.read("ResumeIntel/" + current) == (root / current).read_bytes(), current
print(f"Audited {len(names)} source and documentation files; no private data or credential pattern found")
