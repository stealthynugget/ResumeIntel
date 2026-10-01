import { chromium } from 'playwright'
import { resolve } from 'node:path'
import { writeFileSync } from 'node:fs'

const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const result = {}
const email = `assistant-smoke-${Date.now()}@example.test`
const password = `Long-test-${crypto.randomUUID()}!`

async function ask(question) {
  const previous = await page.locator('.chat-message.assistant').count()
  await page.getByLabel(/Question in .* scope/).fill(question)
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await page.locator('.chat-message.assistant').nth(previous).waitFor({ timeout: 60000 })
  return page.locator('.chat-message.assistant').nth(previous)
}
async function newScope(scope) {
  await page.getByLabel('Conversation scope').selectOption(scope)
  if (scope === 'run' || scope === 'candidate') {
    await page.getByLabel('Saved match run').selectOption({ index: 1 })
    if (scope === 'candidate') {
      await page.getByLabel('Matched candidate').locator('option').nth(1).waitFor({ state: 'attached' })
      await page.getByLabel('Matched candidate').selectOption({ index: 1 })
    }
  }
  await page.getByRole('button', { name: 'Start conversation' }).click()
  await page.getByText(`ACTIVE SCOPE · ${scope.toUpperCase()}`).waitFor()
}
try {
  await page.goto('http://127.0.0.1:5173/chat', { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: /Create an account/ }).click()
  await page.getByLabel('Display name').fill('Assistant Smoke')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Create account' }).click()
  await page.getByRole('button', { name: 'AI Chat' }).click()
  await page.getByRole('heading', { name: 'Ask the evidence.' }).waitFor()
  await newScope('general')
  result.generalScope = await page.getByText('ACTIVE SCOPE · GENERAL').isVisible()
  result.evaluation = (await (await ask('Explain the HR evaluation regression')).innerText()).includes('0.376')
  result.product = (await (await ask('How do I upload resumes?')).innerText()).includes('AI DRAFT — CHECK SAVED CONTEXT')
  result.salaryRefusal = (await (await ask('What salary does a candidate want?')).locator('.citation-list button').count()) === 0
  await newScope('corpus')
  const found = await ask('Find candidates with Python evidence')
  result.corpusCitations = await found.locator('.citation-list button').count()
  const roleSearch = await ask('Which candidates are most relevant for this Data Scientist position?')
  result.roleSearchCitations = await roleSearch.locator('.citation-list button').count()
  result.roleSearchBasis = (await roleSearch.innerText()).includes('no selected JD or match run')
  await found.locator('.citation-list button').first().click()
  const dialog = page.getByRole('dialog', { name: 'Resume source passage' })
  await dialog.locator('mark').waitFor()
  result.corpusSource = (await dialog.locator('mark').innerText()).includes('Python')
  await page.keyboard.press('Escape')
  const histories = await (await page.request.get('http://127.0.0.1:5173/api/chat/conversations')).json()
  const corpusConversation = await (await page.request.get(`http://127.0.0.1:5173/api/chat/conversations/${histories[0].id}`)).json()
  const deepCitation = corpusConversation.messages.at(-1).citations[0]
  const deepSource = await (await page.request.get(`http://127.0.0.1:5173/api/candidates/${deepCitation.candidate_id}/source`)).json()
  const deepSpan = deepSource.spans.find(item => item.id === deepCitation.span_id)
  const deepLink = deepCitation.deep_link
  await page.goto(`http://127.0.0.1:5173${deepLink}`)
  await page.getByRole('dialog', { name: 'Resume source passage' }).locator('mark').waitFor()
  result.deepLink = (await page.getByRole('dialog', { name: 'Resume source passage' }).locator('mark').innerText()) === deepSource.text.slice(deepSpan.start_offset, deepSpan.end_offset)
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Match workbench' }).click()
  await page.getByRole('button', { name: 'Analyze role' }).click()
  await page.getByText('Python', { exact: true }).first().waitFor()
  await page.getByRole('button', { name: /Run candidate match/ }).click()
  await page.getByText('Top 10 of 30 analyzed').waitFor({ timeout: 60000 })
  await page.getByRole('button', { name: 'AI Chat' }).click()
  await newScope('run')
  result.runScope = (await page.locator('.chat-main .surface-heading').innerText()).includes('ACTIVE SCOPE · RUN')
  result.runNeedsCandidate = /(?:select|choose) a candidate/i.test(await (await ask('Explain the match score.')).innerText())
  await newScope('candidate')
  const header = await page.locator('.chat-main .surface-heading h2').innerText()
  const python = await ask('What Python evidence supports this candidate?')
  result.pythonKind = await python.locator('span').first().innerText()
  result.pythonOnly = (await python.locator('.citation-list button').allInnerTexts()).every(value => value.includes('Python') && !value.includes('SQL'))
  await ask('What about AWS?')
  result.followupScope = (await page.locator('.chat-main .surface-heading h2').innerText()) === header
  await page.getByLabel('Compare with candidate').selectOption({ index: 1 })
  const comparison = await ask('Compare Python evidence.')
  result.comparisonCitations = await comparison.locator('.citation-list button').count()
  result.score = (await (await ask('Explain the match score and its limitations.')).innerText()).includes('AI DRAFT — CHECK SAVED CONTEXT')
  await page.screenshot({ path: resolve('../output/recruiter-chat-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  result.mobileFits = await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)
  await page.screenshot({ path: resolve('../output/recruiter-chat-mobile.png'), fullPage: true })
  if (!result.generalScope || !result.evaluation || !result.product || !result.salaryRefusal || !result.corpusCitations || !result.roleSearchCitations || !result.roleSearchBasis || !result.corpusSource || !result.deepLink || !result.runScope || !result.runNeedsCandidate || !result.pythonOnly || !result.followupScope || !result.comparisonCitations || !result.score || !result.mobileFits) { process.stdout.write(JSON.stringify(result, null, 2) + '\n'); throw new Error('One or more assistant assertions failed') }
  writeFileSync(resolve('../evaluation/recruiter_chat_browser_smoke_results.json'), JSON.stringify(result, null, 2) + '\n')
  process.stdout.write(JSON.stringify(result, null, 2) + '\n')
} finally { await browser.close() }
