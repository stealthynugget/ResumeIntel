import { chromium } from 'playwright'
import { resolve } from 'node:path'
import { writeFileSync } from 'node:fs'

const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const email = `smoke-${Date.now()}@example.test`
const password = `Long-test-${crypto.randomUUID()}!`
const results = {}
try {
  await page.goto('http://127.0.0.1:5173/dashboard', { waitUntil: 'networkidle' })
  await page.getByRole('heading', { name: 'Welcome back' }).waitFor()
  results.protectedRoute = true
  await page.getByRole('button', { name: /Create an account/ }).click()
  await page.getByLabel('Display name').fill('Browser Reviewer')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Create account' }).click()
  await page.getByRole('heading', { name: /Recruiting, with the source/ }).waitFor()
  results.signup = true
  results.dashboardCorpus = await page.locator('.metric-card.accent strong').innerText()
  await page.getByRole('button', { name: 'Evaluation' }).click()
  await page.getByRole('heading', { name: /What the ranking evidence shows/ }).waitFor()
  results.evaluationCards = await page.locator('.eval-card').count()
  results.hrDisclosure = await page.locator('.disclosure').innerText()
  await page.getByRole('button', { name: 'Match workbench' }).click()
  await page.getByRole('button', { name: 'Analyze role' }).click()
  await page.getByText('Python', { exact: true }).first().waitFor()
  await page.getByRole('button', { name: /Run candidate match/ }).click()
  await page.getByText('Top 10 of 30 analyzed').waitFor({ timeout: 60000 })
  results.matchCandidates = await page.locator('.candidate-card').count()
  await page.getByRole('button', { name: 'Generate review' }).click()
  await page.locator('.ai-review-result').waitFor({ timeout: 60000 })
  results.reviewFallback = (await page.locator('.ai-review-result').innerText()).includes('Evidence-only fallback')
  await page.getByRole('button', { name: 'AI Chat' }).click()
  await page.getByRole('heading', { name: 'Ask the evidence.' }).waitFor()
  await page.getByRole('button', { name: 'New conversation' }).click()
  await page.getByLabel('Question about this candidate and role').fill('What Python evidence supports this candidate?')
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await page.locator('.chat-message.assistant').waitFor({ timeout: 60000 })
  results.chatFallback = (await page.locator('.chat-message.assistant').innerText()).includes('EVIDENCE-ONLY FALLBACK')
  results.chatCitations = await page.locator('.chat-message.assistant .citation-list button').count()
  if (results.chatCitations) {
    await page.locator('.chat-message.assistant .citation-list button').first().click()
    await page.getByRole('dialog', { name: 'Resume source passage' }).waitFor()
    await page.locator('.source-dialog mark').waitFor()
    results.exactSourceHighlight = await page.locator('.source-dialog mark').count()
    await page.keyboard.press('Escape')
  }
  await page.getByRole('button', { name: 'Profile', exact: false }).count().catch(() => 0)
  await page.locator('.account-button').click()
  await page.getByRole('heading', { name: 'Profile & security.' }).waitFor()
  results.accountPage = true
  await page.getByRole('button', { name: 'Sign out' }).click()
  await page.getByRole('heading', { name: 'Welcome back' }).waitFor()
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.getByRole('heading', { name: /Recruiting, with the source/ }).waitFor()
  results.signin = true
  await page.getByRole('button', { name: 'AI Chat' }).click()
  await page.locator('.conversation-list button').first().waitFor()
  results.historyAfterLogin = await page.locator('.conversation-list button').count()
  await page.screenshot({ path: resolve('../output/full-browser-smoke.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  results.mobileChatFits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2)
  await page.getByRole('button', { name: 'Match workbench' }).click()
  results.mobileWorkbenchFits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2)
  await page.screenshot({ path: resolve('../output/full-browser-mobile.png'), fullPage: true })
  if (!results.reviewFallback || !results.chatFallback || !results.chatCitations || !results.exactSourceHighlight || results.evaluationCards !== 3 || !results.historyAfterLogin || !results.mobileChatFits || !results.mobileWorkbenchFits) throw new Error(JSON.stringify(results))
  writeFileSync(resolve('../evaluation/full_browser_smoke_results.json'), JSON.stringify(results, null, 2) + '\n')
  console.log(JSON.stringify(results, null, 2))
} finally {
  await browser.close()
}
