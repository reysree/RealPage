# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## 5. Anti-Sycophancy

**Tell the truth. Don't perform enthusiasm.**

Before answering or implementing:
- If the user is wrong about a fact, API, or assumption, correct it plainly - then give the accurate version or fix.
- If a requested approach is insecure, brittle, or needlessly complex, say so - and propose a simpler or safer alternative.
- Skip flattery, cheerleading, and generic praise ("great question", "excellent idea") unless it is tied to a specific substantive reason.
- When tradeoffs are bad, say they are bad - don't reframe downsides as upsides to keep the user comfortable.
- If you do not know, say you do not know - do not sound confident just to reassure.

The test: Would a careful colleague with no stake in your mood say the same thing? If no, revise.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

**Anti-sycophancy is working if:** you give the same blunt, technical answer you would if the user were not watching - no extra praise, no false agreement, no confidence you did not earn.

---

# RealPage Lumina

## Project

AI-native property management platform. The agent IS the application — handling leasing intelligence, resident services, operational queries, and analytics through a tool-driven agent architecture. Layers swap independently; interface contracts never change.

**Stack:** FastAPI · OpenAI Agents SDK · ChromaDB · SQLite · React + Tailwind

---

## Agent Registry

Fixed responsibilities. Do not add agents without updating this table and the Harness Inventory below.

| Agent | File | Runs when | Skills it reads | Outputs |
|-------|------|-----------|-----------------|---------|
| Solution Architect | `.cursor/agents/solution-architect.md` | Phase 0; major requirement changes | `architecture-decision-skill`, `openai-sdk-guide`, `recall` | `recall/YYYYMMDD_HHMM_architect_phase0.md` + `logs/` checkpoint |
| Developer | `.cursor/agents/distinguished-engineer.md` | Phases 1–5; fixing audit flags | `python-guide`, `openai-sdk-guide`, `react-guide`, `tdd`, `recall` | `logs/YYYYMMDD_HHMM_developer_phaseN.md` |
| Security Analyst | `.cursor/agents/security-analyst.md` | After each developer phase; before gate opens | `security-analyst-guide`, `recall` | `logs/YYYYMMDD_HHMM_security-analyst_phaseN.md` |
| Audit | *(not yet created)* | After each developer phase | `python-guide`, `tdd`, `recall` | `logs/YYYYMMDD_HHMM_audit_phaseN.md` |
| UX Writer | `.cursor/agents/ux-writer.md` | UI copy, labels, errors, onboarding | *(none — self-contained)* | Copy delivered inline |
| Prompt Engineer | `.cursor/agents/prompt-engineer.md` | Write/review agent system prompts and `@function_tool` docstrings | `recall` | `logs/YYYYMMDD_HHMM_prompt-engineer_<descriptor>.md` |

**Gate rule:** Phase N does not open until `developer_phaseN` = COMPLETE and `security_phaseN` = PASS and `audit_phaseN` = PASS with no FAIL items.

---

## Claude Harness Inventory

Everything in `.claude/`. Update this table whenever a file is added or removed.

### Agents — `.cursor/agents/`

| File | Role | Invoke via |
|------|------|-----------|
| `solution-architect.md` | Phase 0 architecture decisions; produces build contract | Ask Cursor to act as Solution Architect |
| `distinguished-engineer.md` | Phases 1–5 implementation; reads architect recall | Ask Cursor to act as Developer Agent |
| `security-analyst.md` | Post-phase security audit; produces PASS/FAIL/PARTIAL report covering OWASP, AI security, PII, SOC2, GDPR, Fair Housing Act | Ask Cursor to act as Security Analyst |
| `ux-writer.md` | UI copy, button labels, error messages, onboarding flows | Ask Cursor to act as UX Writer |
| `prompt-engineer.md` | Write/review system prompts and `@function_tool` docstrings; anti-pattern audit of agent files | Ask Cursor to act as Prompt Engineer |
| *(audit_agent.md — not yet created)* | Post-phase correctness verification; produces PASS/FAIL audit report | — |

