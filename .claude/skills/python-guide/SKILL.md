# Python Skill
# RealPage Lumina — AI Property Management Platform

## Purpose

This skill is read by the Developer Agent before writing any Python code.
It defines every Python pattern, standard, and anti-pattern for this project.

Do not invent syntax. Do not use patterns not shown here.
If a situation is not covered, ask before proceeding.

---

## Environment

```
Python: 3.12
Package manager: pip
Virtual environment: venv (backend/venv/)
Linter: ruff (run before every commit)
```

---

## Type Hints — Always

Every parameter and return value is annotated. No exceptions.

```python
# Good
def get_history(session_id: str, limit: int = 20) -> list[dict]:
    ...

# Bad
def get_history(session_id, limit=20):
    ...
```

Use built-in generics (Python 3.9+):
```python
# Good
list[str]
dict[str, int]
tuple[str, int]
list[dict[str, str]]

# Bad (do not import from typing unless needed)
List[str]
Dict[str, int]
```

Use `Optional` only when None is a valid value:
```python
from typing import Optional

def find_session(session_id: str) -> Optional[dict]:
    ...

# Equivalent — prefer this in Python 3.10+
def find_session(session_id: str) -> dict | None:
    ...
```

---

## Pydantic v2 — Every API Boundary

Every input and output that crosses a module boundary uses a Pydantic BaseModel.
No raw dicts. No untyped returns from FastAPI routes.

### Defining Models

```python
from pydantic import BaseModel, Field
from typing import Optional

class ChatRequest(BaseModel):
    """
    Inbound chat message from the frontend.
    Validated by Pydantic before the agent sees it.
    """
    message: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="The user's message text"
    )
    session_id: str = Field(
        ...,
        min_length=1,
        description="Unique conversation session ID"
    )
```

### Do Not Use v1 Syntax

```python
# Bad — Pydantic v1 validator (not compatible with v2)
@validator("message")
def validate_message(cls, v):
    ...

# Good — Pydantic v2 field_validator
from pydantic import field_validator

@field_validator("message")
@classmethod
def validate_message(cls, v: str) -> str:
    if not v.strip():
        raise ValueError("Message cannot be empty")
    return v.strip()
```

### Model Config (v2)

```python
from pydantic import BaseModel, ConfigDict

class MyModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str
```

### Instantiating from a dict

```python
# Good — explicit unpacking
record = MessageRecord(**raw_dict)

# Also good — model_validate
record = MessageRecord.model_validate(raw_dict)

# Bad — don't pass a dict as-is
route_handler(raw_dict)
```

---

## Async Patterns

FastAPI route handlers are always async. Any function that calls an async function must be async.

```python
# Good
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    history = get_history(request.session_id)   # sync — ok
    result = await run_agent(request.message, history)  # async — must await
    return ChatResponse(...)

# Bad — sync handler calling async function
@app.post("/chat")
def chat(request: ChatRequest):
    result = run_agent(...)   # TypeError — can't call coroutine without await
```

SQLite operations are synchronous. Do not wrap them in asyncio unnecessarily.
Run them directly — FastAPI handles thread pool offloading for sync operations.

```python
# Good — sync SQLite call inside async route
async def chat(request: ChatRequest):
    history = get_history(request.session_id)  # sync — FastAPI handles this
    result = await run_agent(request.message, history)
```

---

## Error Handling

### In Tools — Always Return, Never Raise

Tools return structured JSON regardless of success or failure.
The agent receives the error JSON and responds accordingly.
Never let an unhandled exception propagate out of a tool.

```python
@function_tool
def search_knowledge_base(query: str) -> str:
    try:
        results = _collection.query(query_texts=[query], n_results=3)
        return json.dumps({"results": results})
    except Exception as e:
        logger.error(f"[search_knowledge_base] error={e}", exc_info=True)
        return json.dumps({"error": str(e), "results": []})
```

### In FastAPI Routes — Raise HTTPException

Route handlers raise HTTPException for errors. Do not return error dicts from routes.

```python
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        result = await run_agent(request.message, history)
    except Exception as e:
        logger.error(f"Agent error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    return ChatResponse(...)
```

