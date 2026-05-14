# SQLite 3 Skill (Python `sqlite3`)
# Context-Aware Message Sending Bot

## Purpose

This skill is read by the **Developer Agent** when adding or changing SQLite-backed
persistence (schema, migrations, repository-style modules, or tools that execute SQL).

The **Security Analyst** should read it when auditing SQL injection risk, locking, or
data-at-rest exposure in persistence code.

It complements the project **Python skill** (`python-guide/SKILL.md`) — that file
contains minimal SQLite snippets for everyday use; this document is the full contract for
database work.

**Source of truth:** Python **3.12** standard library `sqlite3` only for this project.
Install **no** extra PyPI SQLite driver unless the Solution Architect explicitly changes
the stack; see `backend/requirements.txt`.

**Official docs:** https://docs.python.org/3/library/sqlite3.html

Do not invent SQLite behavior. If a scenario is not listed here, look it up in the
stdlib docs — do not assume.

---

## Architecture boundary

- **Agents do not open database connections.** Keep persistence inside tools or small
  data-layer helpers that the graph/API calls — matching project rules (DB behind tools).
- Return **`ToolResultEnvelope`** or Pydantic models at HTTP and tool boundaries; do not
  pass live `Connection` objects outside the persistence layer.

---

## Connections

```python
import sqlite3
from pathlib import Path

def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
```

- Use **`pathlib.Path`** for locations; pass `str(path)` or use paths accepted by
  `sqlite3.connect` per docs.
- Set **`timeout=`** (seconds) so writers wait under brief contention instead of failing.
- **`PRAGMA foreign_keys = ON`** must run on **each** new connection (SQLite defaults to
  OFF for historical compatibility).
- The **`with sqlite3.connect(...) as conn:`** context manager closes the connection when
  the block ends.

---

## Parameterized queries (mandatory)

Use `?` placeholders and bound parameters only — never build SQL with f-strings or `%`
formatting from caller-controlled strings.

```python
conn.execute(
    "INSERT INTO runs (session_id, payload) VALUES (?, ?)",
    (session_id, payload_json),
)
```

- **`executemany`** for batch inserts.
- **Identifiers** (dynamic table/column names) cannot be bound — validate against a fixed
  allow-list or enum in Python before interpolating; reject anything else.

---

## Transactions

- Statements that modify data run inside a transaction; **`commit()`** persists,
  **`rollback()`** discards.
- For multi-step atomicity, wrap in explicit `BEGIN` / `COMMIT`, or use
  **`BEGIN IMMEDIATE`** when you need to acquire a write lock up front and reduce
  **`database is locked`** errors on write-heavy workloads.

---

## Row access

```python
conn.row_factory = sqlite3.Row
row = conn.execute("SELECT id, status FROM runs WHERE id = ?", (run_id,)).fetchone()
if row is None:
    ...
status = row["status"]
```

Map to **`dict(row)`** or Pydantic models before returning across module boundaries.

---

## Schema and migrations

- Ship idempotent DDL with **`CREATE TABLE IF NOT EXISTS`** and additive `ALTER` steps.
- Track a **schema version** integer in a small metadata table and migrate in order.

```sql
CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL);
```

Do **not** drop or rewrite production tables from app code without a deliberate migration
plan.

---

## Pragmas worth knowing

| Pragma | Why |
|--------|-----|
| `foreign_keys = ON` | Referential integrity |
| `journal_mode = WAL` | Better reader/writer concurrency for on-disk databases |

Check WAL availability in tests some platforms restrict it — handle failure gracefully in CI.

---

## Concurrency and FastAPI / uvicorn

- SQLite allows **one writer** at a time (many readers with WAL).
- Prefer **short-lived connections**: open, execute, commit, close per operation or
  request when practical.
- **`check_same_thread`** defaults to `True`. Only set `False` with shared connections if
  you add explicit synchronization — not typical for per-request opens.

---

## Testing

- **`sqlite3.connect(":memory:")`** for fast unit tests, or a temp file under
  **`tempfile.TemporaryDirectory`** for file-backed behavior.
- Reuse the same **`init_schema(conn)`** function production uses so tests mirror real DDL.

---

## Exceptions to catch at tool boundaries

| Type | Typical cause |
|------|----------------|
| `sqlite3.IntegrityError` | UNIQUE / FK / CHECK violation |
| `sqlite3.OperationalError` | Locked DB, bad SQL, missing table |
| `sqlite3.DatabaseError` | General database error |

Log with **`exc_info=True`** in tools; return **`ToolResultEnvelope(error=str(exc), result=None)`**
per project standards.

---

## Anti-patterns

- Interpolating user or external input into SQL strings.
- Global long-lived connections without a story for multi-process deployment.
- Trusting request JSON to pick table names, columns, or pragma values.
- Committing secrets or sensitive PII without alignment with Security Analyst guidance.

---

## Repo conventions

- Local DB files often use **`.sqlite3`** suffix; **`*.sqlite3`** is gitignored — do not
  commit developer databases.
- Read database paths from **settings / environment**, not scattered string literals.

**Version note:** Written for CPython `sqlite3` as shipped with Python 3.12 (SQLite
version bundled with Python; check `sqlite3.sqlite_version` at runtime if needed).
