# Claude Harness Best Practices Guide

You are an expert in configuring and authoring the Claude Code custom harness. When invoked, review the requested area (or all areas if unspecified) and produce concrete, actionable guidance or perform the refactor directly.

## Scope

The user may ask about one or more of these areas:
- `claude.md` — project context file
- `skills` / `commands` — custom slash commands
- `agents` — sub-agent definitions
- `memory` — persistent memory files
- `hooks` — automated shell triggers
- `mcp` — Model Context Protocol server configs

If the user passes an argument (e.g. `/harness-guide memory`), focus on that area. Otherwise cover all.

---

## CLAUDE.md Best Practices

**Purpose:** Give Claude durable project context that survives conversation resets.

### What to include
- Project purpose in 1-3 sentences
- Tech stack and key dependencies (versions if non-obvious)
- Repo layout — only non-obvious directories
- Build, test, and lint commands
- Environment variable requirements (names only, never values)
- Coding conventions that deviate from defaults (e.g. tabs not spaces, no semicolons)
- Domain-specific terminology or abbreviations
- Constraints — things Claude must never do (e.g. never drop tables, never commit to main)

### What to exclude
- Information derivable by reading code (function signatures, schema)
- Git history or recent changes (`git log` is authoritative)
- Debugging notes or fix recipes (belong in commit messages)
- Ephemeral task state (belongs in TodoWrite / conversation)
- Secrets or credential values

### Format rules
- Use H2 (`##`) sections, keep headings scannable
- Bullet points over prose
- Keep the whole file under ~300 lines; Claude loads it every turn
- Prefer absolute truths over relative ones ("use Node 20" not "use the latest LTS")
- Place project-level `CLAUDE.md` at repo root; place folder-level ones in subdirs for monorepos

### Anti-patterns to fix
- Wall-of-text paragraphs → convert to bullets
- Duplicate info already in README → link to README section instead
- Vague instructions ("write good code") → remove or make specific
- Stale commands that no longer work → verify and update or delete

---

## Skills / Commands Best Practices

**Location:** `.cursor/commands/<name>.md` → invoked as `/<name>`

### Structure of a well-formed command file
```
# Command Title

<one-paragraph description of what this command does and when to use it>

## Trigger conditions
<when Claude should invoke this automatically if applicable>

## Steps
<numbered or bulleted procedure Claude should follow>

## Output format
<what the response should look like>

## Examples
<concrete before/after or input/output examples>
```

### Rules
- Name the file with kebab-case matching the slash command (`code-review.md` → `/code-review`)
- Lead with the user intent, not implementation steps
- Include guard clauses: what Claude should do if preconditions aren't met
- For skills that write files, specify exactly which files and where
- For skills that call tools, list the tools in order so the reader can predict behavior
- Keep each skill single-purpose; compose via multiple `/command` calls rather than one mega-skill
- Version-stamp if the skill depends on a tool or API that changes frequently

### Anti-patterns
- Vague outcome ("help with the code") → specify exactly what artifact is produced
- Missing failure modes → add a "## If blocked" section
- Skills that duplicate built-in Claude Code behavior → delete and use the built-in
- Skills longer than ~150 lines → split into focused sub-skills

---

## Agents Best Practices

**Purpose:** Sub-agents handle isolated, parallelisable, or context-heavy subtasks without polluting the main conversation.

### When to spawn an agent
- Open-ended codebase exploration that may take 3+ tool calls
- Independent parallel workstreams (e.g. run tests while fixing lint)
- Tasks that would flood the main context (large file reads, exhaustive grep)
- Specialised domains with their own tool sets (Explore, Plan, claude-code-guide)

### When NOT to spawn an agent
- The target file/symbol is already known → use Read/Grep directly
- The task is a single tool call
- You need the result immediately and there's no parallel work to do

### Agent prompt best practices
- Brief the agent like a smart colleague who just joined: include goal, what's already ruled out, relevant file paths
- State explicitly whether the agent should read-only or also write/edit
- Specify the output format and length cap ("report in under 200 words")
- Never write "based on your findings, fix X" — synthesise findings yourself and give the agent the specific change
- Pass absolute paths, not relative ones
- Set `isolation: "worktree"` for agents that will write code, so changes are sandboxed

### Sub-agent type selection
| Task | Use |
|------|-----|
| Codebase exploration | `Explore` |
| Implementation planning | `Plan` |
| Claude Code / API / SDK questions | `claude-code-guide` |
| Everything else | `general-purpose` (default) |

---

## Memory Best Practices

**Location:** `.claude/memory/` (or `~/.claude/projects/<project>/memory/`)

### Memory types and triggers
| Type | Save when | Example |
|------|-----------|---------|
| `user` | Learn user's role, expertise, preferences | "I'm new to React but senior in Go" |
| `feedback` | User corrects or confirms a non-obvious approach | "don't mock the DB in tests" |
| `project` | Goals, deadlines, architectural decisions not in code | "auth rewrite is compliance-driven" |
| `reference` | Pointers to external systems | "bugs tracked in Linear INGEST project" |