### Skills — `.cursor/skills/`

Skills are reference documents agents read before acting. They are not slash commands.

| Folder | Purpose | Read by |
|--------|---------|---------|
| `architecture-decision-skill/` | Architecture pattern selection, tool design, phase planning | Solution Architect |
| `openai-sdk-guide/` | OpenAI Agents SDK patterns, `@function_tool`, `Runner` usage | Architect, Developer |
| `python-guide/` | Python coding standards, type hints, error handling, logging | Developer, Audit |
| `react-guide/` | React + Vite patterns for the frontend | Developer (Phase 5) |
| `tdd/` | Behavior-first red-green-refactor workflow for features and bug fixes | Developer, Audit |
| `recall/` | Checkpoint protocol — how to read and write `logs/` files | All agents |
| `security-analyst-guide/` | Security audit rules: OWASP Top 10, AI security, PII, SOC2, GDPR, Fair Housing Act, logging, dependencies | Security Analyst |
| `harness-guide/` | Cursor harness best practices — agents, hooks, skills, CLAUDE.md | Used when configuring the harness |

### Commands — `.cursor/commands/`

Commands are slash commands invoked during a session.

| File | Command | What it does |
|------|---------|-------------|
| `audit-codebase.md` | `/audit-codebase` | Full structural + correctness audit: file existence, Python syntax, imports, ESLint, recall coverage |
| `recall.md` | `/recall` | Write a checkpoint to `logs/` at phase or task completion |

### Scripts — `.cursor/hooks/`

Shell scripts called by hooks. Do not invoke manually.

| File | Called by | What it does |
|------|-----------|-------------|
| `audit.sh` | Stop hook | Detects changed `.py`/`.jsx`/`.js` files since last run; runs syntax + import + ESLint checks; logs to `.claude/audit.log` |
| `pre-write-check.sh` | PreToolUse → Write hook | Searches for an existing file with the same name; blocks the Write and redirects to Edit if a duplicate is found |

### Hooks — `.cursor/hooks.json`

| Event | Matcher | Script | Effect |
|-------|---------|--------|--------|
| `PreToolUse` | `Write` | `pre-write-check.sh` | Blocks duplicate file creation |
| `Stop` | *(all turns)* | `audit.sh` | Auto-audits changed files after every Cursor agent turn |

---

## Recall Protocol

**Every agent reads this at the start of a task. Every agent writes a checkpoint at the end.**

Full protocol and file format: `.cursor/skills/recall/SKILL.md`

### At the start of any agent call
Run `ls logs/ | sort | tail -5` and read the latest checkpoint file.
Extract: what is COMPLETE, what files exist, what was verified, what is next.
If `logs/` is empty or absent, read the latest architect decision in `recall/`. If that doesn't exist, run the Solution Architect Agent first.

### At the end of any phase or task
Run `/recall` to write a checkpoint to `logs/`.
File naming: `logs/YYYYMMDD_HHMM_<agent>_<descriptor>.md`
Status must be `COMPLETE` only if verification commands were actually run and passed.

### Checkpoint must contain
1. **Task** — what this phase/task was trying to accomplish
2. **Completed** — every file created or modified, with one sentence each
3. **Verified** — exact commands run and their output
4. **Open questions** — anything unresolved
5. **Next** — concrete next action, named agent, named file
6. **Status** — COMPLETE | PARTIAL | BLOCKED

---

## Coding Standards

### Every `.py` file — header required
```python
"""
File: <filename>
Purpose: <one sentence>
Author: Sreeram
"""
```

### Every class
```python
class MyClass:
    """
    What this represents. Why it exists. What it owns.
    """
```

### Every function
```python
def my_function(param: type) -> type:
    """
    What it does. Why it exists.

    Args:
        param: what it is and why needed
    Returns:
        what comes back and what it represents
    """
```

