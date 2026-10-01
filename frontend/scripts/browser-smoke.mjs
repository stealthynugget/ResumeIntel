import { chromium } from 'playwright'
import { resolve } from 'node:path'
import { writeFileSync } from 'node:fs'

const browser = await chromium.launch({
  executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true,
})
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const result = {}
try {
  await page.goto('http://127.0.0.1:5173/', { waitUntil: 'networkidle' })
  await page.locator('.corpus-state.ready').waitFor()
  result.initialCorpus = Number((await page.locator('.corpus-state.ready').innerText()).replace(/[^0-9]/g, ''))
  if (result.initialCorpus < 2481) throw new Error(`Full CSV corpus is not indexed: ${result.initialCorpus}`)

  await page.locator('input[type="file"]').first().setInputFiles(resolve('../data/source/Resume.csv'))
  await page.getByText('CSV uploaded. Indexing continues in the background').waitFor()
  const duringImport = await page.request.get('http://127.0.0.1:8000/api/health')
  result.healthDuringImport = duringImport.status()
  await page.locator('.import-status-meta').getByText(/completed/).waitFor({ timeout: 120000 })
  result.importStatus = await page.locator('.import-status').innerText()
  if (!result.importStatus.includes('2,483 duplicate') || !result.importStatus.includes('1 invalid')) {
    throw new Error(`Repeated import did not account for every row: ${result.importStatus}`)
  }

  await page.getByRole('button', { name: 'Analyze role' }).click()
  await page.getByText('Python', { exact: true }).first().waitFor()
  result.requirements = await page.locator('.requirement-row').count()
  await page.getByRole('button', { name: /Run candidate match/ }).click()
  await page.getByText('Top 10 of 30 analyzed').waitFor({ timeout: 30000 })
  result.candidates = await page.locator('.candidate-card').count()
  await page.locator('.assessment-list .evidence-link').first().click()
  await page.locator('.source-text .active-source').waitFor()
  result.sourceEvidence = await page.locator('.source-text .active-source').count()
  await page.screenshot({ path: resolve('../output/browser-results.png'), fullPage: true })

  await page.locator('.candidate-card .compare-check input').nth(0).check()
  await page.locator('.candidate-card .compare-check input').nth(1).check()
  await page.getByRole('button', { name: 'Compare selected (2/2)' }).click()
  const dialog = page.getByRole('dialog', { name: 'Candidate comparison' })
  await dialog.waitFor()
  result.dialogRows = await dialog.locator('.compare-row').count()
  result.focusOnOpen = await page.evaluate(() => document.activeElement?.getAttribute('aria-label'))
  await page.keyboard.press('Shift+Tab')
  result.focusWrapped = await page.evaluate(() => document.activeElement?.className)
  await page.screenshot({ path: resolve('../output/browser-compare.png'), fullPage: true })
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'hidden' })
  result.escapeClosed = true
  result.focusRestored = await page.evaluate(() => document.activeElement?.textContent?.includes('Compare selected'))

  await page.getByLabel('Priority for Python').selectOption('preferred')
  result.requirementEditClearedResults = await page.locator('.candidate-card').count() === 0
  await page.getByRole('button', { name: /Run candidate match/ }).click()
  await page.getByText('Top 10 of 30 analyzed').waitFor()
  await page.getByLabel('Job description').fill('Data Scientist revised role with Python and SQL requirements for analysis.')
  result.jdEditClearedResults = await page.locator('.candidate-card').count() === 0
  result.jdEditClearedRequirements = await page.locator('.requirement-row').count() === 0
  await page.screenshot({ path: resolve('../output/browser-smoke.png'), fullPage: true })
  if (result.healthDuringImport !== 200 || result.focusOnOpen !== 'Close comparison' ||
      !result.focusWrapped.includes('compare-evidence') || !result.focusRestored ||
      !result.requirementEditClearedResults || !result.jdEditClearedResults || !result.jdEditClearedRequirements) {
    throw new Error('Stale results remained after an edit')
  }
  writeFileSync(resolve('../evaluation/browser_smoke_results.json'), JSON.stringify(result, null, 2) + '\n')
  console.log(JSON.stringify(result, null, 2))
} finally {
  await browser.close()
}
