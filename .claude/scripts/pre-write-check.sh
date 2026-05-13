#!/usr/bin/env bash
# PreToolUse hook — fires before every Write tool call.
# Reads the tool input JSON from stdin, extracts the target file_path,
# then searches the project for any existing file with the same name at a
# different path. If a duplicate is found, exits 1 to block the write and
# tells Claude to use Edit on the existing file instead.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Read the full tool input JSON from stdin.
INPUT=$(cat)

# Extract file_path via Python (handles any quoting/escaping in the JSON).
FILE_PATH=$(printf '%s' "$INPUT" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(d.get('file_path',''))" \
  2>/dev/null)

# Nothing to check if we couldn't parse a path.
[ -z "$FILE_PATH" ] && exit 0

BASENAME=$(basename "$FILE_PATH")

# These names are legitimately expected in multiple directories — skip them.
case "$BASENAME" in
  __init__.py|__main__.py|index.js|index.jsx|index.ts|index.tsx)
    exit 0 ;;
esac

# Search only within project source directories (not venv, node_modules, .claude).
MATCHES=$(find "$ROOT/backend" "$ROOT/frontend/src" \
  -name "$BASENAME" \
  ! -path "*/.venv/*" \
  ! -path "*/node_modules/*" \
  2>/dev/null || true)

[ -z "$MATCHES" ] && exit 0

# Normalise both paths with Python so Windows case and slash differences
# don't produce false positives.
normalise() {
  python3 -c "import os,sys; print(os.path.normcase(os.path.normpath(sys.argv[1])))" "$1" 2>/dev/null
}

NORM_TARGET=$(normalise "$FILE_PATH")
DUPLICATE=""

while IFS= read -r match; do
  [ -z "$match" ] && continue
  NORM_MATCH=$(normalise "$match")
  if [ "$NORM_MATCH" != "$NORM_TARGET" ]; then
    DUPLICATE="$match"
    break
  fi
done <<< "$MATCHES"

# No collision — same file or no match.
[ -z "$DUPLICATE" ] && exit 0

# Block the write and explain why.
echo ""
echo "[BLOCKED] Cannot create '$BASENAME' — a file with this name already exists at:"
echo "  $DUPLICATE"
echo ""
echo "Do NOT create a duplicate. Use the Edit tool on the existing file instead."
echo "If this is intentionally a different file, confirm the distinction explicitly"
echo "before proceeding."
echo ""
exit 1
