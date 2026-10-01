import { FormEvent, useEffect, useRef, useState } from 'react'
import { candidateDisplay, json, request } from './api'

type Scope = 'general' | 'corpus' | 'run' | 'candidate'
type RunRow = { id: number; title: string }
type Candidate = { id: number; name: string | null; external_id: string | null; category: string | null; rank: number }
type Run = { id: number; candidates: Candidate[] }
type Citation = { candidate_name?: string | null; candidate_id?: number; run_id?: number | null; requirement_id: number | null; span_id: number; requirement: string; quote: string; status: string }
type Message = { id: number; role: string; content: string; citations: Citation[]; response_kind: string | null; suggested_actions?: { label: string; prompt?: string; href?: string }[] }
type Conversation = { id: number; scope: Scope; run_id: number | null; candidate_id: number | null; title: string; candidate_name: string | null; candidate_category: string | null; messages: Message[] }
type Summary = Omit<Conversation, 'messages'> & { updated_at: string }
type Source = { text: string; filename: string | null; spans: { id: number; start_offset: number; end_offset: number }[] }

const examples = [
  'Which candidates are most relevant for this Data Scientist position?',
  'Which candidates have Python, SQL and machine learning experience?',
  'What skills are missing for this candidate compared with the job description?',
  'Why was this candidate matched with the role?',
  'Which candidates satisfy the mandatory requirements?',
]
const kindLabel = (role: string, kind: string | null) => role === 'user' ? 'YOU' : kind === 'fallback' ? 'EVIDENCE-ONLY FALLBACK' : kind === 'llm_draft' || kind === 'llm_context_draft' ? 'AI DRAFT — VERIFY IN SOURCE' : kind === 'saved_measurement' ? 'SAVED MEASUREMENT' : kind === 'evidence_refusal' ? 'NO SUPPORTED ANSWER' : 'SAVED EVIDENCE'

function SourcePassage({ citation, close }: { citation: Citation; close: () => void }) {
  const [source, setSource] = useState<Source | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let live = true
    const prior = document.activeElement as HTMLElement | null
    if (!citation.candidate_id) { setError('This historical citation has no candidate link.'); return }
    request<Source>(`/api/candidates/${citation.candidate_id}/source`).then(value => { if (live) setSource(value) }).catch(e => { if (live) setError(e.message) })
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') close(); if (event.key === 'Tab') { event.preventDefault(); document.querySelector<HTMLElement>('.source-dialog .icon-button')?.focus() } }
    window.addEventListener('keydown', key)
    return () => { live = false; window.removeEventListener('keydown', key); prior?.focus() }
  }, [citation, close])
  const span = source?.spans.find(item => item.id === citation.span_id)
  return <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) close() }}><div className="source-dialog" role="dialog" aria-modal="true" aria-label="Resume source passage"><div className="surface-heading"><div><span className="eyebrow">SAVED RESUME SOURCE</span><h2>{citation.requirement}</h2></div><button className="icon-button" onClick={close} aria-label="Close source passage" autoFocus>×</button></div>{error && <p role="alert">{error}</p>}{!source && !error && <p role="status">Loading source…</p>}{source && span && <><p className="muted">{source.filename || `Candidate ${citation.candidate_id}`} · span #{citation.span_id}</p><div className="source-passage">{source.text.slice(Math.max(0, span.start_offset - 220), span.start_offset)}<mark>{source.text.slice(span.start_offset, span.end_offset)}</mark>{source.text.slice(span.end_offset, Math.min(source.text.length, span.end_offset + 220))}</div><p className="page-footnote">Exact saved span. A quotation alone does not verify proficiency.</p></>}{source && !span && <p role="alert">The cited span was not found for this candidate.</p>}</div></div>
}