### File format
```markdown
---
name: <short title>
description: <one line — used to decide relevance in future sessions>
type: user | feedback | project | reference
---

<content>

**Why:** <the reason this matters>
**How to apply:** <when/where this kicks in>
```

### MEMORY.md index rules
- One line per entry, under 150 chars: `- [Title](file.md) — one-line hook`
- No frontmatter in MEMORY.md itself
- Lines beyond 200 are truncated by the runtime — keep it lean
- Group by topic (user, feedback, project) not chronologically

### What NOT to save
- Code patterns derivable from reading the repo
- Git history (use `git log`)
- In-progress task state (use TodoWrite)
- Anything already in CLAUDE.md
- Secrets

### Staleness rule
Before acting on a memory that names a file, function, or flag — verify it still exists. If it conflicts with current code, trust the code and update or delete the memory.

---

## Hooks Best Practices

**Location:** `.cursor/hooks.json` → `hooks` key (or `settings.local.json` for personal-only hooks)

### Hook anatomy
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "echo 'About to run bash' && validate-command.sh"
          }
        ]
      }
    ],
    "PostToolUse": [...],
    "Stop": [...],
    "Notification": [...]
  }
}
```

### Available hook events
| Event | Fires |
|-------|-------|
| `PreToolUse` | Before any tool call — can block execution |
| `PostToolUse` | After any tool call — for logging/side effects |
| `Stop` | When Claude finishes a turn |
| `Notification` | When Claude emits a user-facing notification |

### Matcher patterns
- `"Bash"` — matches the Bash tool exactly
- `"mcp__*"` — wildcard for all MCP tools
- `""` (empty string) — matches every tool

### Rules
- Keep hook scripts fast (< 1s) — they block the tool call
- Exit non-zero to block a tool and surface an error message to Claude
- Use `settings.local.json` for hooks that contain personal paths or secrets
- Idempotent hooks only — hooks may fire multiple times
- Log to a file, not stdout, to avoid polluting Claude's context
- Test hooks manually (`bash -c "<command>"`) before wiring them in
- Automated behaviors ("always do X before Y") require hooks — memory/preferences alone cannot enforce them

### Anti-patterns
- Long-running hooks (network calls, heavy builds) → run async or move to PostToolUse
- Hooks that modify files Claude is about to read → race condition
- Secrets hardcoded in `settings.json` (committed to git) → use `settings.local.json` or env vars

---

## MCP Files Best Practices

**Location:** `.claude/mcp.json` (project) or `~/.claude/mcp.json` (global)

### Config structure
```json
{
  "mcpServers": {
    "<server-name>": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/allowed/path"],
      "env": {
        "API_KEY": "${MY_API_KEY}"
      }
    }
  }
}
```

### Transport types
| Type | Use case |
|------|----------|
| `stdio` | Local processes (most common) |
| `sse` | Remote HTTP servers |
| `http` | Stateless remote servers |

### Rules
- Use `${ENV_VAR}` interpolation for secrets — never hardcode credentials
- Scope servers narrowly: filesystem servers should only expose needed paths
- Name servers descriptively (`github`, `postgres-prod`) not generically (`server1`)
- Place project-specific MCP in `.claude/mcp.json`; personal/global tools in `~/.claude/mcp.json`
- Pin versions in `args` for reproducibility (`@scope/pkg@1.2.3` not `@scope/pkg`)
- Prefer official Anthropic or well-maintained community servers over ad-hoc scripts
- Test new MCP servers in isolation before adding to shared project config
- Document each server's purpose in a comment block in CLAUDE.md (MCP config is JSON, no comments allowed inline)

### Anti-patterns
- Exposing entire filesystem (`/`) to a filesystem server → scope to project root
- Putting personal API keys in `.claude/mcp.json` (committed) → use `settings.local.json` or `~/.claude/mcp.json`
- Duplicate servers with overlapping capabilities → consolidate
- MCP servers that start heavy background processes on every Claude session → add a health-check wrapper

---

## Quick Reference Checklist

When reviewing or creating any harness artifact, verify:

**CLAUDE.md**
- [ ] Under 300 lines
- [ ] Build/test/lint commands present and working
- [ ] No secrets or values, only names
- [ ] Stale content removed

**Commands**
- [ ] Filename matches intended slash command
- [ ] Single clear purpose
- [ ] Failure/guard cases documented

**Agents**
- [ ] Only spawned for open-ended or parallel work
- [ ] Prompt is self-contained with file paths and goals
- [ ] `isolation: "worktree"` set for write operations

**Memory**
- [ ] MEMORY.md index is current and under 200 lines
- [ ] Each file has correct frontmatter type
- [ ] No code patterns or ephemeral state saved

**Hooks**
- [ ] All hooks are fast and idempotent
- [ ] Secrets in `settings.local.json`, not `settings.json`
- [ ] Tested manually before committing

**MCP**
- [ ] No hardcoded credentials
- [ ] Versions pinned
- [ ] Scope limited to needed paths/resources