---

## Logging

Use Python's stdlib `logging` — not print().

```python
import logging

logger = logging.getLogger(__name__)

# Setup in main.py only — not in every file
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
```

Log levels:
- `logger.debug()` — high-frequency events (every message received)
- `logger.info()` — state changes (tool called, session created, startup complete)
- `logger.warning()` — unexpected but recoverable (seed data missing, no results)
- `logger.error()` — exceptions (always with `exc_info=True`)

What to log in tools:
```python
logger.info(f"[{tool_name}] query={query!r}")          # on entry
logger.info(f"[{tool_name}] returned {n} results")     # on success
logger.error(f"[{tool_name}] error={e}", exc_info=True) # on failure
```

What NOT to log:
- Raw user messages (PII risk)
- API keys or tokens
- Full response bodies in production

---

## SQLite Patterns

Use `sqlite3.connect()` as a context manager. Always use parameterized queries.

```python
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "sessions.db"

def save_message(session_id: str, role: str, content: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, role, content, datetime.utcnow().isoformat())
        )
        conn.commit()
```

Use `sqlite3.Row` for readable results:
```python
def get_history(session_id: str, limit: int = 20) -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit)
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
```

Never use string interpolation in SQL:
```python
# Bad — SQL injection risk
conn.execute(f"SELECT * FROM messages WHERE session_id = '{session_id}'")

# Good — parameterized
conn.execute("SELECT * FROM messages WHERE session_id = ?", (session_id,))
```

---

## json Module

Every tool returns a JSON string. Use `json.dumps()` — never return raw objects.

```python
import json

# Good
return json.dumps({"results": formatted, "count": len(formatted)})

# Bad — returns a Python dict, not a string
return {"results": formatted}
```

Parse incoming JSON strings with try/except:
```python
try:
    data = json.loads(values)
except json.JSONDecodeError as e:
    return json.dumps({"error": f"Invalid JSON: {e}"})
```

---

## Abstract Base Classes — Interface Contracts

Use ABCs to define interfaces for swappable components.
This is the scale upgrade path made explicit in code.

```python
from abc import ABC, abstractmethod

class VectorRetriever(ABC):
    """
    Interface contract for vector retrieval backends.
    ChromaDB implements this locally.
    Pinecone or pgvector implement this in production.
    The agent layer never knows which backend is running.
    """

    @abstractmethod
    def search(self, query: str, n_results: int = 3) -> list[dict]:
        """
        Search the vector store for documents relevant to query.

        Args:
            query: natural language search string
            n_results: number of results to return

        Returns:
            list of dicts with 'content', 'metadata', 'score' keys
        """
        ...
```

---

## Imports — Ordered and Explicit

Import order (enforced by ruff):
1. Standard library
2. Third-party packages
3. Local modules

```python
# Standard library
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

# Third-party
import chromadb
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# Local
from schemas import ChatRequest, ChatResponse
from db import init_db, save_message, get_history
```

Never use wildcard imports:
```python
# Bad
from schemas import *

# Good
from schemas import ChatRequest, ChatResponse, MessageRecord
```

---

## Anti-Patterns — Never Do These

```python
# 1. Raw dict at a module boundary
return {"response": text}  # Bad — return ChatResponse(response=text) instead

# 2. Hardcoded strings
collection_name = "knowledge_base"  # Bad — put in settings or constant at module level

# 3. Catching bare Exception without logging
try:
    ...
except Exception:
    pass  # Bad — always log, always return structured error

# 4. Nested async calls without await
result = run_agent(message, history)  # Bad — missing await, returns coroutine

# 5. Mutating function defaults
def get_history(session_id: str, messages: list = []) -> list:  # Bad — mutable default
    ...

# 6. Type: ignore without explanation
x: str = some_func()  # type: ignore  # Bad — explain why if truly needed

# 7. f-string in SQL
conn.execute(f"SELECT * FROM messages WHERE id = {id}")  # Bad — SQL injection

# 8. Pydantic v1 validator in v2 project
@validator("field")  # Bad — use @field_validator
```