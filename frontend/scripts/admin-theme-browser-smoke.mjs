import { chromium } from 'playwright'
import { execFileSync, spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve('..')
const output = resolve('../output/design_qa/after')
mkdirSync(output, { recursive: true })
const dbPath = resolve(output, `admin-qa-${Date.now()}.db`)
const adminPassword = `Admin-qa-${crypto.randomUUID()}!`
const recruiterPassword = `Recruiter-qa-${crypto.randomUUID()}!`
const testEnv = { ...process.env, RESUMEINTEL_DB: dbPath, RESUMEINTEL_ALLOWED_ORIGIN: 'http://127.0.0.1:5174' }
const createUsers = `
import json, sys
from backend.db import connect, init_db
from backend.auth import HASHER
passwords = json.load(sys.stdin)
init_db()
with connect() as db:
    for email, name, role, password in [
        ('visual-admin@example.test', 'Visual Admin', 'admin', passwords['admin']),
        ('visual-recruiter@example.test', 'Visual Recruiter', 'recruiter', passwords['recruiter']),
    ]:
        db.execute('INSERT INTO users(email,display_name,password_hash,role) VALUES(?,?,?,?)',
                   (email, name, HASHER.hash(password), role))
`
execFileSync('python', ['-c', createUsers], {
  cwd: root,
  env: testEnv,
  input: JSON.stringify({ admin: adminPassword, recruiter: recruiterPassword }),
  stdio: ['pipe', 'ignore', 'pipe'],
})

const api = spawn('python', ['-m', 'uvicorn', 'backend.api:app', '--host', '127.0.0.1', '--port', '8001'], { cwd: root, env: testEnv, stdio: 'ignore', windowsHide: true })
const vite = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5174'], {
  cwd: resolve('.'),
  env: { ...process.env, RESUMEINTEL_API_TARGET: 'http://127.0.0.1:8001' },
  stdio: 'ignore',
  windowsHide: true,
})
async function waitFor(url) {
  for (let attempt = 0; attempt < 120; attempt++) {
    try { if ((await fetch(url)).ok) return } catch { /* Server is still starting. */ }
    await new Promise(resolve => setTimeout(resolve, 500))
  }
  throw new Error(`Server did not start: ${url}`)
}
let browser
try {
  await Promise.all([waitFor('http://127.0.0.1:8001/openapi.json'), waitFor('http://127.0.0.1:5174/signin')])
  browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const checks = []
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('http://127.0.0.1:5174/signin')
  await page.getByLabel('Email').fill('visual-admin@example.test')
  await page.getByLabel('Password').fill(adminPassword)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.getByRole('heading', { name: /Recruiting, with the source/ }).waitFor()
  await page.getByRole('button', { name: 'Users', exact: true }).click()
  await page.getByRole('heading', { name: 'Local users.' }).waitFor()
  if (await page.locator('.user-row').count() !== 2) throw new Error('Admin list did not show both isolated users')
  for (const mode of ['light', 'dark']) for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
    await page.getByLabel('Appearance theme').selectOption(mode)
    await page.evaluate(() => scrollTo(0, 0))
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
    if (overflow > 2) throw new Error(`Admin ${mode} ${width} overflow: ${overflow}px`)
    await page.screenshot({ path: resolve(output, `admin-users-${mode}-${width}.png`) })
    checks.push(`Admin users ${mode} ${width}: two real local users, no overflow`)
  }
  await page.getByLabel('Role for visual-admin@example.test').selectOption('recruiter')
  await page.getByRole('alert').waitFor()
  checks.push('Last admin demotion rejected visibly')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: resolve(output, 'admin-last-admin-error-dark-390.png') })
  await page.getByRole('button', { name: 'AI gateway on' }).click()
  await page.getByRole('button', { name: 'AI gateway off' }).waitFor()
  if (await page.getByRole('button', { name: 'Send test' }).isEnabled()) throw new Error('Gateway test remained enabled in fallback mode')
  await page.screenshot({ path: resolve(output, 'gateway-off-dark-390.png') })
  checks.push('Gateway fallback switch and disabled test control visible')
  await page.getByRole('button', { name: 'Match workbench' }).click()
  await page.getByRole('heading', { name: 'A shortlist with reasons' }).waitFor()
  await page.screenshot({ path: resolve(output, 'match-empty-dark-390.png') })
  checks.push('Empty match state visible')
  await page.locator('.upload-button input').setInputFiles({
    name: 'visual-qa.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('ID,Resume_str,Resume_html,Category\nvisual-qa-1,"Software developer with Python project work and SQL coursework.",,INFORMATION-TECHNOLOGY\n'),
  })
  await page.locator('.import-status progress').waitFor({ timeout: 60000 })
  await page.waitForFunction(() => document.querySelector('.import-status progress')?.value === 1, null, { timeout: 60000 })
  await page.screenshot({ path: resolve(output, 'import-status-dark-390.png') })
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.getByLabel('Appearance theme').selectOption('light')
  await page.evaluate(() => scrollTo(0, 0))
  await page.screenshot({ path: resolve(output, 'import-status-light-1440.png') })
  checks.push('Isolated CSV import status and final count visible')
  if (errors.length) throw new Error(`Page errors: ${errors.join(' | ')}`)
  writeFileSync(resolve(output, 'admin-theme-browser-results.json'), JSON.stringify({ browser: 'Chrome', checks, pageErrors: errors }, null, 2) + '\n')
  process.stdout.write(JSON.stringify({ browser: 'Chrome', checks: checks.length, pageErrors: errors.length }, null, 2) + '\n')
} finally {
  if (browser) await browser.close()
  api.kill()
  vite.kill()
}
