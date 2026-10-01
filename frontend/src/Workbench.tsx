import { useEffect, useMemo, useRef, useState } from 'react'
import { request, json, candidateDisplay } from './api'

type Requirement = { id?: number; label: string; kind: string; mandatory: boolean }
type Job = { id: number; title: string; text: string; requirements_version: number; requirements: Requirement[] }
type Candidate = { id: number; external_id: string | null; name: string | null; category: string | null; rank: number; match_index: number; mandatory_status: string; matched: string[]; gaps: string[]; score: Record<string, number> }
type Run = { id: number; job_id: number; candidates: Candidate[]; trace: { retrieval: { method: string; candidates: number }; analysis: { candidates: number } } }
type ImportJob = { id: number; filename: string; status: string; total_rows: number | null; processed_rows: number; imported: number; duplicate: number; invalid: number; failed: number; error: string | null; duration_seconds: number | null; failures: { row_number: number; status: string; detail: string }[] }
type Assessment = { requirement_id: number; label: string; kind: string; mandatory: boolean; status: string; span_id: number | null; quote: string | null; reason: string }
type Detail = { candidate_id: number; match_index: number; mandatory_status: string; score: Record<string, number>; assessments: Assessment[]; trace: Record<string, unknown> }
type Source = { candidate_id: number; filename: string | null; text: string; spans: { id: number; start_offset: number; end_offset: number; page: number | null }[] }
type AiStatus = { configured: boolean; model: string; mode: string; affects_ranking: boolean }
type DemoRole = { id: string; title: string; text: string; group: string; evaluated: boolean }
type BriefItem = { requirement_id: number; requirement: string; mandatory: boolean; status: string; kind: string; span_id?: number; quote?: string; excerpt?: string; evidence_type?: string }
type AiReview = { brief: { role: string; candidate: string; category: string | null; match_index: number; mandatory_status: string; counts: { required_supported: number; required_total: number; preferred_supported: number; preferred_total: number }; supported: BriefItem[]; attention: BriefItem[] }; candidate_id: number; model: string; cached: boolean; affects_ranking: boolean; response_format: string; summary: string; highlights: { requirement_id: number; requirement: string; status: string; span_id: number; quote: string; note: string }[]; follow_up_questions: string[] }

const sample = `Data Scientist
We are seeking a data scientist with 3 years experience building useful models from messy data.
Required: Python, SQL, machine learning, statistics and data analysis.
Preferred: AWS, natural language processing, Tableau.
You will communicate findings to stakeholders and maintain reliable data pipelines.`

const titleFor = candidateDisplay
const statusLabel = (status: string) => status === 'no_evidence' ? 'No evidence' : status === 'needs_review' ? 'Needs review' : status[0].toUpperCase() + status.slice(1)

