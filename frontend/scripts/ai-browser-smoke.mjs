import { chromium } from 'playwright'
import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

const browser = await chromium.launch({
  executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true,
})
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const report = { gateway_model: 'gpt-4o-mini', candidate_id: 495 }

try {
  await page.goto('http://127.0.0.1:5173/', { waitUntil: 'networkidle' })
  const status = await (await page.request.get('http://127.0.0.1:8000/api/ai/status')).json()
  if (!status.configured || status.model !== report.gateway_model || status.affects_ranking !== false) {
    throw new Error('AI gateway status is not configured as expected')
  }
  report.button_enabled = false

  const jd = readFileSync(resolve('../data/demo/it_infrastructure_engineer_jd.txt'), 'utf8')
  await page.getByLabel('Job description').fill(jd)
  await page.getByRole('button', { name: 'Analyze role' }).click()
  await page.getByLabel('Priority for Windows Server').waitFor()
  const matchResponse = page.waitForResponse(response => response.url().includes('/matches') && response.request().method() === 'POST')
  await page.getByRole('button', { name: /Run candidate match/ }).click()
  const run = await (await matchResponse).json()
  const index = run.candidates.findIndex(candidate => candidate.id === report.candidate_id)
  if (index < 0) throw new Error('Expected existing candidate is not in the shortlist')
  report.run_id = run.id
  report.candidate_rank = run.candidates[index].rank
  await page.locator('.candidate-card .candidate-select').nth(index).click()
  const generate = page.getByRole('button', { name: 'Generate review' })
  await generate.waitFor()
  report.button_enabled = await generate.isEnabled()
  if (!report.button_enabled) throw new Error('Generate review remained disabled')

  const detailUrl = `http://127.0.0.1:8000/api/match-runs/${run.id}/candidates/${report.candidate_id}`
  const sourceUrl = `http://127.0.0.1:8000/api/candidates/${report.candidate_id}/source`
  const before = await (await page.request.get(detailUrl)).json()
  const liveResponse = page.waitForResponse(response => response.url().endsWith('/ai-review') && response.request().method() === 'POST')
  await generate.click()
  const firstHttp = await liveResponse
  report.live_http_status = firstHttp.status()
  if (!firstHttp.ok()) throw new Error(`Live review failed: HTTP ${firstHttp.status()}`)
  const first = await firstHttp.json()
  await page.locator('.ai-review-result').waitFor()
  report.result_visible = await page.locator('.ai-review-result').isVisible()
  report.response_format = first.response_format
  report.first_cached = first.cached
  report.highlight_count = first.highlights.length
  report.summary_present = Boolean(first.summary?.trim())

  const source = await (await page.request.get(sourceUrl)).json()
  const validSpans = new Set(source.spans.map(span => span.id))
  const validPairs = new Set(before.assessments.filter(a => a.span_id !== null).map(a => `${a.requirement_id}:${a.span_id}`))
  report.all_spans_owned = first.highlights.every(item => validSpans.has(item.span_id) &&
    validPairs.has(`${item.requirement_id}:${item.span_id}`))
  report.quotes_in_source = first.highlights.every(item => {
    const span = source.spans.find(span => span.id === item.span_id)
    return source.text.slice(span.start_offset, span.end_offset).toLowerCase().includes(item.quote.toLowerCase())
  })

  const repeatResponse = page.waitForResponse(response => response.url().endsWith('/ai-review') && response.request().method() === 'POST')
  await page.getByRole('button', { name: 'Refresh review' }).click()
  const second = await (await repeatResponse).json()
  report.repeat_cached = second.cached
  const after = await (await page.request.get(detailUrl)).json()
  report.score_unchanged = before.match_index === after.match_index
  report.statuses_unchanged = before.mandatory_status === after.mandatory_status &&
    JSON.stringify(before.assessments) === JSON.stringify(after.assessments)
  report.affects_ranking = first.affects_ranking

  await page.route('**/api/match-runs/**/ai-review', route => route.fulfill({
    status: 503, contentType: 'application/json',
    body: JSON.stringify({ detail: 'Gateway unavailable (HTTP 503); try again later' }),
  }))
  await page.getByRole('button', { name: 'Refresh review' }).click()
  await page.getByRole('alert').getByText('Gateway unavailable (HTTP 503); try again later').waitFor()
  report.unavailable_error_visible = true
  await page.unroute('**/api/match-runs/**/ai-review')

  if (!report.result_visible || first.cached || !report.summary_present || !report.all_spans_owned ||
      !report.quotes_in_source || !report.repeat_cached || !report.score_unchanged ||
      !report.statuses_unchanged || first.affects_ranking !== false || !report.unavailable_error_visible) {
    throw new Error('AI review browser invariant failed')
  }
  writeFileSync(resolve('../evaluation/gateway_live_results.json'), JSON.stringify(report, null, 2) + '\n')
  console.log(JSON.stringify(report, null, 2))
} finally {
  await browser.close()
}
