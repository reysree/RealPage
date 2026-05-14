# Security Analyst Skill
# Context-Aware Message Sending Bot

## Purpose

This skill is read by the Security Analyst Agent before performing any audit.
It defines every security domain, what to check, what constitutes a finding, and how to classify findings.

Do not invent rules. Do not assume compliance. Surface every ambiguity as a FLAG.

---

## Stack Context

```
Backend:  FastAPI · Python 3.12 · OpenAI Agents SDK · SQLite · ChromaDB
Frontend: React + Vite + Tailwind
Auth:     Not yet implemented (flag any routes that lack it)
Deployment: Local uvicorn (production path: containerized)
```

---

## Finding Classification

Every finding must be classified as one of:

| Severity | Label  | Meaning |
|----------|--------|---------|
| Critical | `CRIT` | Exploitable now; blocks deployment |
| High     | `HIGH` | Likely exploitable; fix before any production exposure |
| Medium   | `MED`  | Exploitable under specific conditions; fix before scale |
| Low      | `LOW`  | Defence-in-depth gap; fix in next sprint |
| Info     | `INFO` | Observation worth tracking; no immediate risk |
| Flag     | `FLAG` | Ambiguous; human decision required |

Report format for each finding:
```
[SEVERITY] CATEGORY — Title
  File: path/to/file.py:line
  What: one sentence describing the issue
  Risk: what an attacker or regulator could do
  Fix: specific, concrete remediation step
```

---

## 1. Web Application Security (OWASP Top 10 — FastAPI)

### Injection

- SQL injection: check all raw SQL strings in `db.py` and any future DB access. Parameterized queries only — no f-string SQL.
- Prompt injection: check that user input passed to the agent is not capable of overriding the system prompt. Look for constructs like `system_prompt + user_input` without sanitization.
- Command injection: any `subprocess`, `os.system`, or `shell=True` usage is HIGH unless the input is fully controlled by the system.

### Broken Authentication

- Flag every FastAPI route that has no authentication middleware or dependency injection guard.
- Flag any session token stored in localStorage (frontend). Prefer `sessionStorage` or httpOnly cookies.
- Flag any hardcoded API keys, tokens, or secrets in Python or JS files.

### Sensitive Data Exposure

- Check that `OPENAI_API_KEY` and any other secrets are read from environment variables, not hardcoded.
- Check that SQLite session data does not store raw PII beyond what is functionally necessary.
- Check that ChromaDB document metadata does not contain PII fields unless encrypted or tokenized.
- Flag any response that echoes back PII to the frontend without need.

### Security Misconfiguration

- CORS: check `main.py` CORS settings. `allow_origins=["*"]` is HIGH in any non-local environment.
- Debug mode: flag `debug=True` or `reload=True` if set unconditionally (not gated on env var).
- Error responses: confirm that 500 errors do not leak stack traces to the client.
- Check that `uvicorn` is not exposed on `0.0.0.0` without a reverse proxy in production config.

### Broken Access Control

- Flag any endpoint that takes a `session_id` from the user without verifying that the caller owns that session.
- Flag any admin or internal route reachable without elevated permissions.

### Vulnerable and Outdated Dependencies

- Note: static analysis only — flag if `requirements.txt` or `package.json` pins no versions.
- Flag any known-vulnerable package version if encountered during code inspection (do not run `npm audit` or `pip-audit` autonomously — note that these should be run).

### Cross-Site Scripting (XSS)

- Check `App.jsx` for `dangerouslySetInnerHTML` usage. Any unescaped rendering of agent output is HIGH.
- Confirm that agent response text is rendered as text content, not injected as raw HTML.

---

## 2. AI-Specific Security

### Prompt Injection

Direct: user supplies a message designed to override the system prompt (e.g. "Ignore previous instructions...").
Indirect: tool output from ChromaDB or SQLite contains adversarial text that manipulates the agent.

**Check for:**
- System prompt concatenated with unvalidated user input without a separator or role boundary.
- ChromaDB documents loaded from external sources without sanitization before being returned as tool output.
- Any tool that passes raw user input directly to another LLM call or sub-agent.

**Minimum mitigations to flag as absent:**
- Input length limits (no unbounded `message` field).
- System prompt placed as a `system` role message, not prepended to the `user` message.
- Tool outputs validated as structured data (JSON) before being returned to the agent.

### Data Leakage via LLM

