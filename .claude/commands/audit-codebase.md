# Audit Codebase

Run a structural and correctness audit of the entire codebase.
Use after completing any implementation phase, when the Stop hook reports a failure,
or before handing off to the Audit Agent.

## Steps

Run each check in order. Report every item as `[PASS]`, `[FAIL]`, `[WARN]`, or `[SKIP]`.
Skip only when the relevant layer has not been built yet (e.g. skip `agent.py` import if Phase 4 is not started).

---

### 1. File Structure

Verify each file in the Module Registry exists:

| File | Status |
|------|--------|
| `backend/schemas.py` | |
| `backend/db.py` | |
| `backend/agent.py` | |
| `backend/main.py` | |
| `backend/tools/__init__.py` | |
| `backend/tools/search.py` | |
| `backend/tools/calculate.py` | |
| `backend/data/sample.json` | |
| `frontend/src/App.jsx` | |
| `frontend/src/api.js` | |

Use the Bash tool: `[ -f <path> ] && echo EXISTS || echo MISSING`

---

### 2. Python Syntax

Run `py_compile` on every `.py` file in `backend/` (skip `.venv/`):

```bash
find backend -name "*.py" ! -path "*/.venv/*" -exec python -m py_compile {} \; 2>&1
```

Use `backend/.venv/Scripts/python` (Windows) or `backend/.venv/bin/python` (Unix) if plain `python` is not in PATH.
A single syntax error is a `[FAIL]` — show the file and line.

---

### 3. Python Imports

Run from the `backend/` directory so relative imports resolve. Check each file that exists:

```bash
cd backend
python -c "from schemas import ChatRequest, ChatResponse, MessageRecord, HealthResponse; print('ok')"
python -c "from db import init_db, save_message, get_history, clear_session; print('ok')"
python -c "from tools import ALL_TOOLS; print(f'{len(ALL_TOOLS)} tools registered')"
python -c "from agent import run_agent; print('ok')"
python -c "import main; print('ok')"
```

Any `ImportError` or `ModuleNotFoundError` is a `[FAIL]`. Show the full error — it tells you which dependency or symbol is broken.

---

### 4. Tool Count

After step 3, confirm `len(ALL_TOOLS) >= 2`. Fewer than 2 is a `[WARN]` — one or more tools may not be registered.

---

### 5. sample.json Validity

```bash
cd backend
python -c "
import json, sys
data = json.load(open('data/sample.json'))
assert len(data) >= 6, f'Only {len(data)} records — need at least 6'
required = {'id', 'text', 'metadata'}
for i, r in enumerate(data):
    missing = required - r.keys()
    assert not missing, f'Record {i} missing keys: {missing}'
print(f'{len(data)} records, all keys present')
"
```

`[FAIL]` if invalid JSON, fewer than 6 records, or any record missing `id`/`text`/`metadata`.

---

### 6. Frontend Lint

```bash
cd frontend && npm run lint
```

`[PASS]` if exit 0. `[FAIL]` with the lint output if non-zero.
If `node_modules` is absent, note `[BLOCKED] — run npm install first` and skip.

---

### 7. Recall File Coverage

For each phase that has deliverables present on disk (determined by step 1), check that a recall file exists in `recall/` matching that phase number.

```bash
ls recall/ 2>/dev/null || echo "(no recall/ directory)"
```

`[WARN]` for any phase where deliverables exist but no `recall/..._phaseN.md` is found.

---

## Output Format

```
=== Codebase Audit — YYYY-MM-DD HH:MM ===

File Structure
  [EXISTS ] backend/schemas.py
  [MISSING] backend/agent.py
  ...

Python Syntax
  [PASS] All 5 files clean

Python Imports
  [PASS] schemas — ChatRequest, ChatResponse, MessageRecord, HealthResponse
  [FAIL] tools — ModuleNotFoundError: No module named 'chromadb'
  [SKIP] agent — file not yet created

Tool Count
  [WARN] 0 tools registered — ALL_TOOLS may be empty

sample.json
  [PASS] 8 records, all keys present

Frontend Lint
  [PASS] 0 errors, 0 warnings

Recall Coverage
  [PASS] Phase 1 — recall file found
  [WARN] Phase 2 — db.py exists but no recall/*_phase2.md found

=== Summary: 12 checks — 8 passed, 1 failed, 2 warnings, 1 skipped ===
```

## If blocked

- **Python not found:** use `backend/.venv/Scripts/python` (Windows) or `backend/.venv/bin/python` (Unix)
- **chromadb / openai not installed:** run `pip install -r backend/requirements.txt` inside the venv
- **node_modules missing:** run `cd frontend && npm install`
- **A check fails due to missing dependency, not bad code:** mark `[BLOCKED]` and continue remaining checks
