import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const currentDir = dirname(fileURLToPath(import.meta.url))
const sampleJsonlPath = resolve(currentDir, '../../backend/data/sample.jsonl')
const sampleJsonl = readFileSync(sampleJsonlPath, 'utf-8').trim()

async function attachRenderedOutput(page, testInfo, name) {
  const outputText = await page.locator('.output-panel').innerText()
  await testInfo.attach(`${name}-output.txt`, {
    body: outputText,
    contentType: 'text/plain',
  })
  await testInfo.attach(`${name}-screenshot.png`, {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png',
  })
}

test('runs pasted JSONL cases through the browser workflow', async ({ page }, testInfo) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Outreach eval runner' })).toBeVisible()
  await page.getByLabel('JSON cases').fill(sampleJsonl)

  await page.getByRole('button', { name: 'Run all' }).click()

  await expect(page.getByText('Finished 2 cases')).toBeVisible()
  await expect(page.getByRole('button', { name: /prospect_welcome_day0/ })).toContainText('PASS')
  await expect(page.getByRole('button', { name: /prospect_long_horizon_day3/ })).toContainText('PASS')

  await expect(page.getByTestId('summary-should-send')).toHaveText('true')
  await expect(page.getByTestId('summary-channel')).toHaveText('sms')
  await expect(page.getByTestId('summary-compliance')).toHaveText('PASS')
  await expect(page.locator('.output-panel')).toContainText('"channel": "sms"')
  await expect(page.locator('.output-panel')).toContainText('Reply STOP to opt out')

  await page.getByRole('button', { name: /prospect_long_horizon_day3/ }).click()

  await expect(page.getByTestId('summary-channel')).toHaveText('email')
  await expect(page.locator('.output-panel')).toContainText('"channel": "email"')
  await expect(page.locator('.output-panel')).toContainText('"subject": "Tour Oak Ridge Apartments"')

  await attachRenderedOutput(page, testInfo, 'jsonl-run-all')
})

test('runs the selected pasted JSON case', async ({ page }, testInfo) => {
  const firstCase = JSON.parse(sampleJsonl.split('\n')[0])

  await page.goto('/')
  await page.getByLabel('JSON cases').fill(JSON.stringify(firstCase, null, 2))
  await page.getByRole('button', { name: 'Run selected' }).click()

  await expect(page.getByText(`Finished ${firstCase.task_id}`)).toBeVisible()
  await expect(page.getByTestId('summary-should-send')).toHaveText('true')
  await expect(page.getByTestId('summary-channel')).toHaveText('sms')
  await expect(page.getByTestId('summary-compliance')).toHaveText('PASS')

  await attachRenderedOutput(page, testInfo, 'single-json-run-selected')
})
