import { chromium } from 'playwright'
import { resolve } from 'node:path'
import { writeFileSync } from 'node:fs'

const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const result = { browser: 'Chrome', flow: 'signup → match → brief → chat → source → mobile' }
const email = `capstone-smoke-${Date.now()}@example.test`
const password = `Long-test-${crypto.randomUUID()}!`
const questions = [
  'Which candidates are most relevant for this Data Scientist position?',
  'Which candidates have Python, SQL and machine learning experience?',
  'What skills are missing for this candidate compared with the job description?',
  'Why was this candidate matched with the role?',
  'Which candidates satisfy the mandatory requirements?',
]

async function ask(question) {
  const previous = await page.locator('.chat-message.assistant').count()
  await page.getByLabel('Your question').fill(question)
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  const answer = page.locator('.chat-message.assistant').nth(previous)
  await answer.waitFor({ timeout: 60000 })
  return answer
}

try {
  await page.goto('http://127.0.0.1:5173/signup', { waitUntil: 'networkidle' })
  await page.getByLabel('Display name').fill('Capstone Smoke')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Create account' }).click()
  await page.getByRole('button', { name: 'Match workbench' }).click()
  await page.getByRole('button', { name: 'Analyze role' }).click()
  await page.getByText('Python', { exact: true }).first().waitFor()
  await page.getByRole('button', { name: /Run candidate match/ }).click()
  await page.getByText('Top 10 of 30 analyzed').waitFor({ timeout: 90000 })
  result.matchRun = true
  await page.getByRole('button', { name: 'Generate brief' }).click()
  await page.getByText('Supported requirements', { exact: true }).waitFor({ timeout: 60000 })
  result.structuredBrief = await page.getByText('Missing, partial, or uncertain').isVisible()
    && await page.getByText('Questions to verify').isVisible()
    && (await page.locator('.brief-counts').innerText()).includes('Required evidence')
  await page.screenshot({ path: resolve('../output/capstone-brief-desktop.png'), fullPage: true })
  await page.getByRole('button', { name: /Ask about this candidate in Chat/ }).click()
  await page.getByRole('heading', { name: 'Ask the evidence.' }).waitFor()
  await page.waitForFunction(() => Boolean(document.querySelector('select[aria-label="Saved match run"]')?.value && document.querySelector('select[aria-label="Matched candidate"]')?.value), { timeout: 15000 })
  result.matchToChat = (await page.getByLabel('Saved match run').inputValue()) !== ''
    && (await page.getByLabel('Matched candidate').inputValue()) !== ''
  result.fiveExamples = (await page.locator('.chat-examples button').allInnerTexts()).join('\n') === questions.join('\n')

  const ranked = await ask(questions[0])
  result.ranked = (await ranked.innerText()).includes('top ranked of 30 analyzed') && await ranked.locator('.citation-list button').count() > 0
  const conjunction = await ask(questions[1])
  result.conjunction = (await conjunction.innerText()).includes('every requested skill') || (await conjunction.innerText()).includes('for each requested skill')
  const gaps = await ask(questions[2])
  result.gaps = (await gaps.innerText()).includes('Required experience and qualifications')
  const why = await ask(questions[3])
  result.why = (await why.innerText()).includes('match index') && await why.locator('.citation-list button').count() > 0
  await why.locator('.citation-list button').first().click()
  const dialog = page.getByRole('dialog', { name: 'Resume source passage' })
  await dialog.locator('mark').waitFor()
  result.sourceHighlight = (await dialog.locator('mark').innerText()).length > 0
  await page.keyboard.press('Escape')
  const mandatory = await ask(questions[4])
  result.mandatory = (await mandatory.innerText()).includes('of 30 analyzed')
  await page.screenshot({ path: resolve('../output/capstone-chat-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  result.mobileFits = await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)
  await page.screenshot({ path: resolve('../output/capstone-chat-mobile.png'), fullPage: true })
  await page.getByRole('button', { name: 'Evaluation' }).click()
  await page.getByText('0.376').first().waitFor()
  result.evaluation = true
  if (Object.values(result).some(value => value === false)) { process.stdout.write(JSON.stringify(result, null, 2) + '\n'); throw new Error('Browser assertion failed') }
  writeFileSync(resolve('../evaluation/capstone_browser_smoke_results.json'), JSON.stringify(result, null, 2) + '\n')
  process.stdout.write(JSON.stringify(result, null, 2) + '\n')
} finally { await browser.close() }