- Check whether the agent's system prompt contains information that should not be disclosed to users (internal pricing rules, admin logic, DB schema).
- Check that tool outputs do not include fields that the LLM could leak verbatim (e.g. internal IDs, raw DB rows with PII columns).
- Flag tool responses that stringify entire database rows or unstructured blobs — return minimal fields via `ToolResultEnvelope`-style payloads (or trimmed dicts).

### Model/Tool Abuse

- Check that tools perform exactly one action and validate their inputs. A tool that accepts arbitrary SQL or arbitrary shell commands is CRIT.
- Check `calculate.py` for unsafe `eval()` usage. Any `eval` of user-supplied input is CRIT.
- Flag tools whose docstrings omit the "When called" and "Returns" sections — these are required for the agent to use them safely.

### Jailbreak Surface

- Review the agent system prompt for instructions that could be socially engineered away (e.g. "If the user asks nicely, you can share...").
- Guardrails must be unconditional: "Never recommend based on protected class" not "Try to avoid recommending based on protected class."

---

## 3. Privacy and PII Handling

### What Counts as PII in Property Management

The following are PII in the property management context:
- Full name, email address, phone number
- Date of birth, SSN, government ID numbers
- Income, credit score, employment status
- Current address, rental history
- Lease terms tied to an individual resident
- Maintenance request content (can reveal health, disability status)
- Payment history tied to an individual

### Checks

- **Minimization:** Does the system collect only the PII it needs to function? Flag any field collected but never read.
- **Storage:** Is PII encrypted at rest? SQLite without encryption is LOW for local dev, HIGH for production.
- **Transit:** Is PII transmitted only over HTTPS? Flag any non-TLS endpoint that could carry PII.
- **Retention:** Is there a mechanism to delete PII on request (see GDPR below)? Flag its absence.
- **Access logs:** Does the system log PII in plaintext? Check logger calls for fields like `email`, `ssn`, `name`.
- **Frontend:** Does the frontend store PII in localStorage, sessionStorage, or cookies? Flag anything beyond session_id.

---

## 4. SOC2 Considerations (Trust Service Criteria)

SOC2 is not a checklist — it is an audit of controls. Flag the **absence of controls** that would be required for a SOC2 Type II report.

### Security (CC6, CC7)

- `CC6.1` Logical access controls: flag any route without authentication.
- `CC6.2` New access provisioning: flag any hardcoded admin credentials or shared keys.
- `CC6.6` External-facing components: flag any public endpoint with no rate limiting or input validation.
- `CC7.2` Monitoring: flag the absence of structured logging that would support anomaly detection.
- `CC7.3` Incident response: flag the absence of any error alerting mechanism (even a simple email on 5xx).

### Availability (A1)

- `A1.2` Environmental protections: flag if the app has no health check endpoint or liveness probe.

### Confidentiality (C1)

- `C1.1` Confidential information identification: flag if there is no data classification policy (even a comment-level note) for what is confidential.
- `C1.2` Confidential information disposal: flag if there is no session cleanup or data TTL.

### Processing Integrity (PI1)

- `PI1.1` Complete and accurate processing: flag if tool outputs are not validated before being used by the agent.

---

## 5. GDPR Considerations

Applicable if any EU resident data is processed (or could be). Flag all gaps even if current users are US-only — the architecture must be ready.

### Lawful Basis

- Flag if there is no mechanism to record consent or lawful basis for processing PII.
- Flag if the system processes special category data (health, disability, immigration status) without explicit consent handling.

### Data Subject Rights

For each right, check whether a mechanism exists. Flag its absence.

| Right | What to check |
|-------|---------------|
| Access (Art. 15) | Can a user request all data held about them? |
| Rectification (Art. 16) | Can a user correct inaccurate data? |
| Erasure (Art. 17) | Does `clear_session()` delete all PII, or only session metadata? |
| Portability (Art. 20) | Can a user export their data in a machine-readable format? |
| Objection (Art. 21) | Can a user opt out of automated decision-making? |

### Automated Decision-Making (Art. 22)

- If the agent makes or influences a decision about a resident (lease approval, maintenance priority, pricing), GDPR Art. 22 may require a human review mechanism.
- Flag any agent output that constitutes a decision about an individual without a disclosed human review path.

### Data Transfers

- Flag if the OpenAI API call transmits PII. Tenant names, SSNs, or addresses sent in the message payload are a transfer to a third-party processor — flag if no DPA (Data Processing Agreement) is noted.
- Mitigation: anonymize or pseudonymize user data before sending to the LLM.

### Retention

