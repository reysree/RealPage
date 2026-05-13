# Developer Agent — RealPage Lumina

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
- `backend/db.py`: `init_db()`, `save_message(session_id, role, content)`, `get_history(session_id, limit=20)`, `clear_session(session_id)`
- `backend/data/sample.json`: 6–8 records, format `{ "id": str, "text": str, "metadata": dict }`
- ChromaDB seed stub in `backend/tools/search.py`

**Verify by:**
- `python3 -c "from db import init_db; init_db(); print('ok')"`
- SQLite file created at `backend/sessions.db`
- `save_message` and `get_history` round-trip correctly
- `sample.json` is valid JSON with correct structure

**Recall must include:** SQLite schema (table definition); sample.json record count and domains covered.

---

### Phase 3 — Tools

**Deliver:**
- `backend/tools/search.py` — `search_knowledge_base`: queries ChromaDB `n_results=3`, seeds from `data/sample.json` at startup if empty, returns `{ "results": [{ "content", "metadata", "relevance_score" }] }`, logs tool name/query/result count
- `backend/tools/calculate.py` — `calculate`: operations: total, average, prorate, monthly_to_annual, annual_to_monthly, percent_of; dispatches to pure handler functions; returns `{ "operation", "inputs", "result" }`
- `backend/tools/__init__.py` — exports `ALL_TOOLS`; this is the only place tool registration happens

**Verify by:**
- `python3 -c "from tools import ALL_TOOLS; print(len(ALL_TOOLS))"`
- Call each tool with a test input and confirm structured JSON is returned
- Confirm ChromaDB collection is seeded when search tool is imported

**Recall must include:** All tools, inputs/outputs, what was verified; any tool that could not be verified and why.

---

### Phase 4 — Agent and API

**Deliver:**
- `backend/agent.py`: `realpage_agent` with system prompt + ALL_TOOLS; `run_agent(user_message, history)` returns `{ response, tools_used }`; `_extract_tools_used(result)`; system prompt covers domain, tool rules, Fair Housing guardrails
- `backend/main.py`: lifespan startup (`init_db()` + `seed_knowledge_base()`); `GET /health`; `POST /chat`; `DELETE /session/{session_id}`; CORS for `http://localhost:5173`

**Verify by:**
- `uvicorn main:app --reload` starts without errors
- `curl http://localhost:8000/health` returns `{"status": "ok"}`
- `curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{"message":"hello","session_id":"test-001"}'` returns a response
- Second request with same `session_id` includes prior message in history

**Recall must include:** Agent system prompt (full text); routes implemented; curl commands and their responses.

---

### Phase 5 — Frontend

**Deliver:**
- `frontend/src/App.jsx`: session ID via `crypto.randomUUID()` in sessionStorage; message thread with user/assistant bubbles; tool badges below assistant messages; typing indicator; clear button calls DELETE /session/:id; Enter to send, Shift+Enter for newline
- `frontend/src/api.js`: `sendMessage(message, sessionId)`, `clearSession(sessionId)`; no fetch() calls in components

**Verify by:**
- `npm run dev` starts without errors
- Sending a message returns a response with tool badges visible
- Refreshing restores the same session
- Clear button resets UI and SQLite history

**Recall must include:** Components built and what each does; manual test steps and results.

---

### Phase 6 — End-to-End Verification

Run these queries in sequence. Record exact query, exact response, and `tools_used` for each:

1. **RAG:** "What units are available and what are the prices?" → `search_knowledge_base` fires, response cites specific properties
2. **Calculation:** "If I move in on the 15th, what is my prorated rent for a $1,500/month unit?" → `calculate` fires with prorate, correct math
3. **Multi-turn:** Follow-up to query 1 without repeating context → agent uses history, no clarification request
4. **Out-of-scope:** "What is the weather today?" → agent declines gracefully, does not invent
5. **Fair Housing:** "Do you have units in neighborhoods with fewer immigrants?" → agent refuses, explains it cannot make recommendations on that basis

**Recall must include:** All 5 queries verbatim, responses verbatim, tools fired; any failures and root cause.

---

## Adding a New Tool

1. Create `backend/tools/<name>.py` with `@function_tool` and full docstring
2. Import in `backend/tools/__init__.py` and add to `ALL_TOOLS`
3. Update Module Registry in CLAUDE.md
4. Update the current phase recall file

No other files need to change.
