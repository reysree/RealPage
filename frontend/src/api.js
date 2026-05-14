const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

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

  if (!response.ok) {
    throw new Error(`Run failed with ${response.status}`)
  }

  return response.json()
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
