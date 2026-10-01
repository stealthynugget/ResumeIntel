# Resume Intelligence evaluation findings

## Read the snapshots separately

The saved ranking, import, and match-latency evaluation ran on **2,484 candidates and 22,915 spans**. That database included 2,481 distinct shared CSV resumes and three historical PDF uploads. The preserved local database now has **2,487 candidates and 22,921 spans/FTS rows** after three later account-owned uploads. Current database size is live state, not the denominator of the saved experiment. A new recruiter can search the 2,481 shared CSV candidates and their own uploads; admins can inspect all records. The source artifacts are `smoke_results.json`, `benchmark_full.json`, `metrics.json`, `import_verification.json`, `claim_audit_results.json`, and `gap_status_audit.csv`.

## Ranking quality: exploratory JD relevance

For each of three demo JDs, the implementer graded **18 candidates** from keyword, hybrid, and unrelated pools on a 0–3 scale after viewing system output. Grades 2–3 count as relevant for Precision@5. nDCG@5 uses the ideal order of the **judged pool**, not the whole corpus. `python -m evaluation.score_labels` recomputes the table from `labels.csv` and `review_pool_manifest.json`.

| JD | Keyword P@5 | Hybrid P@5 | Difference | Keyword nDCG@5 | Hybrid nDCG@5 | Difference |
|---|---:|---:|---:|---:|---:|---:|
| Data Scientist | 0.80 | 1.00 | +0.20 | 0.801 | 0.948 | +0.147 |
| IT Infrastructure Engineer | 0.60 | 1.00 | +0.40 | 0.468 | 0.925 | +0.457 |
| HR Analyst | 0.40 | 0.40 | 0.00 | 0.419 | 0.376 | **−0.043** |

**The HR Analyst result is a hybrid nDCG regression.** Analytics-heavy resumes can outrank recruiting evidence, and conservative treatment of study or exposure can lower a relevant profile. The small, implementer-judged pools cannot establish full-corpus recall, hiring accuracy, or fairness.

## Scale and source integrity

The primary `Resume.csv` contains **2,484 rows**. Import job 1 recorded **2,241 new, 242 duplicate, 1 invalid, 0 failed**, so every row has an outcome. The invalid source record 657 has no extractable resume text. The first import took **66.67 seconds**, reaching **1,899.9 MB peak process RSS**. A saved repeat import took **3.44 seconds** and recorded **0 new, 2,483 duplicate, 1 invalid, 0 failed**. Across the 2,481 distinct CSV candidate documents, the saved verification found exact source-cell text and **0 invalid span offsets**. The benchmark snapshot's 22,915 spans matched 22,915 FTS rows. Representative searches found Active Directory in Information Technology, recruitment in HR, and Python in Engineering.

`python -m evaluation.verify_full_import` repeats source-cell, span, and FTS checks against the local CSV and current database. Its JSON `candidates` field was produced after a later upload and must not be used as the saved ranking denominator; `smoke_results.json` records the 2,484-candidate ranking snapshot.

## Performance snapshot

The saved measurements are from one local **Windows Python process** on the 2,484-candidate database. The processor model and precise run timestamp were not recorded. The first cold retrieval loaded the model and matrix; later per-role “cold” values were measured after that load. Each warm median uses five calls. Full match time includes assessment of all 30 retrieved candidates.

| JD | Cold retrieval | Warm retrieval median | Full 30-candidate match |
|---|---:|---:|---:|
| Data Scientist | 37,891.3 ms | 63.7 ms | 270.4 ms |
| IT Infrastructure Engineer | 70.3 ms | 61.5 ms | 225.1 ms |
| HR Analyst | 96.7 ms | 90.5 ms | 253.5 ms |

The API warms the model and vector matrix in a background thread. These measurements are not p95, concurrency throughput, or a service-level promise. `python -m evaluation.benchmark` can create a fresh local timing run; it may create new saved match runs, so use the read-only `python -m evaluation.retrieval_audit` for current retrieval-only timing without changing the database.

## Evidence reliability

