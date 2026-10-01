import { chromium } from 'playwright'
import { resolve } from 'node:path'

const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
const page = await browser.newPage({ viewport: { width: 1366, height: 850 } })
const result = {}
try {
  await page.goto('http://127.0.0.1:5174/signup', { waitUntil: 'networkidle' })
  await page.getByLabel('Display name').fill('Isolated Browser Check')
  await page.getByLabel('Email').fill(`category-smoke-${Date.now()}@example.test`)
  await page.getByLabel('Password').fill('long-isolated-test-passphrase')
  await page.getByRole('button', { name: 'Create account' }).click()
  await page.waitForTimeout(1000)
  if (await page.getByRole('button', { name: 'Match workbench' }).count() === 0) throw new Error(`Signup failed: ${(await page.locator('main').innerText()).slice(0, 500)}`)
  const gatewaySwitch = page.getByRole('button', { name: 'AI gateway on' })
  await gatewaySwitch.click()
  result.gatewayOff = await page.getByRole('button', { name: 'AI gateway off' }).getAttribute('aria-pressed') === 'false'
  await page.getByRole('button', { name: 'AI gateway off' }).click()
  result.gatewayOn = await page.getByRole('button', { name: 'AI gateway on' }).getAttribute('aria-pressed') === 'true'
  await page.getByRole('button', { name: 'Send test' }).click()
  await page.getByText(/Gateway replied from aicredits\.in/).waitFor({ timeout: 30000 })
  result.liveGatewayProbe = true
  await page.getByRole('button', { name: 'Match workbench' }).click()
  const role = page.getByLabel('Example role')
  result.roleOptions = await role.locator('option').count()
  await role.selectOption('hr_analyst')
  result.hrRole = (await page.getByLabel('Job description').inputValue()).startsWith('HR Analyst')
  await role.selectOption('it_infrastructure_engineer')
  result.itRole = (await page.getByLabel('Job description').inputValue()).startsWith('IT Infrastructure Engineer')
  await page.locator('.upload-button input[type=file]').setInputFiles([
    resolve('../output/browser-upload-1.pdf'), resolve('../output/browser-upload-2.pdf'),
  ])
  await page.getByText('2 selected: 2 new, 0 duplicate, 0 failed.', { exact: false }).waitFor({ timeout: 90000 })
  result.multiplePdfs = (await page.locator('.corpus-state').innerText()).includes('2 resumes indexed')
  await role.selectOption('data_scientist')
  await page.getByRole('button', { name: 'Analyze role' }).click()
  await page.getByRole('button', { name: /Run candidate match/ }).click()
  await page.getByText('Top 2 of 2 analyzed', { exact: false }).waitFor({ timeout: 90000 })
  await page.getByRole('button', { name: 'AI gateway on' }).click()
  await page.getByRole('button', { name: 'Generate brief' }).click()
  await page.locator('.ai-review-result').waitFor({ timeout: 30000 })
  result.offBriefFallback = (await page.locator('.ai-review-result').innerText()).includes('Evidence-only fallback')
  await page.getByRole('button', { name: 'AI gateway off' }).click()
  const [reviewResponse] = await Promise.all([
    page.waitForResponse(response => response.url().includes('/ai-review'), { timeout: 60000 }),
    page.getByRole('button', { name: 'Generate brief' }).click(),
  ])
  result.onBriefFormat = (await reviewResponse.json()).response_format
  if (result.onBriefFormat !== 'fallback') {
    const [freshResponse] = await Promise.all([
      page.waitForResponse(response => response.url().includes('/ai-review?refresh=true'), { timeout: 60000 }),
      page.getByRole('button', { name: 'Refresh brief' }).click(),
    ])
    const fresh = await freshResponse.json()
    result.freshBriefRequest = fresh.cached === false && fresh.response_format !== 'fallback'
  } else result.freshBriefRequest = false
  result.onBriefLabel = (await page.locator('.ai-review-result').innerText()).includes('AI draft') ? 'AI draft' : 'Evidence-only fallback'
  await page.getByRole('button', { name: 'Evaluation' }).click()
  await page.getByRole('heading', { name: 'Corpus coverage by job family' }).waitFor()
  result.categoryRows = await page.locator('.category-table tbody tr').count()
  result.proxyRows = await page.locator('.category-table').nth(1).locator('tbody tr').count()
  await page.setViewportSize({ width: 390, height: 844 })
  result.mobileFits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2)
  if (!result.gatewayOff || !result.gatewayOn || !result.liveGatewayProbe || result.roleOptions !== 28 || !result.hrRole || !result.itRole || !result.multiplePdfs || !result.offBriefFallback || !result.freshBriefRequest || result.onBriefLabel !== 'AI draft' || result.categoryRows !== 25 || result.proxyRows !== 24 || !result.mobileFits) {
    throw new Error(`Browser assertions failed: ${JSON.stringify(result)}`)
  }
  process.stdout.write(JSON.stringify(result) + '\n')
} finally {
  await browser.close()
}
