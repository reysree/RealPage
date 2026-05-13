# Cursor Harness Migration

This directory mirrors the project harness from `.claude/` into Cursor-native locations.

## Native Cursor Surfaces

- `rules/*.mdc` - persistent Cursor rules, split into core, backend, frontend, harness, and TDD guidance.
- `hooks.json` - project hook configuration using Cursor hook event names.
- `hooks/pre-write-check.sh` - pre-tool hook that blocks accidental duplicate source files.
- `hooks/audit.sh` - stop hook that audits changed Python and frontend files and logs to `.cursor/audit.log`.

## Mirrored Reference Assets

- `agents/` - migrated project agent prompts with `.cursor` paths.
- `skills/` - migrated project skills with `.cursor` paths.
- `commands/` - migrated command playbooks. Cursor does not treat these exactly like Claude slash commands; use them as project workflows.

## Notes

`.claude/settings.local.json` contains Claude-specific local permissions and was not converted into Cursor hook config. Keep machine-local allowlists out of the shared project harness unless there is a Cursor-native setting that needs them.