function Workbench({ aiEnabled }: { aiEnabled: boolean }) {
  const [health, setHealth] = useState<{ candidates: number; spans: number } | null>(null)
  const [importJob, setImportJob] = useState<ImportJob | null>(null)
  const [draft, setDraft] = useState(sample)
  const [demoRoles, setDemoRoles] = useState<DemoRole[]>([])
  const [roleChoice, setRoleChoice] = useState('data_scientist')
  const [uploadProgress, setUploadProgress] = useState('')
  const [job, setJob] = useState<Job | null>(null)
  const [requirements, setRequirements] = useState<Requirement[]>([])
  const [newRequirement, setNewRequirement] = useState('')
  const [run, setRun] = useState<Run | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [source, setSource] = useState<Source | null>(null)
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null)
  const [aiReview, setAiReview] = useState<AiReview | null>(null)
  const [aiBusy, setAiBusy] = useState(false)
  const aiTarget = useRef('')
  const [activeSpan, setActiveSpan] = useState<number | null>(null)
  const [pendingEvidence, setPendingEvidence] = useState<number | null>(null)
  const [compareIds, setCompareIds] = useState<number[]>([])
  const [compareDetails, setCompareDetails] = useState<Detail[]>([])
  const [compareOpen, setCompareOpen] = useState(false)
  const [busy, setBusy] = useState('')
  const [reportBusy, setReportBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const selectedCandidate = run?.candidates.find(c => c.id === selected)
  const hasEdits = job && JSON.stringify(requirements.map(({ label, kind, mandatory }) => ({ label, kind, mandatory }))) !== JSON.stringify(job.requirements.map(({ label, kind, mandatory }) => ({ label, kind, mandatory })))
  const allRequirements = useMemo(() => job?.requirements || [], [job])

  useEffect(() => {
    request<{ candidates: number; spans: number }>('/api/health').then(setHealth).catch(() => setHealth(null))
    request<ImportJob | null>('/api/resumes/import-jobs/latest').then(setImportJob).catch(() => setImportJob(null))
    request<AiStatus>('/api/ai/status').then(setAiStatus).catch(() => setAiStatus(null))
    request<DemoRole[]>('/api/demo-roles').then(roles => { setDemoRoles(roles); if (roles[0]) setDraft(roles[0].text) }).catch(e => setError((e as Error).message))
  }, [])
  useEffect(() => { setAiReview(null) }, [aiEnabled])
  useEffect(() => {
    if (!importJob || !['queued', 'running'].includes(importJob.status)) return
    const timer = window.setInterval(async () => {
      try {
        const current = await request<ImportJob>(`/api/resumes/import-jobs/${importJob.id}`)
        setImportJob(current)
        setHealth(await request('/api/health'))
        if (current.status === 'completed' || current.status === 'completed_with_errors') {
          setNotice(`Import finished: ${current.imported} new, ${current.duplicate} duplicates, ${current.invalid} invalid, ${current.failed} failed.`)
        }
      } catch (e) { setError((e as Error).message) }
    }, 1000)
    return () => window.clearInterval(timer)
  }, [importJob?.id, importJob?.status])
  useEffect(() => {
    aiTarget.current = run && selected !== null ? `${run.id}:${selected}` : ''
    setAiReview(null)
    if (!run || selected === null) { setDetail(null); setSource(null); return }
    let live = true
    setDetail(null)
    setSource(null)
    Promise.all([
      request<Detail>(`/api/match-runs/${run.id}/candidates/${selected}`),
      request<Source>(`/api/candidates/${selected}/source`),
    ]).then(([d, s]) => { if (live) { setDetail(d); setSource(s); setActiveSpan(null) } }).catch(e => { if (live) setError(e.message) })
    return () => { live = false }
  }, [run, selected])
  useEffect(() => {
    if (source && pendingEvidence && source.spans.some(span => span.id === pendingEvidence)) {
      openEvidence(pendingEvidence)
      setPendingEvidence(null)
    }
  }, [source, pendingEvidence])
  useEffect(() => {
    if (!compareOpen) return
    const previouslyFocused = document.activeElement as HTMLElement | null
    const dialog = document.querySelector<HTMLElement>('.compare-modal')
    const focusable = () => Array.from(dialog?.querySelectorAll<HTMLElement>('button:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])') || [])
    focusable()[0]?.focus()
    function handleKey(event: KeyboardEvent) {
      if (event.key === 'Escape') { setCompareOpen(false); return }
      if (event.key !== 'Tab') return
      const elements = focusable()
      if (!elements.length) return
      const first = elements[0], last = elements[elements.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', handleKey)
    return () => { document.removeEventListener('keydown', handleKey); previouslyFocused?.focus() }
  }, [compareOpen])

  function invalidateResults() {
    setRun(null); setSelected(null); setDetail(null); setSource(null); setAiReview(null); setCompareIds([]); setCompareOpen(false)
  }

  function changeDraft(value: string) {
    setDraft(value)
    if (demoRoles.find(role => role.id === roleChoice)?.text !== value) setRoleChoice('custom')
    if (job && value !== job.text) {
      setJob(null); setRequirements([]); invalidateResults()
      setNotice('Job description changed. Analyze the updated role before matching.')
    }
  }

  function chooseRole(value: string) {
    const role = demoRoles.find(item => item.id === value)
    if (role) changeDraft(role.text)
    setRoleChoice(value)
  }

  function changeRequirements(update: (items: Requirement[]) => Requirement[]) {
    setRequirements(update)
    if (run) invalidateResults()
    setNotice('Requirements changed. Run matching again to refresh the shortlist.')
  }

  function addRequirement() {
    const label = newRequirement.trim()
    if (!label) return
    if (requirements.some(item => item.label.toLowerCase() === label.toLowerCase())) {
      setError('That requirement is already listed.'); return
    }
    changeRequirements(items => [...items, { label, kind: 'skill', mandatory: true }])
    setNewRequirement('')
  }

  async function analyze() {
    if (draft.trim().length < 30) { setError('Enter a fuller job description first.'); return }
    setBusy('Analyzing role'); setError(''); setNotice('')
    try {
      const result = await request<Job>('/api/jobs', json({ text: draft }))
      setJob(result); setRequirements(result.requirements); invalidateResults()
      setNotice('Review the extracted requirements, then run matching.')
    } catch (e) { setError((e as Error).message) } finally { setBusy('') }
  }

  async function upload(file: File, purpose: 'resume' | 'job') {
    setBusy(purpose === 'resume' ? 'Importing resumes and building index' : 'Reading job description'); setError(''); setNotice('')
    const body = new FormData(); body.append('file', file)
    try {
      if (purpose === 'resume') {
        if (file.name.toLowerCase().endsWith('.csv')) {
          const result = await request<ImportJob>('/api/resumes/import', { method: 'POST', body })
          setImportJob(result)
          setNotice('CSV uploaded. Indexing continues in the background; progress appears below.')
        } else {
          const result = await request<{ imported: number; skipped: number }>('/api/resumes/import', { method: 'POST', body })
          setHealth(await request('/api/health'))
          setNotice(result.imported ? 'Resume imported and indexed.' : 'That resume is already indexed.')
        }
      } else {
        const result = await request<Job>('/api/jobs/upload', { method: 'POST', body })
        setDraft(result.text); setJob(result); setRequirements(result.requirements); invalidateResults()
        setNotice('Review the extracted requirements, then run matching.')
      }
    } catch (e) { setError((e as Error).message) } finally { setBusy('') }
  }

  async function uploadResumes(files: File[]) {
    if (!files.length) return
    setError(''); setNotice(''); setBusy('Importing selected resumes')
    let imported = 0, duplicates = 0, failed = 0
    const failures: string[] = []
    try {
      for (const [index, file] of files.entries()) {
        setUploadProgress(`${index + 1} / ${files.length}: ${file.name}`)
        const body = new FormData(); body.append('file', file)
        try {
          if (file.name.toLowerCase().endsWith('.csv')) {
            const result = await request<ImportJob>('/api/resumes/import', { method: 'POST', body })
            setImportJob(result)
          } else {
            const result = await request<{ imported: number; skipped: number }>('/api/resumes/import', { method: 'POST', body })
            imported += result.imported; duplicates += result.skipped
          }
        } catch (e) { failed++; failures.push(`${file.name}: ${(e as Error).message}`) }
      }
      setHealth(await request('/api/health'))
      setNotice(`${files.length} selected: ${imported} new, ${duplicates} duplicate, ${failed} failed.${files.some(file => file.name.toLowerCase().endsWith('.csv')) ? ' CSV indexing continues below.' : ''}`)
      if (failures.length) setError(failures.join(' Â· '))
    } finally { setBusy(''); setUploadProgress('') }
  }

  async function match() {
    if (!job) return
    if (draft !== job.text) { setError('The job description changed. Analyze it again before matching.'); return }
    if (!health?.candidates) { setError('Import resumes before running a match.'); return }
    setBusy('Retrieving and checking candidate evidence'); setError(''); setNotice('')
    try {
      let current = job
      if (hasEdits) {
        current = await request<Job>(`/api/jobs/${job.id}/requirements`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ requirements }) })
        setJob(current); setRequirements(current.requirements)
      }
      const result = await request<Run>(`/api/jobs/${current.id}/matches`, { method: 'POST' })
      setRun(result); setSelected(result.candidates[0]?.id ?? null); setCompareIds([])
      if (!result.candidates.length) setNotice('No candidates found. Import more resumes or revise this role.')
    } catch (e) { setError((e as Error).message) } finally { setBusy('') }
  }

  async function downloadFindings() {
    if (!run) return
    setReportBusy(true); setError('')
    try {
      const response = await fetch(`/api/match-runs/${run.id}/report.pdf`, { credentials: 'same-origin' })
      if (!response.ok) {
        let message = `Report download failed (${response.status})`
        try { const payload = await response.json(); message = payload.detail || message } catch { /* server did not return JSON */ }
        throw new Error(message)
      }
      const blob = await response.blob()
      if (blob.type !== 'application/pdf') throw new Error('The report response was not a PDF.')
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url; link.download = `resumeintel-run-${run.id}-findings.pdf`
      document.body.appendChild(link); link.click(); link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 60000)
      setNotice(`Findings PDF for saved run #${run.id} downloaded.`)
    } catch (e) { setError((e as Error).message) } finally { setReportBusy(false) }
  }

  async function generateAiReview() {
    if (!run || selected === null) return
    const currentRun = run.id, currentCandidate = selected
    const target = `${currentRun}:${currentCandidate}`
    setAiBusy(true); setError('')
    try {
      const result = await request<AiReview>(`/api/match-runs/${currentRun}/candidates/${currentCandidate}/ai-review${aiReview ? '?refresh=true' : ''}`, { method: 'POST' })
      if (aiTarget.current === target) setAiReview(result)
    } catch (e) { setError((e as Error).message) } finally { setAiBusy(false) }
  }

  async function retryImport() {
    if (!importJob) return
    setError('')
    try {
      const result = await request<ImportJob>(`/api/resumes/import-jobs/${importJob.id}/retry`, { method: 'POST' })
      setImportJob(result)
    } catch (e) { setError((e as Error).message) }
  }

  async function openComparison() {
    if (!run || compareIds.length !== 2) return
    setBusy('Loading comparison'); setError('')
    try {
      const details = await Promise.all(compareIds.map(id => request<Detail>(`/api/match-runs/${run.id}/candidates/${id}`)))
      setCompareDetails(details); setCompareOpen(true)
    } catch (e) { setError((e as Error).message) } finally { setBusy('') }
  }

  function toggleCompare(id: number) {
    setCompareIds(ids => ids.includes(id) ? ids.filter(value => value !== id) : ids.length < 2 ? [...ids, id] : [ids[1], id])
  }

  function openEvidence(spanId: number | null) {
    if (!spanId) return
    setActiveSpan(spanId)
    window.setTimeout(() => document.getElementById(`span-${spanId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 0)
  }

  function sourceView() {
    if (!source) return null
    const segments: { text: string; id: number | null }[] = []
    let cursor = 0
    for (const span of source.spans) {
      if (span.start_offset > cursor) segments.push({ text: source.text.slice(cursor, span.start_offset), id: null })
      if (span.end_offset > cursor) segments.push({ text: source.text.slice(Math.max(cursor, span.start_offset), span.end_offset), id: span.id })
      cursor = Math.max(cursor, span.end_offset)
    }
    if (cursor < source.text.length) segments.push({ text: source.text.slice(cursor), id: null })
    return <div className="source-text" role="region" aria-label="Resume source text" tabIndex={0}>{segments.map((part, index) => <span key={index} id={part.id ? `span-${part.id}` : undefined} className={part.id === activeSpan ? 'active-source' : ''}>{part.text}</span>)}</div>
  }

  return <div className="app-shell">
    <header className="topbar"><div className="workbench-location"><strong>Recruiter workbench</strong><span>Role, shortlist, evidence</span></div><div className="topbar-right"><span className={`corpus-state ${health?.candidates ? 'ready' : ''}`}><span className="state-dot" />{health ? `${health.candidates} resumes indexed` : 'API unavailable'}</span><label className="secondary-button upload-button">Import resumes<input type="file" multiple accept=".csv,.pdf,.docx,.txt" onChange={e => { const files = Array.from(e.target.files || []); if (files.length) uploadResumes(files); e.target.value = '' }} /></label></div></header>
    <div className="page-heading"><div><span className="eyebrow">CANDIDATE DISCOVERY</span><h1>Find the evidence behind the match.</h1><p>Turn a role into clear requirements, then inspect every recommendation against its resume.</p></div><div className="page-stat"><strong>{health?.candidates.toLocaleString() ?? 'â€”'}</strong><span>resumes indexed</span></div></div>
    {error && <div className="message error" role="alert"><strong>Something needs attention.</strong> {error}<button onClick={() => setError('')} aria-label="Dismiss error">Ã—</button></div>}
    {notice && <div className="message notice" role="status">{notice}<button onClick={() => setNotice('')} aria-label="Dismiss notice">Ã—</button></div>}
    {busy && <div className="progress" role="status"><span className="spinner" />{busy}â€¦</div>}
    {importJob && <div className="import-status" role="status" aria-live="polite"><div className="import-status-header"><strong>{['running', 'queued'].includes(importJob.status) ? 'Indexing resume corpus' : 'Latest resume import'}</strong><span>{importJob.processed_rows.toLocaleString()} / {importJob.total_rows?.toLocaleString() ?? 'â€¦'} rows</span></div><progress value={importJob.processed_rows} max={importJob.total_rows || 1} /><div className="import-status-meta"><span>{importJob.imported.toLocaleString()} new Â· {importJob.duplicate.toLocaleString()} duplicate Â· {importJob.invalid} invalid Â· {importJob.failed} failed</span><span>{importJob.status.replaceAll('_', ' ')}{importJob.duration_seconds != null ? ` Â· ${importJob.duration_seconds}s` : ''}</span></div>{importJob.error && <p>{importJob.error}</p>}{importJob.failures.length > 0 && <details><summary>Review {importJob.invalid + importJob.failed} affected row(s)</summary>{importJob.failures.map(item => <p key={item.row_number}>Record {item.row_number}: {item.detail}</p>)}</details>}{['failed', 'interrupted', 'completed_with_errors'].includes(importJob.status) && <button onClick={retryImport}>Retry incomplete rows</button>}</div>}
    {uploadProgress && <div className="import-status" role="status" aria-live="polite">Uploading {uploadProgress}</div>}
    <main className="workbench">
      <section className="pane role-pane" aria-labelledby="role-heading"><div className="pane-header"><span className="step">01</span><div><h2 id="role-heading">Role brief</h2><p>Define what matters</p></div></div>
        <label className="field-label" htmlFor="role-choice">Example role</label><select id="role-choice" className="role-choice" value={roleChoice} onChange={e => chooseRole(e.target.value)} disabled={!!busy}><option value="custom">Custom job description</option><optgroup label="Evaluated demo roles">{demoRoles.filter(role => role.evaluated).map(role => <option key={role.id} value={role.id}>{role.title}</option>)}</optgroup><optgroup label="All 24 dataset job families">{demoRoles.filter(role => !role.evaluated).map(role => <option key={role.id} value={role.id}>{role.title}</option>)}</optgroup></select><p className="helper">Dataset job-family descriptions are editable examples; only the three demo roles have manually judged evaluation results.</p>
        <label className="field-label" htmlFor="job-text">Job description</label><textarea id="job-text" value={draft} onChange={e => changeDraft(e.target.value)} disabled={!!busy} placeholder="Paste the job description hereâ€¦" />
        <div className="input-actions"><label className="text-upload">Upload PDF, DOCX or TXT<input type="file" accept=".pdf,.docx,.txt" onChange={e => { const file = e.target.files?.[0]; if (file) upload(file, 'job'); e.target.value = '' }} /></label><button className="primary-button" onClick={analyze} disabled={!!busy}>Analyze role</button></div>
        <div className="divider" />
        <div className="section-title"><h3>Requirements</h3><span>{requirements.length}</span></div>
        {!job ? <div className="quiet-state">Analyze a role to extract the criteria you can edit before matching.</div> : <>
          <p className="helper">Move criteria between required and preferred. Remove anything the parser misread.</p>
          <div className="requirements-list">{requirements.map((req, index) => <div className="requirement-row" key={`${req.label}-${index}`}>
            <div><strong>{req.label}</strong><span>{req.kind}</span></div>
            <select aria-label={`Priority for ${req.label}`} value={req.mandatory ? 'required' : 'preferred'} onChange={e => changeRequirements(items => items.map((item, i) => i === index ? { ...item, mandatory: e.target.value === 'required' } : item))}><option value="required">Required</option><option value="preferred">Preferred</option></select>
            <button className="remove-button" aria-label={`Remove ${req.label}`} onClick={() => changeRequirements(items => items.filter((_, i) => i !== index))}>Ã—</button>
          </div>)}</div>
          <div className="add-requirement"><input aria-label="New requirement" placeholder="Add a requirement" value={newRequirement} onChange={e => setNewRequirement(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') addRequirement() }} /><button onClick={addRequirement}>Add</button></div>
          <button className="match-button" onClick={match} disabled={!!busy || !requirements.length}>Run candidate match <span>â†’</span></button>
        </>}
      </section>
      <section className="pane results-pane" aria-labelledby="results-heading"><div className="pane-header"><span className="step">02</span><div><h2 id="results-heading">Ranked candidates</h2><p>{run ? `Top ${run.candidates.length} of ${run.trace.analysis.candidates} analyzed Â· sorted by match index` : 'Awaiting a match run'}</p></div></div>
        {!run ? <div className="empty-state"><div className="empty-glyph">â†—</div><h3>A shortlist with reasons</h3><p>Import a resume corpus, review the role requirements, and run matching to see ranked candidates here.</p></div> : <><div className="results-toolbar"><span>TOP MATCHES</span><div className="results-actions"><button type="button" disabled={reportBusy} onClick={downloadFindings}>{reportBusy ? "Preparing PDF…" : "Download findings PDF"}</button><button disabled={compareIds.length !== 2} onClick={openComparison}>Compare selected ({compareIds.length}/2)</button></div></div><div className="candidate-list">{run.candidates.map(candidate => <div className={`candidate-card ${selected === candidate.id ? 'selected' : ''}`} key={candidate.id}><button className="candidate-select" onClick={() => setSelected(candidate.id)}><div className="candidate-top"><span className="rank">#{String(candidate.rank).padStart(2, '0')}</span><span className={`mandatory-badge ${candidate.mandatory_status === 'satisfied' ? 'satisfied' : ''}`}>{candidate.mandatory_status === 'satisfied' ? 'Required met' : 'Review required'}</span></div><strong>{titleFor(candidate)}</strong><span className="candidate-category">{candidate.category || 'Uploaded resume'}</span><div className="candidate-meta"><span>{candidate.match_index.toFixed(1)} match index</span><span>{candidate.matched.length} supported</span></div><div className="candidate-summary"><span>{candidate.matched.slice(0, 3).join(' Â· ') || 'No direct matches'}</span>{candidate.gaps.length > 0 && <small>Gap: {candidate.gaps[0]}</small>}</div></button><label className="compare-check"><input type="checkbox" checked={compareIds.includes(candidate.id)} onChange={() => toggleCompare(candidate.id)} /> Compare</label></div>)}</div></>}
      </section>
      <section className="pane detail-pane" aria-labelledby="detail-heading"><div className="pane-header"><span className="step">03</span><div><h2 id="detail-heading">Evidence review</h2><p>{selectedCandidate ? titleFor(selectedCandidate) : 'Choose a candidate'}</p></div></div>
        {!detail || !selectedCandidate ? <div className="empty-state"><div className="empty-glyph">â—Ž</div><h3>Inspect the reasoning</h3><p>Select a candidate to review supported requirements and jump to the exact resume passage.</p></div> : <><div className="score-hero"><div><span>MATCH INDEX</span><strong>{detail.match_index.toFixed(1)}</strong><small>Weighted coverage and relevance, not a hiring probability</small></div><div className={`score-status ${detail.mandatory_status === 'satisfied' ? 'good' : ''}`}>{detail.mandatory_status === 'satisfied' ? 'All required items supported' : 'Required evidence incomplete'}</div></div><div className="score-breakdown"><div><span>Required</span><strong>{Math.round(detail.score.mandatory_coverage * 100)}%</strong></div><div><span>Preferred</span><strong>{Math.round(detail.score.preferred_coverage * 100)}%</strong></div><div><span>Semantic</span><strong>{Math.round(detail.score.semantic_relevance * 100)}%</strong></div></div><div className="ai-review"><div className="ai-review-heading"><div><span className="eyebrow">RECRUITER EVIDENCE BRIEF</span><h3>Candidate evidence brief</h3><p>{aiEnabled && aiStatus?.configured ? `${aiStatus.model} drafts only the narrative` : 'Evidence-only fallback is active'}</p></div><button className="secondary-button" onClick={generateAiReview} disabled={aiBusy}>{aiBusy ? 'Reviewing?' : aiReview ? 'Refresh brief' : 'Generate brief'}</button></div><p className="ai-disclosure">Counts and statuses come from saved assessments. Source mentions do not verify proficiency. The model cannot change ranking. A cached first brief sends no new request; Refresh brief requests a fresh draft when the gateway is on.</p>{aiReview && <div className="ai-review-result"><div className="brief-identity"><strong>{aiReview.brief.candidate}</strong><span>{aiReview.brief.role} ? {aiReview.brief.category || 'Uploaded resume'}</span><span>Match index {aiReview.brief.match_index.toFixed(1)} ? {aiReview.brief.mandatory_status === 'satisfied' ? 'Mandatory evidence satisfied' : 'Mandatory evidence incomplete'}</span></div><div className="brief-counts"><span>Required evidence <strong>{aiReview.brief.counts.required_supported}/{aiReview.brief.counts.required_total}</strong></span><span>Preferred evidence <strong>{aiReview.brief.counts.preferred_supported}/{aiReview.brief.counts.preferred_total}</strong></span></div><h4>Supported requirements</h4>{aiReview.brief.supported.length ? aiReview.brief.supported.map(item => <div className="brief-item" key={item.requirement_id}><strong>{item.requirement}</strong><small>{item.mandatory ? 'Required' : 'Preferred'} ? {item.evidence_type}</small><p>{item.excerpt}</p>{item.span_id && <button className="evidence-link" onClick={() => openEvidence(item.span_id!)}>?{item.quote}? <span>View exact source ?</span></button>}</div>) : <p>No validated supported passage is available.</p>}<h4>Missing, partial, or uncertain</h4>{aiReview.brief.attention.length ? aiReview.brief.attention.map(item => <div className="brief-item" key={item.requirement_id}><strong>{item.requirement}</strong><small>{item.mandatory ? 'Required' : 'Preferred'} ? {item.kind} ? {statusLabel(item.status)}</small>{item.excerpt && <p>{item.excerpt}</p>}{item.span_id && <button className="evidence-link" onClick={() => openEvidence(item.span_id!)}>?{item.quote}? <span>View exact source ?</span></button>}</div>) : <p>No saved requirement is flagged for review.</p>}<h4>Overall synthesis</h4><p>{aiReview.summary}</p><h4>Questions to verify</h4><ol>{aiReview.follow_up_questions.map((item, index) => <li key={index}>{item}</li>)}</ol><small>{aiReview.response_format === 'fallback' ? 'Evidence-only fallback' : 'AI draft ? verify in source'} ? {aiReview.cached ? 'cached' : 'new'}. The passages show resume text, not verified capability.</small></div>}</div><button className="secondary-button" onClick={() => location.assign(`/chat?run=${run!.id}&candidate=${selected}`)}>Ask about this candidate in Chat ?</button><div className="section-title"><h3>Requirement review</h3><span>{detail.assessments.length}</span></div><div className="assessment-list">{detail.assessments.map(item => <div className="assessment" key={item.requirement_id}><div className="assessment-top"><strong>{item.label}</strong><span className={`status ${item.status}`}>{statusLabel(item.status)}</span></div><span className="assessment-type">{item.mandatory ? 'Required' : 'Preferred'} Â· {item.kind}</span><p>{item.reason}</p>{item.quote && <button className="evidence-link" onClick={() => openEvidence(item.span_id)}>â€œ{item.quote}â€ <span>View in source â†—</span></button>}</div>)}</div><div className="section-title source-heading"><h3>Resume source</h3><span>{source?.filename || `Candidate ${selected}`}</span></div>{sourceView()}</>}
      </section>
    </main>
    <footer><span>Evidence refers to the uploaded document. Missing evidence does not prove a candidate lacks a skill.</span><span>Local review tool Â· Human decision required</span></footer>
    {compareOpen && <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) setCompareOpen(false) }}><div className="compare-modal" role="dialog" aria-modal="true" aria-labelledby="compare-heading"><div className="modal-heading"><div><span className="eyebrow">SIDE BY SIDE</span><h2 id="compare-heading">Candidate comparison</h2></div><button onClick={() => setCompareOpen(false)} aria-label="Close comparison">Ã—</button></div><p className="comparison-scroll-hint">Scroll sideways to compare both candidates.</p><div className="compare-table" role="region" aria-label="Candidate comparison table" tabIndex={0} onKeyDown={event => { if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') { event.preventDefault(); event.currentTarget.scrollLeft += event.key === 'ArrowRight' ? 100 : -100 } }}><div className="compare-row compare-header"><strong>Requirement</strong>{compareIds.map(id => <strong key={id}>{titleFor(run!.candidates.find(c => c.id === id)!)}</strong>)}</div>{allRequirements.map(req => <div className="compare-row" key={req.id}><div><strong>{req.label}</strong><span>{req.mandatory ? 'Required' : 'Preferred'}</span></div>{compareDetails.map(detail => { const a = detail.assessments.find(item => item.requirement_id === req.id); return <div key={detail.candidate_id}><span className={`status ${a?.status}`}>{statusLabel(a?.status || 'no_evidence')}</span>{a?.quote && <button className="compare-evidence" onClick={() => { setSelected(detail.candidate_id); setPendingEvidence(a.span_id); setCompareOpen(false) }}>â€œ{a.quote}â€ â†—</button>}</div> })}</div>)}</div><p className="modal-note">Scores are an index for review. Read the source before making a hiring decision.</p></div></div>}
  </div>
}

export default Workbench


