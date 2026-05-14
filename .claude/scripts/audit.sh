#!/usr/bin/env bash
# Auto-audit hook — runs after each Claude turn via the Stop hook in settings.json.
# Detects changed .py / .jsx / .js files since the last run and checks only what changed.
# Results are appended to .claude/audit.log and printed to the terminal.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SENTINEL="$ROOT/.claude/scripts/.audit-sentinel"
LOG="$ROOT/.claude/audit.log"

# First run: create sentinel and exit — no baseline to compare against yet.
if [ ! -f "$SENTINEL" ]; then
  touch "$SENTINEL"
  exit 0
fi

# Find code files modified after the last audit run.
CHANGED=$(find "$ROOT/backend" "$ROOT/frontend/src" \
  -newer "$SENTINEL" \
  \( -name "*.py" -o -name "*.jsx" -o -name "*.js" \) \
  ! -path "*/.venv/*" \
  ! -path "*/.venv-evals/*" \
  ! -path "*/node_modules/*" \
  2>/dev/null || true)

if [ -z "$CHANGED" ]; then
  echo ""
  echo "=== Auto-audit $(date '+%Y-%m-%d %H:%M:%S') ==="
  echo "[PASS] No code files changed since last audit — all checks passed."
  echo ""
  exit 0
fi

# Advance sentinel before running so any edits Claude makes during the audit
# don't re-trigger on the next turn.
touch "$SENTINEL"

# Resolve Python interpreter: prefer project venvs, fall back to system.
PYTHON=""
for candidate in \
  "$ROOT/backend/.venv-evals/Scripts/python" \
  "$ROOT/backend/.venv-evals/bin/python" \
  "$ROOT/backend/.venv/Scripts/python" \
  "$ROOT/backend/.venv/bin/python"; do
  if [ -f "$candidate" ]; then
    PYTHON="$candidate"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  PYTHON=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo "python")
fi

run_audit() {
  echo ""
  echo "=== Auto-audit $(date '+%Y-%m-%d %H:%M:%S') ==="
  echo "Changed files:"
  echo "$CHANGED" | sed 's|'"$ROOT/"'||' | sed 's/^/  /'

  PY_CHANGED=$(echo "$CHANGED" | grep "\.py$" || true)
  JS_CHANGED=$(echo "$CHANGED" | grep -E "\.(jsx|js)$" || true)

  # ── Python checks ────────────────────────────────────────────────────────
  if [ -n "$PY_CHANGED" ]; then
    echo ""
    echo "--- Python ---"
    SYNTAX_OK=true

    while IFS= read -r f; do
      [ -z "$f" ] && continue
      if "$PYTHON" -m py_compile "$f" 2>&1; then
        echo "[PASS] syntax: $(basename "$f")"
      else
        echo "[FAIL] syntax: $f"
        SYNTAX_OK=false
      fi
    done <<< "$PY_CHANGED"

    # Import check: run from repo root so backend.* package paths resolve correctly.
    if $SYNTAX_OK; then
      cd "$ROOT"
      for module in schemas tools agent main; do
        if PYTHONPATH="$ROOT" "$PYTHON" -c "import backend.${module}" 2>/dev/null; then
          echo "[PASS] import: backend.${module}"
        else
          echo "[FAIL] import: backend.${module}"
          PYTHONPATH="$ROOT" "$PYTHON" -c "import backend.${module}" 2>&1 | sed 's/^/       /'
        fi
      done
    fi
  fi

  # ── Frontend checks ──────────────────────────────────────────────────────
  if [ -n "$JS_CHANGED" ]; then
    echo ""
    echo "--- Frontend ---"
    if [ -d "$ROOT/frontend/node_modules" ]; then
      cd "$ROOT/frontend"
      if npm run lint 2>&1; then
        echo "[PASS] eslint"
      else
        echo "[FAIL] eslint — fix errors above before continuing"
      fi
      cd "$ROOT"
    else
      echo "[SKIP] node_modules not installed — run: cd frontend && npm install"
    fi
  fi

  echo ""
  echo "=== Audit complete ==="
  echo ""
}

# Run audit, tee to log and terminal.
run_audit 2>&1 | tee -a "$LOG"
