#!/usr/bin/env bash
# Cursor preToolUse hook - blocks accidental duplicate file creation.
# Reads Cursor hook JSON from stdin, extracts the target write path, and asks the
# agent to edit the existing file when another source file has the same basename.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INPUT="$(cat)"

PYTHON="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)"
if [ -z "$PYTHON" ]; then
  echo '{"permission":"allow"}'
  exit 0
fi

FILE_PATH="$(printf '%s' "$INPUT" | "$PYTHON" -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    print("")
    raise SystemExit

keys = ("file_path", "filePath", "path", "target_file", "targetFile")
containers = [data, data.get("input", {}), data.get("tool_input", {}), data.get("toolInput", {}), data.get("arguments", {})]
for container in containers:
    if isinstance(container, dict):
        for key in keys:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                print(value)
                raise SystemExit
print("")
' 2>/dev/null)"

if [ -z "$FILE_PATH" ]; then
  echo '{"permission":"allow"}'
  exit 0
fi

BASENAME="$(basename "$FILE_PATH")"
case "$BASENAME" in
  __init__.py|__main__.py|index.js|index.jsx|index.ts|index.tsx)
    echo '{"permission":"allow"}'
    exit 0 ;;
esac

MATCHES="$(find "$ROOT/backend" "$ROOT/frontend/src" \
  \( -path "*/.venv" -o -path "*/.venv/*" -o -path "*/.venv-*" -o -path "*/.venv-*/*" -o -path "*/node_modules" -o -path "*/node_modules/*" \) -prune -o \
  -name "$BASENAME" -print \
  2>/dev/null || true)"

if [ -z "$MATCHES" ]; then
  echo '{"permission":"allow"}'
  exit 0
fi

normalise() {
  "$PYTHON" -c "import os,sys; print(os.path.normcase(os.path.abspath(os.path.normpath(sys.argv[1]))))" "$1" 2>/dev/null
}

NORM_TARGET="$(normalise "$FILE_PATH")"
DUPLICATE=""
while IFS= read -r match; do
  [ -z "$match" ] && continue
  NORM_MATCH="$(normalise "$match")"
  if [ "$NORM_MATCH" != "$NORM_TARGET" ]; then
    DUPLICATE="$match"
    break
  fi
done <<< "$MATCHES"

if [ -z "$DUPLICATE" ]; then
  echo '{"permission":"allow"}'
  exit 0
fi

"$PYTHON" -c '
import json, sys
basename, duplicate = sys.argv[1], sys.argv[2]
print(json.dumps({
    "permission": "deny",
    "user_message": f"A file named {basename} already exists at {duplicate}. Edit the existing file unless this is intentionally distinct.",
    "agent_message": f"Do not create a duplicate {basename} file. Use an edit on {duplicate} or ask the user to confirm the distinction.",
}))
' "$BASENAME" "$DUPLICATE"
exit 0
