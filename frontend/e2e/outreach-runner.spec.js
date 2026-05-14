import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const currentDir = dirname(fileURLToPath(import.meta.url))
const sampleJsonlPath = resolve(currentDir, '../../backend/data/sample.jsonl')
const sampleJsonl = readFileSync(sampleJsonlPath, 'utf-8').trim()
const sampleCases = sampleJsonl.split('\n').map((line) => JSON.parse(line))

async function attachRenderedOutput(page, testInfo, name) {
  const outputText = await page.getByTestId('generated-output').innerText()
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

  await expect(page.getByRole('heading', { name: 'Case runner' })).toBeVisible()
  await page.getByLabel('Case JSON or JSONL').fill(sampleJsonl)

  await page.getByRole('button', { name: 'Run', exact: true }).click()

  await expect(page.getByTestId('generated-output')).toContainText('"channel": "sms"')
  await expect(page.getByTestId('generated-output')).toContainText('Reply STOP to opt out')
  await expect(page.getByTestId('generated-output')).toContainText('prospect_long_horizon_day3')
  await expect(page.getByTestId('generated-output')).toContainText('"channel": "email"')

  await attachRenderedOutput(page, testInfo, 'jsonl-run-all')
})

test('runs a single pasted JSON case', async ({ page }, testInfo) => {
  const firstCase = sampleCases[0]

  await page.goto('/')
  await page.getByLabel('Case JSON or JSONL').fill(JSON.stringify(firstCase, null, 2))
  await page.getByRole('button', { name: 'Run', exact: true }).click()

  await expect(page.getByTestId('generated-output')).toContainText('"channel": "sms"')
  await expect(page.getByTestId('generated-output')).toContainText('Reply STOP to opt out')

  await attachRenderedOutput(page, testInfo, 'single-json-run')
})

test('renders no-send result for all opted out case', async ({ page }, testInfo) => {
  const noSendCase = sampleCases.find((item) => item.task_id === 'prospect_all_opted_out')

  await page.goto('/')
  await page.getByLabel('Case JSON or JSONL').fill(JSON.stringify(noSendCase, null, 2))
  await page.getByRole('button', { name: 'Run', exact: true }).click()

  await expect(page.getByTestId('generated-output')).toContainText('"send": false')
  await expect(page.getByTestId('generated-output')).toContainText('"next_message": null')
  await expect(page.getByTestId('generated-output')).toContainText('"pipeline_blocked"')

  await attachRenderedOutput(page, testInfo, 'no-send-run')
})

test('shows sanitized API validation error for invalid case', async ({ page }) => {
  const invalidCase = {
    ...sampleCases[0],
    input: {
      ...sampleCases[0].input,
      profile: {
        ...sampleCases[0].input.profile,
        first_name: 'fuck',
      },
    },
  }

  await page.goto('/')
  await page.getByLabel('Case JSON or JSONL').fill(JSON.stringify(invalidCase, null, 2))
  await page.getByRole('button', { name: 'Run', exact: true }).click()

  await expect(page.getByTestId('generated-output')).toContainText('"error": "Run failed"')
  await expect(page.getByTestId('generated-output')).toContainText('"message"')
  await expect(page.getByTestId('generated-output')).not.toContainText('fuck')
})

test('clear resets input and output', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Case JSON or JSONL').fill('{"task_id":"x"}')
  await page.getByRole('button', { name: 'Clear' }).click()

  await expect(page.getByLabel('Case JSON or JSONL')).toHaveValue('')
  await expect(page.getByTestId('generated-output')).toContainText('Run a case to see output here.')
})

test('rejects invalid JSON with error message', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Case JSON or JSONL').fill('{invalid json')

  // Verify that invalid JSON disables the Run button
  const runButton = page.getByRole('button', { name: 'Run', exact: true })
  await expect(runButton).toBeDisabled()

  // Verify that the output panel shows the parse error
  await expect(page.getByTestId('generated-output'))
    .toContainText('"error"', { timeout: 5000 })
})
