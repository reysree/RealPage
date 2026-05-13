# Recall Skill
# RealPage Lumina — AI Property Management Platform

## Purpose

This skill defines the checkpoint protocol for all agents.

Every time an agent completes a phase or a significant task, it writes a checkpoint
to `logs/`. Every time an agent starts work, it reads the latest checkpoint(s) to
reconstruct context — instead of needing the full conversation history.

If you are starting work: read "Reading Checkpoints" first.
If you are finishing work: read "Writing a Checkpoint" first.

---

## Reading Checkpoints (start of any task)

Before writing a single line of code or making any decision, run:

```bash
ls logs/ | sort | tail -5
```

Read the most recent checkpoint file. If multiple agents were active, read the
latest file for each relevant agent.

Extract and hold in mind:
1. **Phase status** — what is COMPLETE, what is PARTIAL, what is BLOCKED
2. **Files produced** — what already exists (do not recreate)
3. **Verified state** — what has already been confirmed working
4. **Open questions** — unresolved decisions that may affect your work
5. **Next actions** — what the previous agent said should happen next

If no `logs/` directory or no checkpoint files exist, you are the first agent.
Read `CLAUDE.md` and the architect's recall file in `recall/` (if any) instead.

---

## Writing a Checkpoint (end of any phase or task)

Invoke `/recall` when:
- A phase is complete (Phases 1–6 per CLAUDE.md)
- A significant sub-task is done within a phase
- You are handing off to another agent
- You are blocked and stopping work

The `/recall` command will prompt you through the checkpoint fields.
The file is written to `logs/YYYYMMDD_HHMM_<agent>_<descriptor>.md`.

---

## Checkpoint File Format

```markdown
# Checkpoint — <descriptor> | YYYY-MM-DD HH:MM

## Agent
<Developer | Architect | Audit | user>

## Task
<1–2 sentences: what this phase/task was trying to accomplish>

## Completed
- `path/to/file.py` — what it does and why it was created/changed
- `path/to/file2.py` — ...
(List every file created or meaningfully modified. Be specific.)

## Verified
- Command: `<exact command run>`
  Result: `<exact output or "exit 0">`
- Command: `...`
  Result: `...`
(Omit if nothing was verified — but note that as a gap.)

## Open Questions
- <anything unresolved that the next agent must decide or check>
- (none) if everything is resolved

## Next
<What needs to happen next. Be specific: which phase, which files, which agent.>

## Status
COMPLETE | PARTIAL | BLOCKED

### If PARTIAL or BLOCKED
<Exact reason. What is missing. What would unblock it.>
```

---

## Naming Convention

```
logs/YYYYMMDD_HHMM_<agent>_<descriptor>.md
```

Examples:
```
logs/20260513_1430_developer_phase1.md
logs/20260513_1615_audit_phase2.md
logs/20260513_1800_developer_phase3-tools.md
logs/20260513_2100_architect_domain-expansion.md
```

Use `date '+%Y%m%d_%H%M'` to generate the timestamp prefix.

---

## Rules

- **One checkpoint per agent per phase.** If you need to update a checkpoint within
  the same phase (e.g. after fixing an audit flag), write a new file — do not edit the old one.
- **Never truncate the Completed or Verified sections.** The next agent depends on
  precision. "Updated schemas.py" is useless. "Added `LeaseRecord` model with fields
  `unit_id`, `tenant_id`, `start_date`, `monthly_rent` to `backend/schemas.py`" is useful.
- **Status = COMPLETE only if verification passed.** If you did not run the verification
  commands, status is PARTIAL.
- **Next must name the next action concretely.** "Continue Phase 3" is not enough.
  "Implement `calculate` tool in `backend/tools/calculate.py` with prorate operation" is.
