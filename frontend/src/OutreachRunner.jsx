import { useState } from 'react'
import './App.css'
import { runCase, runEvalSample } from './api'

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

/**
 * Shape API results for display: one object if a single case, else an array with task_id on each row.
 */
function formatGeneratedOutput(cases, responses) {
  if (responses.length === 0) {
    return null
  }
  if (responses.length === 1) {
    return responses[0].output
  }
  return responses.map((response, index) => ({
    task_id: cases[index]?.task_id ?? null,
    ...response.output,
  }))
}

/**
 * MessagePreview renders just the composed message atomically by channel type.
 */
function MessagePreview({ output }) {
  if (!output || !output.next_message) {
    return null
  }

  const msg = output.next_message
  const channel = msg.channel?.toLowerCase()

  return (
    <div className="message-preview">
      <div className="message-channel">{channel}</div>
      <div className="message-body">
        {channel === 'email' && msg.subject && (
          <>
            <div className="message-subject">
              <strong>Subject:</strong> {msg.subject}
            </div>
          </>
        )}
        <div className="message-text">{msg.body}</div>
      </div>
    </div>
  )
}

function formatScoreChips(scores) {
  if (!scores || typeof scores !== 'object') {
    return null
  }
  return Object.entries(scores).map(([key, value]) => (
    <span key={key} className={`eval-chip ${value ? 'eval-chip-pass' : 'eval-chip-fail'}`}>
      {key.replace(/_pass$/, '').replaceAll('_', ' ')}: {String(value)}
    </span>
  ))
}

export default function OutreachRunner() {
  const [rawInput, setRawInput] = useState('')
  const [outputText, setOutputText] = useState('')
  const [running, setRunning] = useState(false)
  const [evalReport, setEvalReport] = useState(null)
  const [evalRunning, setEvalRunning] = useState(false)
  const [evalError, setEvalError] = useState(null)

  let cases = []
  let parseError = null

  try {
    cases = parseCases(rawInput)
  } catch (error) {
    parseError = error
  }

  const canRun = Boolean(!parseError && cases.length > 0 && !running)

  const trimmedInput = rawInput.trim()
  const parseErrorJson =
    trimmedInput && parseError
      ? JSON.stringify({ error: parseError.message, stage: 'parse' }, null, 2)
      : null

  const outputPanelText =
    parseErrorJson ?? (outputText ? outputText : null) ?? 'Run a case to see output here.'

  let outputForPreview = null
  if (outputText && !parseErrorJson) {
    try {
      outputForPreview = JSON.parse(outputText)
      if (Array.isArray(outputForPreview)) {
        outputForPreview = outputForPreview[0]
      }
    } catch {
      outputForPreview = null
    }
  }

  async function handleRun() {
    if (!canRun) {
      return
    }

    setRunning(true)
    setOutputText('')
    try {
      const responses = []
      for (const caseData of cases) {
        responses.push(await runCase(caseData))
      }
      const display = formatGeneratedOutput(cases, responses)
      setOutputText(JSON.stringify(display, null, 2))
    } catch (error) {
      const payload =
        error && typeof error === 'object' && error.runFailedBody
          ? error.runFailedBody
          : { error: 'Run failed', message: String(error?.message ?? error) }
      setOutputText(JSON.stringify(payload, null, 2))
    } finally {
      setRunning(false)
    }
  }

  function handleClear() {
    setRawInput('')
    setOutputText('')
  }

  async function handleRunEvalSample() {
    setEvalRunning(true)
    setEvalError(null)
    setEvalReport(null)
    try {
      const report = await runEvalSample(1)
      setEvalReport(report)
    } catch (error) {
      const payload =
        error && typeof error === 'object' && error.evalFailedBody
          ? error.evalFailedBody
          : { error: 'Eval failed', message: String(error?.message ?? error) }
      setEvalError(`${payload.error}: ${payload.message}`)
    } finally {
      setEvalRunning(false)
    }
  }

  return (
    <main className="runner-shell">
      <section className="runner-header">
        <p className="eyebrow">Context-Aware Message Sending Bot</p>
        <h1>Case runner</h1>
        <p>Paste JSON or JSONL, run once, read the generated output. Nothing is stored.</p>
      </section>

      <div className="runner-grid">
        <section className="input-panel">
          <div className="panel-heading">
            <h2>Input</h2>
          </div>
          <textarea
            aria-label="Case JSON or JSONL"
            onChange={(event) => setRawInput(event.target.value)}
            placeholder='Paste one object, an array of cases, or JSONL lines (e.g. from backend/data/sample.jsonl).'
            spellCheck="false"
            value={rawInput}
          />
          <div className="actions">
            <button disabled={!canRun} onClick={handleRun} type="button">
              {running ? 'Running…' : 'Run'}
            </button>
            <button className="button-secondary" onClick={handleClear} type="button">
              Clear
            </button>
          </div>
        </section>

        <section className="output-panel">
          <div className="panel-heading">
            <h2>Generated output</h2>
          </div>
          {outputForPreview && <MessagePreview output={outputForPreview} />}
          <pre className="output-pre" data-testid="generated-output">
            {outputPanelText}
          </pre>
        </section>
      </div>

      <section className="eval-panel" aria-labelledby="eval-heading">
        <div className="panel-heading">
          <h2 id="eval-heading">Evaluation (sample.json)</h2>
        </div>
        <p className="eval-intro">
          Runs all records from the repository root <code>sample.json</code> through the same harness as{' '}
          <code>python -m backend.evals.runner</code> (scores, personalization judge when applicable, P95;
          one latency sample per case from the UI for faster turns).
        </p>
        <div className="actions">
          <button disabled={evalRunning} onClick={handleRunEvalSample} type="button">
            {evalRunning ? 'Running evaluation…' : 'Run evaluation'}
          </button>
        </div>
        {evalError && (
          <div className="eval-error" role="alert">
            {evalError}
          </div>
        )}
        {evalReport && (
          <div className="eval-results">
            <div className="eval-summary">
              <strong>
                Correctness: {evalReport.passed} passed / {evalReport.total} total
              </strong>
              {evalReport.failed > 0 ? (
                <span className="eval-summary-fail"> — {evalReport.failed} failed</span>
              ) : (
                <span className="eval-summary-ok"> — all passed</span>
              )}
              <span className="eval-source"> (source: {evalReport.source})</span>
            </div>
            <div className="eval-table-wrap">
              <table className="eval-table">
                <thead>
                  <tr>
                    <th scope="col">Task</th>
                    <th scope="col">Pass</th>
                    <th scope="col">Scores</th>
                    <th scope="col">Personalization</th>
                    <th scope="col">P95 agent ms</th>
                  </tr>
                </thead>
                <tbody>
                  {evalReport.results.map((row) => (
                    <tr key={row.task_id}>
                      <td className="eval-cell-mono">{row.task_id}</td>
                      <td>{row.passed ? '✓' : '✗'}</td>
                      <td className="eval-cell-chips">{formatScoreChips(row.scores)}</td>
                      <td>
                        {row.personalization_judge_score != null
                          ? row.personalization_judge_score.toFixed(2)
                          : '—'}
                      </td>
                      <td className="eval-cell-mono">
                        {row.latency?.agent_p95_ms != null ? Math.round(row.latency.agent_p95_ms) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>
    </main>
  )
}