### Every `@function_tool`
```python
@function_tool
def tool_name(param: str) -> str:
    """
    TOOL: <name>
    Purpose: <what it does for the agent — one sentence>
    When called: <specific user intent or situation that triggers this tool>
    Returns: {"field": type, "field": type}  # actual JSON shape, not prose
    Note: Atomic — one responsibility, no overlap with other tools.
    """
```

All four fields are required. `When called` must differ from `Purpose` —
it names the trigger, not the action. `Returns` must show the JSON structure,
not describe it in a sentence.

### Boundary rules
- FastAPI routes: input and output are Pydantic models — no raw dicts
- Tools: all inputs/outputs typed — no untyped returns
- Config: no hardcoded strings — use settings object or env vars
- DB access: agent never accesses DB directly — only through tools

### Error handling — every tool
```python
try:
    result = do_the_thing()
    logger.info(f"[{tool_name}] session={session_id} input={input!r}")
    return json.dumps({"result": result})
except Exception as e:
    logger.error(f"[{tool_name}] session={session_id} error={e}", exc_info=True)
    return json.dumps({"error": str(e), "result": None})
```

---

## Audit Report Format

```
Phase: N
Status: PASS | FAIL | PARTIAL
Items:
  [ PASS ] File headers present on all .py files
  [ FAIL ] Tool X missing atomicity note in docstring
  [ FLAG ] Function Y has no error handling — review required
Action required: <specific fixes if FAIL or PARTIAL>
```

---

## Module Registry

Update when any file is added or removed.

```
backend/
    main.py          → FastAPI app: routes, CORS, lifespan startup
    agent.py         → Agent definition, system prompt, tool registration
    db.py            → SQLite session and message persistence
    schemas.py       → Pydantic models for all API boundaries
    tools/
        __init__.py  → ALL_TOOLS list — the only place tools are registered
        search.py    → search_knowledge_base (ChromaDB semantic search)
        calculate.py → calculate (deterministic numeric operations)
    data/
        sample.json  → Seed data loaded into ChromaDB at startup

frontend/
    src/App.jsx      → Chat UI: message thread, tool badges, input
    src/api.js       → sendMessage() and clearSession() — no fetch() in components
    src/main.jsx     → React DOM entry point
    src/index.css    → Tailwind directives

.claude/
    agents/          → solution-architect.md, distinguished-engineer.md, security-analyst.md, ux-writer.md, prompt-engineer.md
    skills/          → python-guide, openai-sdk-guide, architecture-decision-skill, react-guide, tdd, recall, security-analyst-guide, harness-guide
    commands/        → audit-codebase.md, recall.md
    scripts/         → audit.sh (Stop hook), pre-write-check.sh (PreToolUse hook)
    settings.json    → hooks: PreToolUse(Write), Stop

recall/              → Architect phase0 decision documents (human-approved architecture)

logs/                → Agent checkpoint files — one per phase per agent, written via /recall
                       Read at start of every agent call; written at end via /recall

documents/           → Project documents: plans, architecture diagrams, research, PRDs, ADRs
                       Freeform — no naming convention enforced
```

---

## Scale Considerations

| Component     | Current        | Trigger                              | Upgrade Path                 |
|---------------|----------------|--------------------------------------|------------------------------|
| Session store | SQLite         | Multi-process deployment             | Redis or Postgres            |
| Vector store  | ChromaDB       | Multi-tenant / high-volume ingestion | Pinecone or pgvector         |
| Agent layer   | Single agent   | Domain complexity                    | Multi-agent with handoffs    |
| Deployment    | Local uvicorn  | Any multi-user production workload   | Containerized, load-balanced |
| Observability | Python logging | Behavioral drift or latency SLAs     | LangSmith or OpenTelemetry   |

---

## MCP Documentation Servers

Not yet connected. Use `.cursor/skills/` files as the source of truth for API references. Never invent API signatures from memory.
