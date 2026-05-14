# Context-Aware Message Sending Bot — Agent Instructions

This project uses Cursor-native harness files. Start with these:

1. Read `.cursor/rules/*.mdc` for project rules, coding standards, and workflow constraints.
2. Use `.cursor/hooks.json` for project hook behavior. Hook scripts live in `.cursor/hooks/`.
3. Use `.cursor/agents/`, `.cursor/skills/`, and `.cursor/commands/` as mirrored project guidance from the original Claude harness.
4. Before phase work, read the latest checkpoint in `logs/`. If none exists, read the latest architecture decision in `recall/`.
5. After significant work, write a checkpoint to `logs/YYYYMMDD_HHMM_<agent>_<descriptor>.md`.

Keep changes surgical, preserve user edits, and do not bypass the phase gate:
developer `COMPLETE`, security `PASS`, and audit `PASS` before the next phase opens.
