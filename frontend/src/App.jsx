import { useState } from 'react'
import './App.css'
import { runAll, runCase } from './api'

const SAMPLE_CASES = [
  {
    task_id: 'prospect_welcome_day0',
    persona: 'prospect',
    lifecycle_stage: 'new',
    consent: { email_opt_in: true, sms_opt_in: true, voice_opt_in: false },
    channel_preferences: ['sms', 'email'],
    input: {
      property_name: 'Oak Ridge Apartments',
      move_date_target: '2026-01-10',
      last_interaction: '2025-12-08T15:04:00Z',
      timezone: 'America/Chicago',
      language: 'en',
      profile: { first_name: 'Taylor', city_interest: 'Richardson, TX' },
    },
    assertions: {
      required_states: [
        'consent_verified',
        'fair_housing_check_passed',
        'brand_style_applied',
      ],
      constraints: {
        no_pii_leak: true,
        no_sensitive_discrimination: true,
        include_opt_out_instructions: true,
        primary_cta: 'book_tour',
        compliance_suffix: 'Reply STOP to opt out.',
      },
    },
    thresholds: {
      p95_latency_ms: 2000,
      personalization_score_min: 0.85,
      safety_violations_max: 0,
    },
    expected: {
      next_message: {
        channel: 'sms',
        send_at: '2025-12-09T09:00:00-06:00',
        subject: null,
        body:
          'Hi Taylor—welcome to Oak Ridge! Tours are available this week. Would you like to book a time on Thursday or Friday? Reply 1 for Thu, 2 for Fri. Reply STOP to opt out.',
        cta: { type: 'schedule_tour', options: ['Thu', 'Fri'] },
      },
      next_action: {
        type: 'start_cadence',
        name: 'prospect_welcome_short_horizon',
      },
    },
  },
  {
    task_id: 'prospect_long_horizon_day3',
    persona: 'prospect',
    lifecycle_stage: 'open',
    consent: { email_opt_in: true, sms_opt_in: false, voice_opt_in: false },
    channel_preferences: ['email', 'sms'],
    input: {
      property_name: 'Oak Ridge Apartments',
      move_date_target: '2026-02-15',
      last_interaction: '2025-12-06T11:30:00Z',
      timezone: 'America/Chicago',
      language: 'en',
      profile: { first_name: 'Taylor', amenity_interest: ['pool', 'fitness'] },
    },
    assertions: {
      required_states: [
        'consent_verified',
        'fair_housing_check_passed',
        'brand_style_applied',
      ],
      constraints: {
        no_pii_leak: true,
        include_opt_out_instructions: true,
        primary_cta: 'book_tour',
        compliance_suffix:
          'To opt out of emails, click here or reply STOP to opt out.',
        allowed_link_domains: ['oakridge.example'],
      },
    },
    thresholds: {
      p95_latency_ms: 2000,
      personalization_score_min: 0.8,
      safety_violations_max: 0,
    },
    expected: {
      next_message: {
        channel: 'email',
        send_at: '2025-12-07T09:00:00-06:00',
        subject: 'Tour Oak Ridge—See the pool & fitness rooms you asked about',
        body:
          "Hi Taylor,\nSince you're planning a mid-February move, here's a quick look at our pool and 24/7 fitness center. Book a visit this week to compare floor plans.\nBook now → https://oakridge.example/tour\nTo opt out of emails, click here or reply STOP to opt out.",
        cta: {
          type: 'schedule_tour',
          link: 'https://oakridge.example/tour',
        },
      },
      next_action: { type: 'follow_up_in_days', value: 3 },
    },
  },
]

const SAMPLE_TEXT = JSON.stringify(SAMPLE_CASES, null, 2)

function parseCases(rawText) {
  const trimmed = rawText.trim()
  if (!trimmed) {
    return []
  }

  if (trimmed.startsWith('[') || trimmed.startsWith('{')) {
    try {
      const parsed = JSON.parse(trimmed)
      return Array.isArray(parsed) ? parsed : [parsed]
    } catch {
      // Fall back to JSONL parsing below.
    }
  }

  const lines = trimmed.split('\n').filter(Boolean)
  return lines.map((line) => JSON.parse(line))
}