export default function RecruiterChatPage() {
  const [runs, setRuns] = useState<RunRow[]>([])
  const [runId, setRunId] = useState('')
  const [run, setRun] = useState<Run | null>(null)
  const [candidateId, setCandidateId] = useState('')
  const [compareId, setCompareId] = useState('')
  const [history, setHistory] = useState<Summary[]>([])
  const [active, setActive] = useState<Conversation | null>(null)
  const [question, setQuestion] = useState('')
  const [citation, setCitation] = useState<Citation | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const pendingCandidate = useRef('')
  const questionInput = useRef<HTMLInputElement>(null)

  async function refresh() {
    const [available, conversations] = await Promise.all([request<RunRow[]>('/api/match-runs'), request<Summary[]>('/api/chat/conversations')])
    setRuns(available); setHistory(conversations)
  }
  async function openConversation(id: number, linkMessage?: number, linkCitation?: number) {
    const value = await request<Conversation>(`/api/chat/conversations/${id}`)
    setActive(value); setRunId(value.run_id ? String(value.run_id) : ''); setCandidateId(value.candidate_id ? String(value.candidate_id) : ''); setCompareId('')
    if (linkMessage !== undefined && linkCitation !== undefined) {
      const item = value.messages.find(message => message.id === linkMessage)?.citations[linkCitation]
      if (item) setCitation({ ...item, candidate_id: item.candidate_id || value.candidate_id || undefined })
    }
  }
  useEffect(() => {
    refresh().then(async () => {
      const params = new URLSearchParams(location.search)
      const conversation = Number(params.get('conversation'))
      if (conversation) await openConversation(conversation, Number(params.get('message')), Number(params.get('citation')))
      else if (params.get('run')) { pendingCandidate.current = params.get('candidate') || ''; setRunId(params.get('run') || '') }
    }).catch(e => setError(e.message)).finally(() => setLoading(false))
  }, [])
  useEffect(() => {
    setRun(null); setCompareId('')
    if (!runId) { setCandidateId(''); return }
    let live = true
    request<Run>(`/api/match-runs/${runId}`).then(value => {
      if (!live) return
      setRun(value)
      if (pendingCandidate.current) { setCandidateId(value.candidates.some(item => String(item.id) === pendingCandidate.current) ? pendingCandidate.current : ''); pendingCandidate.current = '' }
      else setCandidateId(previous => value.candidates.some(item => String(item.id) === previous) ? previous : '')
    }).catch(e => { if (live) setError(e.message) })
    return () => { live = false }
  }, [runId])
  function chooseRun(value: string) { pendingCandidate.current = ''; setActive(null); setRun(null); setCandidateId(''); setRunId(value) }
  function chooseCandidate(value: string) { setActive(null); setCandidateId(value); setCompareId('') }
  async function startConversation() {
    const scope: Scope = runId ? candidateId ? 'candidate' : 'run' : 'corpus'
    const context = { scope, run_id: runId ? Number(runId) : null, candidate_id: candidateId ? Number(candidateId) : null }
    if (runId && run?.id !== Number(runId)) throw new Error('Wait for the selected match run to load.')
    const made = await request<{ id: number }>('/api/chat/conversations', json(context))
    await refresh(); await openConversation(made.id)
    return { id: made.id, context }
  }
  async function send(event: FormEvent) {
    event.preventDefault()
    if (!question.trim()) return
    const draft = question.trim()
    setBusy(true); setError('')
    try {
      const target = active ? { id: active.id, context: { scope: active.scope, run_id: active.run_id, candidate_id: active.candidate_id } } : await startConversation()
      await request(`/api/chat/conversations/${target.id}/messages`, json({ question: draft, context: { ...target.context, compare_candidate_id: compareId ? Number(compareId) : null } }))
      setQuestion(''); await openConversation(target.id); await refresh()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  const activeTitle = active?.candidate_name ? `${active.candidate_name} · ${active.title}` : active?.run_id ? active.title : 'Accessible corpus and app guidance'
  const selectedTitle = run ? runs.find(item => item.id === run.id)?.title || `Run #${run.id}` : 'No role selected'
  const selectedCandidate = run?.candidates.find(item => String(item.id) === candidateId)
  return <div className="page-content"><div className="section-intro"><span className="eyebrow">GROUNDED RECRUITER ASSISTANT</span><h1>Ask the evidence.</h1><p>Choose a saved role and, when needed, a candidate. Every resume claim links to its source.</p></div>
    {error && <div className="message error" role="alert">{error}<button onClick={() => setError('')} aria-label="Dismiss error">×</button></div>}
    {loading ? <div className="state-panel" role="status">Loading conversations…</div> : <div className="chat-layout"><aside className="surface chat-sidebar"><h2>Current context</h2><label>Saved role<select aria-label="Saved match run" value={runId} onChange={e => chooseRun(e.target.value)}><option value="">No role selected</option>{runs.map(item => <option value={item.id} key={item.id}>#{item.id} · {item.title}</option>)}</select></label><label>Candidate<select aria-label="Matched candidate" value={candidateId} disabled={!run} onChange={e => chooseCandidate(e.target.value)}><option value="">No candidate selected</option>{run?.candidates.map(item => <option value={item.id} key={item.id}>#{item.rank} · {candidateDisplay(item)} ({item.category || 'Upload'})</option>)}</select></label><p className="muted">{selectedTitle}{selectedCandidate ? ` · ${candidateDisplay(selectedCandidate)}` : ''}</p><button className="primary-button" disabled={busy || (!!runId && !run)} onClick={() => { setActive(null); setQuestion(''); questionInput.current?.focus() }}>New conversation</button><div className="divider" /><h2>History</h2>{history.length ? <div className="conversation-list">{history.map(item => <button className={active?.id === item.id ? 'active' : ''} key={item.id} onClick={() => openConversation(item.id).catch(e => setError(e.message))}><strong>{item.candidate_name || item.title}</strong><span>{item.title}{item.candidate_category ? ` · ${item.candidate_category}` : ''}</span></button>)}</div> : <p className="muted">No conversations yet.</p>}</aside>
      <section className="surface chat-main" aria-label="Recruiter conversation"><div className="surface-heading"><div><span className="eyebrow">{active ? 'SAVED CONVERSATION' : 'NEW CONVERSATION'}</span><h2>{active ? activeTitle : selectedCandidate ? `${candidateDisplay(selectedCandidate)} · ${selectedTitle}` : selectedTitle}</h2>{active?.candidate_category && <p className="muted">{active.candidate_category}</p>}</div><span className="chat-boundary">Read only · human review</span></div>
        {active?.scope === 'candidate' && run?.id === active.run_id && <label className="compare-picker">Compare with a candidate in this run<select aria-label="Compare with candidate" value={compareId} onChange={e => setCompareId(e.target.value)}><option value="">Select when comparing</option>{run.candidates.filter(item => item.id !== active.candidate_id).map(item => <option key={item.id} value={item.id}>{candidateDisplay(item)}</option>)}</select></label>}
        <div className="chat-examples" aria-label="Example recruiter questions">{examples.map(example => <button type="button" key={example} onClick={() => { setQuestion(example); questionInput.current?.focus() }}>{example}</button>)}</div>
        <div className="chat-messages" aria-live="polite">{active?.messages.length ? active.messages.map(message => <div className={`chat-message ${message.role}`} key={message.id}><span>{kindLabel(message.role, message.response_kind)}</span><p>{message.content}</p>{message.citations.length > 0 && <div className="citation-list">{message.citations.map((item, index) => <button key={`${item.candidate_id}:${item.span_id}:${index}`} onClick={() => setCitation({ ...item, candidate_id: item.candidate_id || active.candidate_id || undefined })}><strong>{item.requirement}</strong><span>“{item.quote}” · Open exact source ↗</span></button>)}</div>}{message.suggested_actions?.length ? <div className="chat-actions">{message.suggested_actions.map(action => <button key={action.label} onClick={() => action.prompt ? setQuestion(action.prompt) : action.href ? location.assign(action.href) : undefined}>{action.label}</button>)}</div> : null}</div>) : <div className="chat-empty"><p>Start with one of the questions above. A saved role is needed for ranking and mandatory checks; select a candidate for gap and match explanations.</p></div>}</div>
        <form className="chat-compose" onSubmit={send}><label htmlFor="chat-question">Your question</label><div><input ref={questionInput} id="chat-question" value={question} onChange={e => setQuestion(e.target.value)} placeholder="Ask about this role or candidate…" maxLength={800} required /><button className="primary-button" disabled={busy || !question.trim() || (!!runId && !run)}>{busy ? 'Reviewing…' : 'Ask'}</button></div><small>Resume mentions require source review. Unsupported claims and hiring decisions are refused.</small></form></section></div>}{citation && <SourcePassage citation={citation} close={() => setCitation(null)} />}</div>
}
