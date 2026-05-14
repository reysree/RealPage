# Developer Agent — Context-Aware Message-Sending Bot

## Guard Clauses — Stop Before Acting

Before writing any code, verify all required prerequisites exist:

1. `.claude/skills/python-guide/SKILL.md` — Python coding contract
2. `.claude/skills/openai-sdk-guide/SKILL.md` — Agent/tool coding contract
3. `.claude/skills/tdd/SKILL.md` — behavior-first test workflow for feature and bug work
4. `recall/` — most recent `YYYYMMDD_HHMM_architect_phase0.md` — your build contract

Then read the checkpoint protocol:
5. `.claude/skills/recall/SKILL.md` — how to read existing checkpoints and write new ones

Run `ls logs/ | sort | tail -5` and read the latest checkpoint. If `logs/` is empty or
absent, you are the first agent — proceed from the architect's recall file.

If any file is missing, stop and name the missing file. Do not write a line of code.

---

## Hard Rules

- Do not redesign the architecture — surface disagreements, do not silently change
- Do not skip the recall file — it is the handoff to the Audit Agent
- Do not declare a phase complete without running verification steps
- Do not merge two tool responsibilities into one function
- Do not let the agent touch the database directly
- Do not use raw dicts where a Pydantic model should be

---

## Role

Build what the Solution Architect designed for Phases 1–5. If you disagree with an architectural decision, surface it — do not silently change it.

---

## Workflow — Every Phase

**Before starting:**
1. Read the architect's phase plan from `recall/`
2. State what you are about to build in plain English
3. List the files you will create or modify
4. Get confirmation before proceeding

**While building:**
- Follow CLAUDE.md Section 8 — Coding Standards for every file, class, and function
- For feature and bug work, use `.claude/skills/tdd/SKILL.md` unless the user explicitly asks to skip tests
- Every tool: atomic, one responsibility, no overlap
- Every API boundary: Pydantic model, no raw dicts
- Every tool call: structured error handling and logging

**After completing:**
1. Run the verification steps listed in the phase contract
2. State exactly what you built and what you verified
3. Run `/recall` to write a checkpoint to `logs/` — follow the format in `.claude/skills/recall/SKILL.md`
4. Wait for the Audit Agent to review before declaring phase complete

**If something is unclear:** Stop and ask. Do not guess.

---

## File Size Limits

Backend files must stay under these line counts. A file over its limit is a code-review failure.
If a file is approaching its limit, split it rather than growing it.

| Pattern | Max LOC | Guidance when approached |
|---------|---------|--------------------------|
| `tools/*.py` (single-purpose, atomic) | 250 | Split into a helper module; tools must stay single-responsibility |
| `agent.py` (orchestration only) | 300 | Extract helper logic to `agent_utils.py`; orchestration stays in `agent.py` |
| `main.py` (FastAPI entry point) | 150 | Extract middleware / exception handlers if growing |
| `schemas.py` (Pydantic models) | 500 | Split: `schemas.py` → API models; `schemas_eval.py` → eval-only models |
| `eval_runner.py` (eval harness) | 600 | Extract per-concern helpers; keep `run_case`, `score_output`, `run_all` in one file |
| Utility modules (`url_security.py`, `content_policy.py`, `constants.py`, `audit_log.py`) | 150 | Extract constants to `constants.py` if it grows |
| `compose_fixture_stub.py` | 100 | Stub logic only — no production code |

**Do not add LOC to a file just to stay under the limit.** The limit enforces single-responsibility. If a file is long because it has too many responsibilities, split it; if it is long because one responsibility is genuinely complex, that is acceptable up to the limit.

---

## Phase Contracts

### Phase 1 — Schemas and Interfaces

**Deliver:** `backend/schemas.py` with Pydantic models for every API boundary:
- `ChatRequest` — inbound message from frontend
- `ChatResponse` — agent response to frontend
- `MessageRecord` — single message as stored in SQLite
- `HealthResponse` — GET /health response
- Any domain-specific models identified in Phase 0

**Verify by:**
- `python3 -c "from schemas import ChatRequest, ChatResponse; print('ok')"`
- Every model has a docstring explaining what it represents and why it exists

**Recall must include:** All models and fields; ambiguous fields and how they were resolved.

---

### Phase 2 — Data Layer

**Deliver:**
- `backend/db.py`: `init_db()`, `save_run(task_id, input_json, output_json, scores_json)`, `get_run(task_id)`, `list_runs(limit=50)`
- `backend/data/sample.jsonl`: 2+ JSONL records, each with `task_id`, `persona`, `lifecycle_stage`, `consent`, `channel_preferences`, `input`, `assertions`, `thresholds`, `expected` — matching the structure in the problem statement
- `backend/eval_runner.py`: `load_cases(path)` reads JSONL line-by-line and returns a list of parsed dicts; `run_case(case, agent_fn)` calls the agent and returns `{"task_id", "generated", "expected", "elapsed_ms"}`

**Verify by:**
- `python3 -c "from db import init_db; init_db(); print('ok')"`
- SQLite file created at `backend/runs.db`
- `save_run` and `get_run` round-trip correctly
- `python3 -c "from eval_runner import load_cases; cases = load_cases('data/sample.jsonl'); print(len(cases))"`
- `sample.jsonl` loads without parse errors; each record contains all required fields

**Recall must include:** SQLite schema (table definition); count and task_ids of JSONL cases; eval_runner function signatures.

---

### Phase 3 — Tools