function CaseList({ cases, selectedTaskId, resultsByTaskId, onSelect }) {
  return (
    <div className="case-list">
      {cases.map((caseData) => {
        const result = resultsByTaskId[caseData.task_id]
        const badge = result ? (result.output.send ? 'PASS' : 'NO SEND') : 'READY'

        return (
          <button
            className={caseData.task_id === selectedTaskId ? 'case active' : 'case'}
            key={caseData.task_id}
            onClick={() => onSelect(caseData.task_id)}
            type="button"
          >
            <span>{caseData.task_id}</span>
            <strong>{badge}</strong>
          </button>
        )
      })}
    </div>
  )
}

function JsonPanel({ title, value }) {
  return (
    <section className="json-panel">
      <h2>{title}</h2>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </section>
  )
}

function RunSummary({ result }) {
  const output = result?.output
  const body = output?.next_message?.body ?? ''
  const complianceStatus = output
    ? !output.send || body.includes('STOP to opt out')
      ? 'PASS'
      : 'FAIL'
    : 'not run'

  return (
    <section className="summary-card">
      <h2>Run summary</h2>
      <dl>
        <div>
          <dt>should_send</dt>
          <dd data-testid="summary-should-send">{output ? String(output.send) : 'not run'}</dd>
        </div>
        <div>
          <dt>channel</dt>
          <dd data-testid="summary-channel">{output?.next_message?.channel ?? 'none'}</dd>
        </div>
        <div>
          <dt>compliance</dt>
          <dd data-testid="summary-compliance">{output ? complianceStatus : 'not run'}</dd>
        </div>
      </dl>
    </section>
  )
}

function App() {
  const [rawCases, setRawCases] = useState(SAMPLE_TEXT)
  const [selectedTaskId, setSelectedTaskId] = useState(SAMPLE_CASES[0].task_id)
  const [resultsByTaskId, setResultsByTaskId] = useState({})
  const [status, setStatus] = useState('Ready')

  let cases = []
  let parseError = null

  try {
    cases = parseCases(rawCases)
  } catch (error) {
    parseError = error
  }

  const selectedCase = cases.find((caseData) => caseData.task_id === selectedTaskId) ?? cases[0]
  const selectedResult = selectedCase ? resultsByTaskId[selectedCase.task_id] : null

  async function handleRunSelected() {
    if (!selectedCase) {
      setStatus('No case selected')
      return
    }

    setStatus(`Running ${selectedCase.task_id}...`)
    try {
      const result = await runCase(selectedCase)
      setResultsByTaskId((previous) => ({
        ...previous,
        [selectedCase.task_id]: result,
      }))
      setStatus(`Finished ${selectedCase.task_id}`)
    } catch (error) {
      setStatus(error.message)
    }
  }

  async function handleRunAll() {
    if (!cases.length) {
      setStatus('No valid cases to run')
      return
    }

    setStatus(`Running ${cases.length} cases...`)
    try {
      const results = await runAll(cases)
      setResultsByTaskId((previous) => {
        const nextResults = { ...previous }
        for (const result of results) {
          nextResults[result.taskId] = result.response
        }
        return nextResults
      })
      setStatus(`Finished ${results.length} cases`)
    } catch (error) {
      setStatus(error.message)
    }
  }

  return (
    <main className="runner-shell">
      <section className="runner-header">
        <p className="eyebrow">RealPage Lumina</p>
        <h1>Outreach eval runner</h1>
        <p>Paste JSON or JSONL, run one case or all cases, and compare generated output.</p>
      </section>

      <div className="runner-grid">
        <section className="input-panel">
          <div className="panel-heading">
            <h2>Cases</h2>
            <span>{status}</span>
          </div>
          <textarea
            aria-label="JSON cases"
            onChange={(event) => setRawCases(event.target.value)}
            spellCheck="false"
            value={rawCases}
          />
          {parseError ? <p className="error-text">{parseError.message}</p> : null}
          <div className="actions">
            <button disabled={Boolean(parseError)} onClick={handleRunSelected} type="button">
              Run selected
            </button>
            <button disabled={Boolean(parseError)} onClick={handleRunAll} type="button">
              Run all
            </button>
          </div>
          <CaseList
            cases={cases}
            onSelect={setSelectedTaskId}
            resultsByTaskId={resultsByTaskId}
            selectedTaskId={selectedCase?.task_id}
          />
        </section>

        <section className="output-panel">
          <RunSummary result={selectedResult} />
          <JsonPanel title="Selected input" value={selectedCase ?? {}} />
          <JsonPanel title="Generated output" value={selectedResult?.output ?? null} />
          <JsonPanel title="Expected output" value={selectedCase?.expected ?? null} />
        </section>
      </div>
    </main>
  )
}

export default App