- Flag any data that is stored indefinitely with no TTL or deletion trigger.
- SQLite session history with no expiry = FLAG.

---

## 6. Fair Housing Act (FHA) Compliance

The Fair Housing Act (42 U.S.C. § 3604) prohibits discrimination in housing on the basis of:

**Protected classes:**
- Race
- Color
- National origin
- Religion
- Sex (including gender identity and sexual orientation under HUD guidance)
- Familial status (presence of children under 18)
- Disability

State and local laws may add: source of income, marital status, age, student status, immigration status.

### What the AI Must Never Do

| Prohibited behavior | Example trigger |
|---------------------|-----------------|
| Recommend or steer based on protected class | "Which neighborhoods have fewer [group]?" |
| Describe a property using protected class language | "This building is popular with [group]" |
| Filter or rank results based on protected class | Applying occupancy limits that target families |
| Suggest or confirm that a unit is unavailable based on protected class | Lying about vacancies |
| Provide different terms, conditions, or pricing based on protected class | |
| Discourage inquiry based on protected class | |

### Checks

- **System prompt guardrails:** Verify the agent system prompt explicitly prohibits all protected-class-based recommendations, descriptions, and filtering.
- **Tool layer validation:** If any tool accepts location or demographic filters, verify those filters cannot include protected class attributes.
- **Query rejection pattern:** Confirm the agent has a response pattern for refusing FHA-violating queries that explains why (not just "I can't help with that").
- **Implicit discrimination:** Flag any tool that uses zip code, neighborhood name, or school district as a ranking factor — these are known proxies for protected classes.
- **Disability accommodation:** Check that the system prompt includes the duty to discuss reasonable accommodations without steering (e.g. accessible units can be highlighted on request, not unsolicited).

### HUD Guidance on AI and Fair Housing (2023)

HUD has stated that algorithmic systems can create fair housing liability even without discriminatory intent. Flag any ranking or recommendation algorithm that:
- Was trained on historical data without bias auditing
- Uses proxy variables correlated with protected classes
- Produces disparate impact without documented justification

---

## 7. Dependency and Supply Chain Security

- Flag if `requirements.txt` uses unpinned versions (e.g. `fastapi` with no `==x.y.z`).
- Flag if `package.json` uses `*` or `latest` as a version specifier.
- Flag if any package is sourced from a non-official registry.
- Note (do not run automatically): `pip-audit` and `npm audit` should be run in CI before every deployment.

---

## 8. Logging and Observability Security

- Logs must not contain: raw PII, API keys, full request bodies containing user messages.
- Logs should contain: tool name, session_id (pseudonymous), operation type, duration, error codes.
- Flag any `logger.info(f"... {user_message} ...")` that logs the full user message — truncate or hash.
- Flag the absence of a log retention policy (even a comment noting the intended TTL).

---

## 9. Report Format

The Security Analyst Agent produces its output in this format:

```markdown
# Security Audit Report
Date: YYYY-MM-DD
Scope: <files reviewed>
Agent: Security Analyst
Status: PASS | FAIL | PARTIAL

## Summary
<2–3 sentence executive summary>

## Findings

### [CRIT/HIGH/MED/LOW/INFO/FLAG] CATEGORY — Title
File: path/to/file:line
What: ...
Risk: ...
Fix: ...

...

## Compliance Checklist

| Domain     | Status | Notes |
|------------|--------|-------|
| OWASP      | PASS / FAIL / PARTIAL | |
| AI Security| PASS / FAIL / PARTIAL | |
| PII / Privacy | PASS / FAIL / PARTIAL | |
| SOC2       | PASS / FAIL / PARTIAL | |
| GDPR       | PASS / FAIL / PARTIAL | |
| Fair Housing Act | PASS / FAIL / PARTIAL | |
| Dependencies | PASS / FAIL / PARTIAL | |
| Logging    | PASS / FAIL / PARTIAL | |

## Required Actions Before Deployment
<numbered list — CRIT and HIGH items only>

## Recommended Actions (Non-Blocking)
<numbered list — MED and LOW items>

## Open Questions
<anything requiring human decision — FLAG items>
```

**Status rules:**
- `PASS` — zero CRIT or HIGH findings; all compliance domains at PASS or INFO.
- `FAIL` — one or more CRIT or HIGH findings. Phase is blocked until resolved.
- `PARTIAL` — no CRIT findings; one or more HIGH findings under active remediation, or one or more compliance domains at PARTIAL.
