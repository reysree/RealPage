const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

function jsonBodyFromResponseText(text) {
  if (!text) {
    return null
  }
  try {
    return JSON.parse(text)
  } catch {
    return { raw: text }
  }
}

export async function getBackendHealth() {
  const response = await fetch(`${API_BASE_URL}/health`)

  if (!response.ok) {
    throw new Error(`Backend returned ${response.status}`)
  }

  return response.json()
}

export async function runCase(caseData) {
  const response = await fetch(`${API_BASE_URL}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(caseData),
  })

  const text = await response.text()
  const parsed = jsonBodyFromResponseText(text)

  if (!response.ok) {
    const body = parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
    const message =
      typeof body.message === 'string' && body.message.trim()
        ? body.message.trim()
        : 'Run failed.'
    const err = new Error('Run failed')
    err.runFailedBody = {
      error: typeof body.error === 'string' && body.error.trim() ? body.error.trim() : 'Run failed',
      message,
    }
    throw err
  }

  return parsed
}

export async function runAll(cases) {
  const results = []

  for (const caseData of cases) {
    results.push({
      taskId: caseData.task_id,
      response: await runCase(caseData),
    })
  }

  return results
}

/**
 * Run the bundled repository `sample.json` cases through the eval harness (backend).
 *
 * @param {number | undefined} latencySampleCount — optional query override (P95 sampling); omit for server default.
 * @returns {Promise<{ total: number, passed: number, failed: number, results: object[], source: string }>}
 */
export async function runEvalSample(latencySampleCount) {
  const params = new URLSearchParams()
  if (latencySampleCount != null && Number.isFinite(latencySampleCount) && latencySampleCount >= 1) {
    params.set('latency_sample_count', String(Math.floor(latencySampleCount)))
  }
  const qs = params.toString()
  const url = `${API_BASE_URL}/eval/run-sample${qs ? `?${qs}` : ''}`
  const response = await fetch(url, { method: 'POST' })

  const text = await response.text()
  const parsed = jsonBodyFromResponseText(text)

  if (!response.ok) {
    const body = parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
    const message =
      typeof body.message === 'string' && body.message.trim()
        ? body.message.trim()
        : 'Eval run failed.'
    const err = new Error('Eval run failed')
    err.evalFailedBody = {
      error: typeof body.error === 'string' && body.error.trim() ? body.error.trim() : 'Eval failed',
      message,
    }
    throw err
  }

  return parsed
}