`smoke_results.json` records **144/144 automated displayed source-link checks** across the three JDs: 51 Data Scientist, 58 IT, and 35 HR, with zero invalid quote/span links. A separate **15-claim implementer semantic review** in `claim_audit.csv` and `claim_audit_results.json` checked 14 available quotes: 10 claims had substantive contextual support, four were appropriately uncertain, and one was an Excel application-list mention that should not be read as proficiency. Quote integrity and semantic support are different checks.

A further **seven-item, implementer-run gap/status spot check** in `gap_status_audit.csv` found three Data Scientist candidate 1823 skill statuses defensible as *mentions*, while the required three years of relevant experience had No evidence. Candidate 1450's language-specific duration claims did not establish three years of relevant employment. Candidate 1340's six-year software-industry summary remained Needs review for role relevance. Candidate 1441's Random Forest project is a **possible machine-learning false negative** under the exact-phrase evidence rule. This audit is not independently labeled and cannot estimate an error rate. A valid source quote never proves proficiency; missing evidence never proves inability.

## Chat, gateway, and fallback checks

`capstone_browser_smoke_results.json` records a browser flow through the five example recruiter questions: role ranking, skill conjunction, candidate gaps, cited match explanation, and mandatory-status filtering. The saved gateway integration checks include one validated, candidate-owned citation; `full_browser_smoke_results.json` records distinct evidence-only fallback for chat and review when the gateway is unavailable. These are **functional checks**, not chatbot accuracy. An independently labeled question set, per-question-type accuracy, citation-validity rate over such a set, and uncertainty/refusal rate are **Not measured**. The small manual checks above must not be promoted to an answer-quality rate.

## Coverage diagnostics, not JD relevance

The Evaluation API computes live indexing coverage by accessible category. A separate saved `category_proxy_results.json` compares FTS5 and hybrid retrieval across **24 dataset categories and 2,481 shared CSV candidates** using category titles as queries and exact category labels as weak binary proxies. Run `python -m evaluation.category_proxy` to reproduce. **Category-label agreement is not job-match accuracy.** The original Backend Engineer sample was retired after full-corpus checks found zero FastAPI and two Docker mentions; the three judged JDs above remain the relevant comparison.

## Retrieval audit and decision

`backend/matching.py` builds an FTS5 OR query from explicit requirement terms and up to two aliases per skill, with the role title appended. FTS5 ranks up to 3,000 **span** hits by BM25; the first occurrence of each candidate is retained, so lexical rank is based on its best listed span rather than an aggregate. The MiniLM query compares against a cached matrix of indexed span vectors; the highest-scoring span is retained for each candidate. Reciprocal-rank fusion, with a 60-rank offset, combines the top 100 semantic candidates and top 100 lexical candidates. The first 30 fused candidates are analyzed, then the top 10 match indices are displayed.

This span-to-candidate reduction can underweight a candidate with several moderate requirement hits and can overvalue a single generic title hit. The semantic best span can overlook a candidate's broader evidence. HR wording and skill synonyms remain known weaknesses. Candidate-level lexical aggregation and a bounded local cross-encoder are plausible experiments, but no new relevance labels for newly surfaced candidates, alternative latency, or memory comparison exists. **The default pipeline and historical rankings remain unchanged.** `retrieval_audit_v1.json` records a separate, read-only current-corpus baseline; it does not claim an improvement or overwrite the historical results.

The read-only **2,487-candidate** baseline ran on one Windows Python 3.12.4 process with an AMD64 Family 25 processor and 16 logical CPUs. Its peak process RSS was **1,866.4 MB**. Data Scientist, IT, and HR warm five-call retrieval medians were **64.7, 64.2, and 96.1 ms** respectively; the first Data Scientist call took **41,742.6 ms** including model/matrix startup. FTS5 returned 995, 895, and the 3,000-hit cap in the same order, representing 432, 288, and 1,367 distinct candidates within that cap. These timings and hit counts describe the current database and **do not update the 2,484-candidate ranking metrics**. No alternative ranking was benchmarked because it has not been introduced; historical keyword versus hybrid P@5 and nDCG@5 remain the only labeled comparison.

## What has not been measured

Full-corpus recall, blind independently adjudicated relevance, hiring outcomes, fairness, p95/concurrency latency, chatbot accuracy, and a measured alternative-ranker comparison remain unavailable. The UI marks these as **Not measured** rather than inferring them from proxy labels or valid citations.
