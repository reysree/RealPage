# RealPage Lumina

Context-aware outreach agent for property management. The agent reads structured prospect records and decides autonomously: whether to communicate, which channel to use, what to say, and when to send. No rules are hardcoded — all logic is inferred from input data.

## Stack

| Layer | Technology |
|-------|-----------|
| Backend API | FastAPI (Python) |
| Message composition | OpenAI SDK (`gpt-4o`) |
| Frontend | React 19 + Vite + Tailwind CSS |

## Project Structure

```
realpage/
├── backend/
│   ├── main.py              # FastAPI app — routes, CORS, health check
│   ├── agent.py             # Stateless outreach orchestration
│   ├── schemas/
│   │   ├── __init__.py      # Re-exports all public types
│   │   ├── models.py        # API/eval Pydantic models (RunRequest, AgentOutput, …)
│   │   ├── types.py         # Wire validators and annotated primitives
│   │   └── llm.py           # LLM JSON output contracts
│   ├── core/
│   │   ├── constants.py     # FAIR_HOUSING_RULES, BRAND_STYLE_GUIDE
│   │   ├── audit_log.py     # Structured operator audit log (NDJSON)
│   │   ├── content_policy.py  # Profanity/extremism screening
│   │   └── url_security.py    # URL/hostname safety helpers
│   ├── evals/
│   │   ├── runner.py        # JSONL eval harness — run cases, score output
│   │   └── fixture_stub.py  # Offline fixture stubs for CI
│   ├── tools/
│   │   ├── __init__.py      # ALL_TOOLS registry
│   │   ├── channel_selector.py
│   │   ├── compliance.py
│   │   ├── consent.py
│   │   ├── input_security.py
│   │   ├── input_security_llm.py
│   │   ├── message_composer.py
│   │   └── timing.py
│   ├── data/
│   │   └── sample.jsonl     # JSONL eval cases with assertions and thresholds
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx          # Eval runner UI
│   │   └── api.js           # runCase() and runAll()
│   └── package.json
│
├── tests/                   # pytest test suite
├── .claude/                 # Claude Code harness — agents, skills, hooks, commands
├── recall/                  # Architect phase-0 decision documents
├── logs/                    # Agent checkpoint files (git-ignored)
└── documents/               # Plans, architecture diagrams, PRDs, ADRs
```

## Getting Started

All commands run from the **repo root** (`realpage/`).

### 1. Environment

Create `backend/.env`:

```
OPENAI_API_KEY=sk-...
```

### 2. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
cd ..
uvicorn backend.main:app --reload
```

API starts at `http://localhost:8000`. Interactive docs at `/docs`.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

UI starts at `http://localhost:5173`.

### 4. Tests

```bash
pytest tests/ -q
```

Excludes live LLM eval tests by default (skipped when `OPENAI_API_KEY` is absent).

### 5. Evals

Run the JSONL eval harness against the bundled sample cases:

```bash
python -m backend.evals.runner
```

By default uses live OpenAI composition. To run offline with fixture stubs (no API key required):

```bash
REALPAGE_EVAL_STUB_COMPOSE=true python -m backend.evals.runner
```

CLI options:

```
python -m backend.evals.runner --help
python -m backend.evals.runner --latency-runs 5   # P95 over 5 timed samples
python -m backend.evals.runner backend/data/sample.jsonl  # explicit path
```

## Architecture

The agent pipeline runs in a fixed sequence for each outreach case:

```
input security → channel selection → consent check → timing → compose → compliance
```

Each step is an in-process tool returning `ToolResultEnvelope`. The pipeline blocks on any failure and returns `send=false` — no partial sends.

Eval cases live in `backend/data/sample.jsonl`. Each case defines `input`, `assertions`, `thresholds`, and `expected` output. The runner scores generated output against expected using compliance checks and an LLM personalization judge.

## Development Workflow

Agent phases are gated: each phase requires a Developer checkpoint (`logs/`), a Security Analyst PASS, and an Audit PASS before the next phase opens. See `CLAUDE.md` for the full agent registry and gate rules.
