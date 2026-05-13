# Recall — Write a Checkpoint

Write a checkpoint to `logs/` summarising what was just completed.
Invoked by any agent at the end of a phase or significant task, or before handing off.

Read `.cursor/skills/recall/SKILL.md` for the full protocol including how to read
existing checkpoints at the start of a task.

## Steps

### 1. Generate the filename

Run:
```bash
date '+%Y%m%d_%H%M'
```

Construct the filename as:
```
logs/<timestamp>_<agent>_<descriptor>.md
```

Where `<agent>` is one of: `developer`, `architect`, `audit`, `user`.
Where `<descriptor>` is a short kebab-case label: `phase1`, `phase3-tools`, `domain-expansion`, etc.

Example: `logs/20260513_1430_developer_phase1.md`

### 2. Collect the checkpoint content

Answer each field honestly. Do not skip fields. Do not write vague summaries.

**Agent** — which agent are you?

**Task** — in 1–2 sentences, what was this phase or task trying to accomplish?

**Completed** — list every file created or meaningfully modified, with one sentence
per file explaining what it does. Be exact about file paths.

**Verified** — list every verification command you ran and its actual output.
If you skipped verification, write `(not verified)` — do not fabricate results.

**Open Questions** — list anything unresolved. If nothing, write `(none)`.

**Next** — what happens next? Name the phase, the file, and the responsible agent.
Be specific enough that the next agent can start without asking.

**Status** — `COMPLETE`, `PARTIAL`, or `BLOCKED`.
- `COMPLETE`: all deliverables built and verified
- `PARTIAL`: deliverables built but not fully verified, or some items missing
- `BLOCKED`: cannot proceed — explain exactly what is blocking

### 3. Write the file

Use the Write tool to create `logs/<filename>.md` with the checkpoint content.
Follow the exact format defined in `.cursor/skills/recall/SKILL.md`.

### 4. Confirm

State the full path of the file written and its status line.
Example: `logs/20260513_1430_developer_phase1.md — COMPLETE`

## If blocked

- If `logs/` does not exist, create it first: `mkdir -p logs`
- If you are unsure what the descriptor should be, use the phase number: `phase1`, `phase2`, etc.
- If you are mid-phase and handing off due to a blocker, set status to `BLOCKED`
  and fill the "Next" field with exactly what would unblock the work
