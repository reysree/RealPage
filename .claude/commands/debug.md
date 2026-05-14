# Debug — Evidence-first workflow

Structured debugging using a **37% evidence** rule: spend the first
chunk of your budget gathering facts; do not jump to fixes.

Invoked with free text: error message, symptom, test name, or file path (`$ARGUMENTS`).

**Conventions:** Run **Python** and **pytest** from the **repo root** (`realpage/`).
Use the **PowerShell** tool on Windows. Frontend scripts run from `frontend/`.

---

## Phase 1 — Gather evidence (~37% of time budget)

1. **Reproduce**

   Backend (from repo root):

   ```powershell
   # repo root: realpage/
   pytest tests/ -q
   pytest tests/test_eval_runner.py -q
   pytest tests/ -q -k "pattern_in_test_name"
   ```

   JSONL eval harness (when the bug is eval/scoring):

   ```powershell
   python -m backend.evals.runner
   python -m backend.evals.runner   # requires OPENAI_API_KEY for composer + judge
   ```

   API (manual repro):

   ```powershell
   uvicorn backend.main:app --reload
   ```

   Frontend:

   ```powershell
   Set-Location frontend
   npm run dev
   ```

   E2E (if relevant):

   ```powershell
   Set-Location frontend
   npm run test:e2e
   ```

2. **Capture exactly**

   - Full error text (copy/paste — no paraphrase)
   - Complete stack trace
   - Browser devtools errors (if UI)

3. **Record the session** — create `logs/YYYYMMDD_HHMM_debug_<short-slug>.md` (git-ignored; same spirit as `/recall`). Use this skeleton:

   ```markdown
   ## Debug Session: $ARGUMENTS

   ### Error
   [Exact message]

   ### Stack trace
   ```
   [Full trace]
   ```

   ### Hypotheses (ordered by likelihood)
   1. … — ~60%
   2. … — ~25%
   3. … — ~15%

   ### Evidence
   - [ ] Trace captured
   - [ ] Repro confirmed
   - [ ] Related code read
   - [ ] Git history checked
   ```

4. **Context**

   ```powershell
   git log --oneline -10 -- path/to/file
   git blame path/to/file
   ```

   Search the repo (ripgrep if available):

   ```powershell
   rg -n "error_keyword" backend tests
   rg -n "error_keyword" frontend/src
   ```

---

## Phase 2 — Systematic investigation

5. **Test the highest-likelihood hypothesis first** (common bugs before exotic ones).

6. **Temporary instrumentation**

   - Python: short `logger.debug(...)` or guarded prints — **remove before commit**.
   - Frontend: same for `console.log` — **remove before commit**.

7. **Targeted re-runs**

   ```powershell
   pytest tests/path_to_file.py -q --tb=long
   ```

8. **Update hypotheses** when evidence changes — confirm, reject, reorder.

---

## Phase 3 — Win-stay, lose-shift

9. **Win-stay:** if the current line of investigation works, continue on it.

10. **Lose-shift:** after **three** failed hypotheses, stop and re-gather evidence (wider surface).

---

## Phase 4 — Fix and verify

11. **Fix the root cause** — minimal, surgical diff (match `CLAUDE.md` / `.cursor/rules`).

12. **Regression test** — add or extend a case under `tests/` that would have failed before the fix.

13. **Strip debug noise**

    ```powershell
    rg -n "DEBUG|console\.log|print\(" path/you/changed
    ```

14. **Verify**

    ```powershell
    pytest tests/ -q
    python -m backend.evals.runner
    ```

    Frontend:

    ```powershell
    Set-Location frontend
    npm run lint
    npm run build
    ```

---

## Evidence rules

- Do not hide failures or soften error text.
- Paste **exact** messages and traces into the debug log or chat.
- Record what you tried and **why** it failed.

---

## Copernican principle

If a bug already burned a long time, expect more time unless you change approach (different layer, fresh repro, different hypothesis).

---

## Quick symptom map (this repo)

| Symptom | Where to look |
|--------|----------------|
| Eval threshold / personalization failures | `backend/evals/runner.py`, fixtures in `backend/data/sample.jsonl`, `sample.json` |
| API 4xx/5xx on `/run` | `backend/main.py`, `backend/agent.py`, `backend/schemas/` |
| Composer / OpenAI errors | `backend/tools/message_composer.py`, `backend/.env`, `OPENAI_API_KEY`; eval CLI uses live compose |
| Compliance / opt-out / URL blocks | `backend/tools/compliance.py`, `backend/core/url_security.py`, `backend/core/content_policy.py` |
| Frontend cannot reach API | `frontend/src/api.js`, CORS, base URL, `uvicorn` running |
| Hydration / client-only issues | React 19 + Vite: avoid non-deterministic render (`Date.now` in render, etc.) |
