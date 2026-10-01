# Resume Intelligence & Candidate Matching

A local, account-protected recruiting workspace built with React, FastAPI, SQLite FTS5, and MiniLM. The dashboard summarizes the real corpus; the match workbench links recommendations to exact source spans; evaluation shows saved exploratory measurements; candidate chat uses only saved assessments and validated excerpts. The score is a review index, not a hiring probability.

The primary Kaggle dataset pairs each `Resume.csv` record with a PDF named by its `ID`. The CSV's `Resume_str` is the searchable resume text, so importing those PDFs again as separate candidates would duplicate profiles. The app independently accepts uploaded PDF resumes and PDFs can be used for a parsing demo. The primary CSV has no name column; results therefore show **Candidate 12011623** (for example) as the headline and the dataset category underneath. A real name is shown only when supplied as candidate metadata.

## Start locally

Requires Python 3.11+, Node 20+, npm, and roughly 2 GB of free RAM for full-corpus indexing. Run from the repository root in PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m backend.fetch_dataset
python -m backend.seed data/source/Resume.csv
python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
```

The dataset download saves `data/source/Resume.csv` locally. If you already have the CSV, place it there and skip the download. The seed command imports **all rows** by default. Use `--limit 100` only for a quick development run. The first run downloads `sentence-transformers/all-MiniLM-L6-v2` into `data/model_cache/`; later runs use the cache. Imports preserve existing candidates. Never delete the database to retry an import.

In a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173. Create a local recruiter account on the sign-up page. To create the first admin safely, run `python -m backend.create_admin --email you@example.com --name "Your Name"` in a terminal; it prompts for a password without putting it in shell history. No default accounts exist. API docs are at http://127.0.0.1:8000/docs. The app can also upload the entire CSV: indexing continues in one background worker, and the UI shows durable row progress and any invalid or failed rows. A failed or interrupted job can retry from its saved upload. The **Import resumes** picker accepts multiple PDF, DOCX, or TXT files in one selection, indexes each in turn, and reports new, duplicate, and failed counts. Job-description uploads remain single-file.

## Pages and account boundaries

- `/dashboard` shows the candidates accessible to the signed-in account, with source types, category distribution, recent activity, and saved performance highlights from the same scope. A new recruiter sees 2,481 shared CSV resumes. The preserved local database also includes three historical ownerless PDFs and three later account-owned PDFs, so an admin sees 2,487 records as of this visual QA pass. The 72 ms highlight is explicitly the **mean of three saved role medians** measured on the earlier 2,484-record snapshot, not a new search median. New uploads, imports, JDs, runs, and chats are private to their creator. Admins can inspect all records, including historical runs.
- `/match` is the three-pane workbench. The **Example role** selector loads the three evaluated demo JDs plus an editable template for each of the **24 dataset job families**. Select **Custom job description** for another role. Dataset-family templates are starting points, not evaluated JDs; review their criteria before matching. Editing the JD or a requirement clears stale results. A new match analyzes 30 retrieved candidates and displays 10. **Download findings PDF** exports the saved top-10 criteria, statuses, and exact short source excerpts; editing requirements later does not rewrite an old report. Its structured evidence brief shows candidate identity, saved index, required/preferred counts, contextual passages and evidence type, uncertain criteria, synthesis, and follow-up questions. **Ask about this candidate in Chat** carries the current run and candidate into `/chat`.
- `/evaluation` separates the saved **2,484-candidate** ranking/latency snapshot from the current **2,487-candidate** local database. It compares keyword and hybrid P@5 and nDCG@5 with absolute differences for three roles, each with **18 implementer-judged candidates**, and prominently shows the HR Analyst nDCG regression. It also documents import outcomes and timings, the separate **144/144 automated link** and **15-claim semantic** checks, seven manual gap/status observations, saved gateway/fallback functional checks, and unmeasured outcomes. Live indexing coverage for every accessible category and the saved 24-category label proxy are kept separate from genuine JD relevance. Category-label agreement is not job-match accuracy.
- `/chat` shows five example recruiter questions and plain role/candidate selectors. Its channel-independent server-side `ChatService` retains conversation context and routes only to read-only, allowlisted functions. The five capstone questions now use saved run rank, candidate-owned skill evidence with AND semantics, grouped saved gaps, cited match explanations, and saved mandatory status across **all 30 analyzed** candidates. Without a selected JD/run, the relevance question asks for one; a role title alone is never presented as a JD-based match. A skills-list mention is never called verified experience. General product and Evaluation questions, authorized comparison, and follow-ups remain available without exposing backend scope names in the interface. GPT-4o-mini candidate drafts require validated citation pairs and are labeled **AI draft ? verify in source**. Invalid or unavailable gateway output uses a distinct **Evidence-only fallback**. Salary, protected-characteristic inferences, and hiring decisions are refused. Signed-in citation links reopen exact source passages after authorization. See `docs/slack_integration.md` for the future adapter contract; Slack is not connected.
- `/account` edits display name and changes password; `/admin/users` manages roles and activation. The last active admin cannot be disabled or demoted.

Passwords use Argon2id. Opaque session IDs are hashed in SQLite and sent only in HttpOnly, SameSite=Lax cookies. Cookies are Secure on HTTPS or when `RESUMEINTEL_COOKIE_SECURE=true`. Mutations require a session CSRF header and origin checks; login attempts are rate limited. The React app keeps the CSRF value in memory and does not store tokens in localStorage. The SQLite migration copies historical chat IDs, messages, and run/candidate context into new scope-capable assistant tables idempotently; it leaves the legacy tables and all resume data intact.

## Appearance and accessibility

The **Appearance** selector is available on sign-in, sign-up, and every signed-in page. **System** is the default and follows the OS live; **Light** and **Dark** are deliberate warm-neutral and charcoal palettes. Only an explicit appearance preference is saved in localStorage. A small script applies the theme and browser theme color before React renders. Candidate data, sessions, and credentials are never stored for this feature. Evidence links, source and comparison dialogs, mobile tables, and the theme control support keyboard use; mobile tables display a sideways-scroll hint. Reduced-motion settings disable the loading animation and smooth scrolling.

## Measured local corpus

The primary CSV has **2,484 rows** across 24 categories. In this existing database, the full import processed all 2,484: **2,241 newly imported, 242 duplicates, 1 invalid empty resume, 0 failed** in **66.67 seconds**. The 242 duplicates include 240 previously indexed CSV candidates and two duplicate source rows. Peak importer process RSS was **1,899.9 MB**. At the saved benchmark, the database held **2,484 candidates**: 2,481 distinct CSV resumes plus three uploaded PDFs, with **22,915 source spans** and the same number of FTS5 entries. Three later account-owned PDFs bring the preserved local total to **2,487 candidates and 22,921 spans/FTS entries**; each is visible only to its owner and admins. The saved evaluation and timing artifacts were not rerun after those uploads. All 2,481 unique CSV documents match their exact source cells; all stored span offsets pass validation. A repeated full CSV upload produced **0 new, 2,483 duplicate, 1 invalid, 0 failed** in **3.44 seconds**.

Reproduce the checks locally with `python -m evaluation.verify_full_import`. The source CSV and database are deliberately absent from the submission ZIP.

## Use the workbench

1. Use the prefilled Data Scientist JD or paste one of the three files in `data/demo/`. Select **Analyze role**.
2. Check the required and preferred requirements. The parser recognizes separate "Preferred qualifications" headings. Edit any requirement before matching.
3. Select **Run candidate match**. Retrieval combines requirement-focused FTS5 with cached MiniLM vectors and reciprocal rank fusion. All 30 retrieved candidates are analyzed; the UI displays the top 10.
4. Select a candidate and click a cited phrase to jump to its source span. "Matched" indicates an evidence mention, **not verified proficiency**. Negated, limited, student-exposure, and duration-only claims can be marked **Needs review** or **No evidence**.
5. Check two cards and open **Compare selected**. The dialog supports Tab, Shift+Tab, and Escape. Editing the JD or requirements clears the old results.

The index weights required nonqualification coverage (50%), preferred nonqualification coverage (20%), semantic relevance (20%), and qualification evidence (10%); absent groups are renormalized. Required coverage and the mandatory status are shown separately. Missing evidence does not prove the person lacks a skill.

The report endpoint is `GET /api/match-runs/{run_id}/report.pdf`. It requires a signed-in owner (or admin), returns an in-memory A4 attachment, and reads **saved result assessments** rather than mutable job requirements. The PDF lists 30 retrieved/analyzed and 10 displayed where the saved run recorded those counts, plus coverage and validated candidate-owned short excerpts. It makes no gateway call, contains no full resume or contact information, and is not stored by the server. ReportLab is installed with the Python requirements. The reviewed preview is kept locally at `output/pdf/match-findings-preview.pdf` and is intentionally excluded from the submission ZIP because it contains candidate evidence.

## Architecture

See [architecture.jpg](docs/architecture.jpg). It includes authentication, ChatService, the server-side AI gateway/fallback, and Evaluation beside the ingestion-to-ranking path. A bounded 24-resume embedding batch and transactional writes make full imports practical. A cached vector matrix is rebuilt when the database path, span count, or maximum span ID changes. One in-process background worker keeps import progress queryable while indexing.

The four analysis modules run in order and save a trace with each match. They are typed, deterministic modules within one service. See `backend/agents.py` and `backend/matching.py`. The **on-demand evidence brief** builds every count, status and source passage from saved assessments. GPT-4o-mini may draft a bounded synthesis and linked notes from selected redacted excerpts; a distinct evidence-only fallback supplies the same structured sections. Review cache version 7 invalidates older shallow briefs. Neither path changes ranking or requirement status.

## Optional GPT-4o-mini gateway

Configure the Chat Completions gateway for the **API server** before starting Uvicorn. Copy `.env.example` to `.env`, then put the credential in the local `.env` file's `OPENAI_API_KEY` entry. The local `.env` overrides stale inherited shell values at server startup; restart Uvicorn after editing it. The adapter calls `/chat/completions` beneath the base URL. Never put the credential in frontend files, `.env.example`, logs, or the submission ZIP. Existing `RESUMEINTEL_LLM_*` names remain supported and take precedence if set.

```powershell
Copy-Item .env.example .env
# Edit .env locally and set OPENAI_API_KEY there.
python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
```

The header has a per-account **AI gateway on/off** button. Off blocks gateway calls for that account and labels responses **Evidence-only fallback**. On permits server-side drafts; **Send test** makes one tiny non-resume request and shows the responding host and latency, so a panel can verify the connection without sending candidate data. Matching, role analysis, Dashboard, and Evaluation do not call the gateway. A first **Generate brief** may use its cache; **Refresh brief** forces a new request when On. General product/Evaluation/JD questions and citeable candidate, comparison, or score questions can request a bounded wording draft. The five capstone list/filter/gap questions retain their exact deterministic answers. The candidate draft receives a bounded answer assembled from saved, candidate-owned citations; the full resume stays local. The adapter negotiates response formats and validates source IDs, quotes, length, and unsupported claims. A rejected brief may be regenerated once from the same bounded evidence; otherwise the explicit fallback appears. On October 1, 2026, the `.env` gateway at `aicredits.in` returned HTTP 200 to a non-resume probe and produced a validated uncached brief using `json_schema`. AI never changes match scores or requirement statuses. Citation validity does not itself prove proficiency; review the source before relying on draft prose.

## Measured search and evaluation

On the 2,484-candidate local database, warm median retrieval for the three demo roles was **63.7 ms, 61.5 ms, and 90.5 ms** respectively; complete 30-candidate matches took **270.4 ms, 225.1 ms, and 253.5 ms**. The first cold retrieval took **37.9 seconds** for model and index loading; API startup now warms these in the background. These are local single-process measurements, not a concurrency guarantee. See `evaluation/benchmark_full.json`.

A separate **read-only 2,487-candidate retrieval audit** in `evaluation/retrieval_audit_v1.json` measured warm medians of **64.7 ms Data Scientist, 64.2 ms IT, and 96.1 ms HR** on one Windows Python process, with **1,866.4 MB peak process RSS**. It also records the FTS span-hit counts before candidate deduplication. The unchanged pipeline uses up to 3,000 FTS5 span hits, keeps each candidate's first BM25 occurrence, compares all cached MiniLM span vectors and keeps the best span per candidate, fuses the top 100 from each source, and analyzes 30. The HR and synonym limitations remain. Candidate-level lexical aggregation or a cross-encoder would need new labels, latency, and memory comparisons before replacing this default; no alternative has been claimed as an improvement.

The 18-candidate-per-role exploratory evaluation compares keyword-only and hybrid retrieval using manually assigned 0-3 relevance grades. Precision@5 treats grades 2-3 as relevant. The report in [report.md](evaluation/report.md) includes the negative HR result and a 15-claim semantic audit. The three demo roles are Data Scientist, IT Infrastructure Engineer, and HR Analyst. The earlier FastAPI/Docker backend role was retired after a full-corpus coverage check found **0 FastAPI** and **2 Docker** mentions.

The saved evaluation has **144/144 valid automated source links** and a distinct **seven-item manual gap/status spot check** with one possible machine-learning false negative. Gateway and five-question checks validate functions and source ownership, not chatbot accuracy; no independent labeled question benchmark exists. Full-corpus recall, fairness, hiring accuracy, p95, and concurrency remain **Not measured**.

## Verify

```powershell
python -m pytest -q
python -m evaluation.verify_full_import
python -m evaluation.smoke
python -m evaluation.baseline
python -m evaluation.score_labels
python -m evaluation.benchmark
cd frontend
npm run build
node scripts/capstone-browser-smoke.mjs
node scripts/theme-browser-smoke.mjs
node scripts/admin-theme-browser-smoke.mjs
```

The current Chrome script signs up a fresh test account, creates a Data Scientist run, generates a structured brief, opens Chat with the same run/candidate, asks all five exact capstone questions, opens a cited source span, checks Evaluation, and verifies a 390 px viewport. It adds test-owned jobs, runs and chat but never deletes or recreates candidate data. See the metadata-only [current browser result](evaluation/capstone_browser_smoke_results.json), the [10-minute demo sequence](docs/demo.md), and the [8-slide panel deck](docs/ResumeIntel_panel_presentation.pptx). Earlier browser results remain historical checks.

The theme Chrome sweep captures all recruiter routes in Light and Dark at 1440, 768, and 390 px, plus populated Match, the brief, Chat, comparison, loading, source, and keyboard/theme behavior. Its screenshots and results are saved only in `output/design_qa/after/`. The admin sweep runs on a separate temporary SQLite database in that same output folder, checks Admin Users and import states, and never changes the primary candidate database. Representative older screenshots are in `output/design_qa/before/`. These QA artifacts and the reversible pre-redesign source backup in `output/` are excluded from the submission ZIP.
`evaluation.score_labels` recomputes the saved comparison from the text-free judged-pool manifest and labels even from a fresh ZIP. `evaluation.audit_claims` checks saved local run IDs and therefore requires the original local database; the included `claim_audit.csv` and `claim_audit_results.json` document that historical check. Internal database candidate IDs can change when a clean database is seeded.

The seven-item [manual gap/status audit](evaluation/gap_status_audit.csv) is also implementer reviewed. It finds a possible machine-learning false negative for candidate 1441, whose Random Forest project was not recognized by the exact-phrase evidence rule. The saved ranking and original evaluation labels remain intact; the audit is a limitation disclosure, not a revised accuracy metric.

## Limits and data handling

The rule parser and evidence matcher still require human review. An Excel entry in a skills list is an example of a mention that does not prove practical use. Experience duration may belong to a different domain; the app now flags duration claims for review. The HR role is challenging for hybrid reranking and remains a documented negative result. Labels were assigned by the implementer after viewing results, so reported metrics are exploratory, not independent validation, corpus-wide recall, fairness, or hiring accuracy.

The app is intended for local review, not internet deployment with real resumes. Source CSVs, databases, saved uploads, model caches, `node_modules`, secrets, and browser screenshots are excluded from the submission package. Scanned PDFs need OCR, which is not included. The in-process worker and in-memory vector index are suitable for one local server process, not a multi-server production deployment. The chatbot validates citation identities and restricts supplied context, but prose still needs human source review; neither this exploratory evaluation nor the app validates fairness or hiring outcomes.

