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
