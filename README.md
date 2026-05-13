# RealPage Lumina

AI-native property management platform. The agent is the application — handling leasing intelligence, resident services, operational queries, and analytics through a tool-driven agent architecture.

## Stack

| Layer | Technology |
|-------|-----------|
| Backend API | FastAPI (Python) |
| Agent runtime | OpenAI Agents SDK |
| Vector store | ChromaDB |
| Session store | SQLite |
| Frontend | React 19 + Vite + Tailwind CSS |

## Project Structure

```
realpage/
├── backend/
│   ├── main.py          # FastAPI app — routes, CORS, lifespan startup
│   ├── agent.py         # Agent definition, system prompt, tool registration
│   ├── db.py            # SQLite session and message persistence
│   ├── schemas.py       # Pydantic models for all API boundaries
│   ├── tools/
│   │   ├── __init__.py  # ALL_TOOLS list — the only place tools are registered
│   │   ├── search.py    # search_knowledge_base (ChromaDB semantic search)
│   │   └── calculate.py # calculate (deterministic numeric operations)
│   ├── data/
│   │   └── sample.json  # Seed data loaded into ChromaDB at startup
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx      # Chat UI — message thread, tool badges, input
│   │   ├── api.js       # sendMessage() and clearSession()
│   │   ├── main.jsx     # React DOM entry point
│   │   └── index.css    # Tailwind directives
│   └── package.json
│
├── .claude/             # Claude Code harness — agents, skills, hooks, commands
├── recall/              # Architect phase-0 decision documents
├── logs/                # Agent checkpoint files (git-ignored)
└── documents/           # Plans, architecture diagrams, PRDs, ADRs
```

## Getting Started

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
uvicorn main:app --reload
```

The API starts at `http://localhost:8000`. Interactive docs at `/docs`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The UI starts at `http://localhost:5173`.

### Environment

Create `backend/.env` (see `.env.example` if present):

```
OPENAI_API_KEY=sk-...
```

## Architecture

The agent is the core of the application. Every user message is routed through the OpenAI Agents SDK runner, which selects tools, executes them, and streams a response. FastAPI handles transport; React renders the conversation thread.

Layers are decoupled — the agent only calls tools, tools only access the DB and vector store, and routes only accept/return Pydantic models. Each layer can be swapped independently.

## Development Workflow

Agent phases are gated: each phase requires a Developer checkpoint (`logs/`), a Security Analyst PASS, and an Audit PASS before the next phase opens. See `CLAUDE.md` for the full agent registry and gate rules.