**Deliver:**
- `backend/tools/consent.py` — `check_consent`: given `channel` (str) and `consent` (dict of `{channel}_opt_in` flags), returns `{"channel": str, "eligible": bool, "reason": str}`; never raises — always returns a result
- `backend/tools/channel_selector.py` — `select_channel`: given `channel_preferences` (list[str]) and `consent` (dict), calls `check_consent` for each in order and returns `{"selected_channel": str | null, "fallback_channel": str | null, "rationale": str, "send": bool}`
- `backend/tools/message_composer.py` — `compose_message`: given `channel`, `persona`, `lifecycle_stage`, `profile` (dict), `property_name`, and `primary_cta`, returns `{"subject": str | null, "body": str, "cta": dict}`; uses an LLM call with structured output; never invents consent or channel data
- `backend/tools/timing.py` — `determine_send_time`: given `timezone` (str), `last_interaction` (ISO8601 str), and `lifecycle_stage` (str), returns `{"send_at": str (ISO8601 with offset), "rationale": str}`
- `backend/tools/compliance.py` — `check_compliance`: given `body` (str) and `constraints` (dict), returns `{"passed": bool, "violations": list[str], "required_additions": list[str]}`; checks: no PII leak, no discriminatory language, opt-out instruction present when required
- `backend/tools/__init__.py` — exports `ALL_TOOLS`; this is the only place tool registration happens

**Verify by:**
- `python3 -c "from tools import ALL_TOOLS; print(len(ALL_TOOLS))"`
- Call `check_consent` with `channel="sms"` and `consent={"sms_opt_in": true}` → `{"eligible": true, ...}`
- Call `select_channel` with preferences `["sms", "email"]` and sms blocked → returns email as selected
- Call `determine_send_time` with `timezone="America/Chicago"` → returns a valid ISO8601 timestamp with offset
- Call `check_compliance` with a body missing opt-out → `{"passed": false, "violations": [...], ...}`

**Recall must include:** All tools, input/output schemas, test inputs used, exact outputs received; any tool that could not be verified and why.

---

### Phase 4 — Agent and API

**Deliver:**
- `backend/agent.py`: `messaging_agent` with system prompt + ALL_TOOLS; `run_agent(case_input)` accepts a parsed JSONL case dict and returns `{"send": bool, "channel": str | null, "send_at": str | null, "subject": str | null, "body": str | null, "cta": dict | null, "next_action": dict | null, "tools_used": list[str]}`; system prompt instructs the agent to: infer rules from data, never hardcode channel logic, always call compliance before returning a message, return `{"send": false}` when no channel is eligible
- `backend/main.py`: lifespan startup (`init_db()`); `GET /health`; `POST /run` accepts a JSONL case body and returns agent output; `GET /runs` lists stored run results; CORS for `http://localhost:5173`

**Verify by:**
- `uvicorn main:app --reload` starts without errors
- `curl http://localhost:8000/health` returns `{"status": "ok"}`
- POST the `prospect_welcome_day0` case → agent selects SMS, returns a body with tour CTA and STOP opt-out
- POST the `prospect_long_horizon_day3` case → agent selects email (SMS opt-out blocks SMS), body references pool and fitness

**Recall must include:** Agent system prompt (full text); routes implemented; curl commands and their exact responses.

---

### Phase 5 — Frontend

**Deliver:**
- `frontend/src/App.jsx`: two-panel layout — left panel lists loaded test cases from `sample.jsonl`; right panel shows the selected case's input, generated output, expected output, and per-dimension scores; "Run All" button calls `runAll()`; per-case "Run" button calls `runCase(case)`; pass/fail badge per case in the list
- `frontend/src/api.js`: `runCase(caseData)` POSTs to `/run`; `runAll(cases)` calls `runCase` sequentially and returns results array; no fetch() calls in components

**Verify by:**
- `npm run dev` starts without errors
- Selecting a case shows its input fields
- Running a case shows generated output alongside expected output
- Pass/fail badge updates after run

**Recall must include:** Components built and what each does; manual test steps and results.

---

### Phase 6 — End-to-End Verification

Run these cases from `backend/data/sample.jsonl` via `POST /run`. Record exact input, exact output, and `tools_used` for each:

1. **Consent + channel selection:** `prospect_welcome_day0` — `sms_opt_in: true`, `email_opt_in: true`, preferred channel SMS → agent selects SMS; body contains tour CTA; body ends with opt-out instruction; `tools_used` includes `check_consent`, `select_channel`, `compose_message`, `check_compliance`
2. **Channel fallback:** `prospect_long_horizon_day3` — `sms_opt_in: false`, `email_opt_in: true` → agent selects email (not SMS); body references pool and fitness interests; subject line is present
3. **Compliance enforcement:** craft a case where `include_opt_out_instructions: true` and omit opt-out from a draft message → `check_compliance` must catch violation and trigger a rewrite
4. **No eligible channel:** craft a case where all opt-ins are false → agent returns `{"send": false}` and no message body
5. **Fair Housing guardrail:** craft a case with `no_sensitive_discrimination: true` where profile hints at a protected class → agent produces no discriminatory language; `check_compliance` PASS

**Recall must include:** All 5 cases, exact agent outputs, exact `tools_used` lists; any failures and root cause.

---

## Adding a New Tool

1. Create `backend/tools/<name>.py` with `@function_tool` and full docstring per CLAUDE.md Coding Standards
2. Import in `backend/tools/__init__.py` and add to `ALL_TOOLS`
3. Update Module Registry in CLAUDE.md
4. Update the current phase recall file
5. Add at least one eval case in `backend/data/sample.jsonl` that exercises the new tool

No other files need to change.
