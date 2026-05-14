#!/usr/bin/env bash
# Cursor stop hook - audits changed backend/frontend code after an agent turn.
# Writes full audit output to .cursor/audit.log. Stdout is JSON for Cursor hooks.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SENTINEL="$ROOT/.cursor/hooks/.audit-sentinel"
LOG="$ROOT/.cursor/audit.log"

json_escape() {
  python -c 'import json,sys; print(json.dumps(sys.stdin.read()))' 2>/dev/null || python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'
}

if [ ! -f "$SENTINEL" ]; then
  touch "$SENTINEL"
  echo '{}'
  exit 0
fi

CHANGED="$(find "$ROOT/backend" "$ROOT/frontend/src" \
  \( -path "*/.venv" -o -path "*/.venv/*" -o -path "*/.venv-*" -o -path "*/.venv-*/*" -o -path "*/node_modules" -o -path "*/node_modules/*" \) -prune -o \
  -newer "$SENTINEL" \
  \( -name "*.py" -o -name "*.jsx" -o -name "*.js" \) -print \
  2>/dev/null || true)"

touch "$SENTINEL"

if [ -z "$CHANGED" ]; then
  {
    echo ""
    echo "=== Cursor auto-audit $(date '+%Y-%m-%d %H:%M:%S') ==="
    echo "[PASS] No code files changed since last audit."
  } >> "$LOG"
  echo '{}'
  exit 0
fi

PYTHON="$ROOT/backend/.venv/Scripts/python"
if [ ! -f "$PYTHON" ]; then PYTHON="$ROOT/backend/.venv/bin/python"; fi
if [ ! -f "$PYTHON" ] && command -v python.exe >/dev/null 2>&1; then PYTHON="$(command -v python.exe)"; fi
if [ ! -f "$PYTHON" ]; then PYTHON="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python)"; fi

python_arg_path() {
  case "$PYTHON" in
    *python.exe|*.exe)
      if command -v wslpath >/dev/null 2>&1; then
        wslpath -w "$1"
      elif command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$1"
      else
        echo "$1"
      fi
      ;;
    *)
      echo "$1"
      ;;
  esac
}

PYTHONPATH_FOR_IMPORT="$(python_arg_path "$ROOT")"

TMP="$(mktemp)"
{
  echo ""
  echo "=== Cursor auto-audit $(date '+%Y-%m-%d %H:%M:%S') ==="
  echo "Changed files:"
  echo "$CHANGED" | sed 's|^'"$ROOT"'/||' | sed 's/^/  /'

  PY_CHANGED="$(echo "$CHANGED" | grep "\.py$" || true)"
  JS_CHANGED="$(echo "$CHANGED" | grep -E "\.(jsx|js)$" || true)"

  if [ -n "$PY_CHANGED" ]; then
    echo ""
    echo "--- Python ---"
    SYNTAX_OK=true
    while IFS= read -r f; do
      [ -z "$f" ] && continue
      PY_FILE="$(python_arg_path "$f")"
      if "$PYTHON" -m py_compile "$PY_FILE" </dev/null 2>&1; then
        echo "[PASS] syntax: $(basename "$f")"
      else
        echo "[FAIL] syntax: $f"
        SYNTAX_OK=false
      fi
    done <<< "$PY_CHANGED"

    if $SYNTAX_OK && [ -d "$ROOT/backend" ]; then
      for module in backend.schemas backend.db backend.tools backend.agent backend.main; do
        module_file="$ROOT/${module//.//}.py"
        module_dir="$ROOT/${module//.//}"
        [ -f "$module_file" ] || [ -d "$module_dir" ] || continue
        if PYTHONPATH="$PYTHONPATH_FOR_IMPORT" "$PYTHON" -c "import ${module}" 2>/dev/null; then
          echo "[PASS] import: ${module}"
        else
          echo "[FAIL] import: ${module}"
          PYTHONPATH="$PYTHONPATH_FOR_IMPORT" "$PYTHON" -c "import ${module}" 2>&1 | sed 's/^/       /'
        fi
      done
    fi
  fi

  if [ -n "$JS_CHANGED" ]; then
    echo ""
    echo "--- Frontend ---"
    if [ -d "$ROOT/frontend/node_modules" ]; then
      cd "$ROOT/frontend" || exit 0
      if npm run lint 2>&1; then
        echo "[PASS] eslint"
      else
        echo "[FAIL] eslint - fix errors above before continuing"
      fi
      cd "$ROOT" || exit 0
    else
      echo "[SKIP] node_modules not installed - run: cd frontend && npm install"
    fi
  fi

  echo ""
  echo "=== Audit complete ==="
} > "$TMP" 2>&1

cat "$TMP" >> "$LOG"

if grep -q "\[FAIL\]" "$TMP"; then
  SUMMARY="$(sed -n '1,80p' "$TMP")"
  MSG="Cursor auto-audit found failures after the last turn. Read .cursor/audit.log and fix the reported issues before declaring the task complete.\n\n$SUMMARY"
  printf '{"followup_message":%s}\n' "$(printf '%s' "$MSG" | json_escape)"
else
  echo '{}'
fi

rm -f "$TMP"
exit 0
