"""Build a reviewed source-only submission ZIP from an explicit allowlist."""
import os
import re
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "output" / "ResumeIntel_submission.zip"
FILES = [
    "README.md", ".gitignore", ".env.example", "requirements.txt", "pytest.ini",
    "docs/architecture.jpg", "docs/demo.md", "docs/slack_integration.md", "docs/make_architecture.py",
    "docs/ResumeIntel_panel_presentation.pptx", "docs/build_panel_deck.py", "docs/render_panel_deck.py",
    "frontend/index.html", "frontend/package.json", "frontend/package-lock.json",
    "frontend/tsconfig.json", "frontend/vite.config.ts",
    "frontend/scripts/browser-smoke.mjs", "frontend/scripts/ai-browser-smoke.mjs",
    "frontend/scripts/full-browser-smoke.mjs", "frontend/scripts/quality-browser-smoke.mjs",
    "frontend/scripts/recruiter-chat-browser-smoke.mjs",
    "frontend/scripts/capstone-browser-smoke.mjs",
    "frontend/scripts/category-upload-browser-smoke.mjs",
    "frontend/scripts/theme-browser-smoke.mjs", "frontend/scripts/admin-theme-browser-smoke.mjs",
    "frontend/src/App.tsx", "frontend/src/EvaluationPage.tsx", "frontend/src/Workbench.tsx", "frontend/src/RecruiterChatPage.tsx", "frontend/src/api.ts", "frontend/src/main.tsx", "frontend/src/styles.css",
    "frontend/public/fonts/newsreader-OFL.txt", "frontend/public/fonts/newsreader-latin.woff2",
    "frontend/public/fonts/dmsans-OFL.txt", "frontend/public/fonts/dm-sans-latin.woff2",
    "evaluation/README.md", "evaluation/report.md", "evaluation/labels.csv",
    "evaluation/review_pool_manifest.json",
    "evaluation/metrics.json", "evaluation/import_verification.json",
    "evaluation/benchmark_full.json", "evaluation/smoke_results.json",
    "evaluation/browser_smoke_results.json", "evaluation/full_browser_smoke_results.json",
    "evaluation/quality_browser_smoke_results.json", "evaluation/recruiter_chat_browser_smoke_results.json",
    "evaluation/gateway_live_results.json",
    "evaluation/gateway_chat_live_results.json",
    "evaluation/capstone_browser_smoke_results.json", "evaluation/gap_status_audit.csv",
    "evaluation/claim_audit.csv", "evaluation/claim_audit_results.json",
    "evaluation/audit_claims.py", "evaluation/baseline.py", "evaluation/benchmark.py",
    "evaluation/coverage.py", "evaluation/inspect_pool.py", "evaluation/restore_source_text.py",
    "evaluation/score_labels.py", "evaluation/smoke.py", "evaluation/verify_full_import.py",
    "evaluation/category_proxy.py", "evaluation/category_proxy_results.json",
    "evaluation/retrieval_audit.py", "evaluation/retrieval_audit_v1.json",
    "data/demo/data_scientist_jd.txt", "data/demo/hr_analyst_jd.txt",
    "data/demo/it_infrastructure_engineer_jd.txt",
    "scripts/build_submission.py", "scripts/audit_submission.py",
    "tests/test_core.py", "tests/test_import_jobs.py", "tests/test_llm_review.py", "tests/test_auth_chat.py", "tests/test_capstone_questions.py", "tests/test_findings_pdf.py",
]
FILES += [str(path.relative_to(ROOT)).replace("\\", "/") for path in sorted((ROOT / "backend").glob("*.py"))]


def main():
    forbidden = {"source", "imports", "model_cache", "node_modules", "dist", "__pycache__", ".env"}
    for name in FILES:
        path = ROOT / name
        assert path.is_file(), f"Missing allowlisted file: {name}"
        assert not (set(Path(name).parts) & forbidden), f"Forbidden artifact: {name}"
        assert not name.lower().endswith((".db", ".sqlite", ".pyc")), name
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(TARGET, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(set(FILES)):
            archive.write(ROOT / name, "ResumeIntel/" + name)
    with ZipFile(TARGET) as archive:
        names = archive.namelist()
        assert len(names) == len(set(FILES))
        assert all(name.startswith("ResumeIntel/") for name in names)
        assert not any(set(Path(name).parts) & forbidden for name in names)
        assert archive.testzip() is None
        credentials = {value for value in (os.getenv("OPENAI_API_KEY"), os.getenv("RESUMEINTEL_LLM_API_KEY")) if value}
        local_env = ROOT / ".env"
        if local_env.is_file():
            for match in re.finditer(r"^(?:OPENAI_API_KEY|RESUMEINTEL_LLM_API_KEY)\s*=\s*(.+)$",
                                     local_env.read_text(encoding="utf-8"), re.MULTILINE):
                value = match.group(1).strip().strip("\"'")
                if value:
                    credentials.add(value)
        for credential in credentials:
            for name in names:
                payload = archive.read(name)
                assert credential.encode() not in payload, "Submission contains a configured API credential"
                if name.endswith(".pptx"):
                    with ZipFile(BytesIO(payload)) as nested:
                        assert all(credential.encode() not in nested.read(part) for part in nested.namelist()), \
                            "Submission presentation contains a configured API credential"
    print(f"{TARGET} ({TARGET.stat().st_size:,} bytes; {len(names)} files)")


if __name__ == "__main__":
    main()
