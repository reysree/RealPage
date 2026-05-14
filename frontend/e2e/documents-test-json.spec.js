import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const currentDir = dirname(fileURLToPath(import.meta.url))
const testJsonPath = resolve(currentDir, '../../documents/test.json')

test('runs documents/test.json (empty thresholds and expected) in Case runner', async ({ page }) => {
  const raw = readFileSync(testJsonPath, 'utf-8')

  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Case runner' })).toBeVisible()
  await page.getByLabel('Case JSON or JSONL').fill(raw)

  await page.getByRole('button', { name: 'Run', exact: true }).click()

  const out = page.getByTestId('generated-output')
  await expect(out).not.toContainText('"error": "Run failed"', { timeout: 120_000 })
  await expect(out).toContainText('"send": true')
  await expect(out).toContainText('"channel": "email"')
})
