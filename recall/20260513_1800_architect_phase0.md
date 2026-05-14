# Architecture Decision — Phase 0 (PoC)
Date: 2026-05-13
Domain: Context-Aware Message-Sending Bot (RealPage Lumina Outreach)
Pattern chosen: E — LangGraph Pipeline (Primary Orchestrator)
Status: AWAITING HUMAN APPROVAL

---

## Scope

This is a PoC. The system reads JSONL records and, for each record, runs a LangGraph
pipeline that decides: which channel to use, what message to send, and why.

Output per record: `{ channel, message, why }`.

Everything else (eval harness, ChromaDB, SQLite, frontend) is deferred.

---

## 1. Domain Analysis

**Input:** A JSONL file where each line is one outreach record. Each record contains:
- `consent` — which channels the recipient has opted into (email_opt_in, sms_opt_in, voice_opt_in)
- `channel_preferences` — ordered list of preferred channels
- `persona`, `lifecycle_stage` — who this person is and where they are in the journey
- `input` — profile facts (name, move date, interests), property name, timezone, last_interaction

**Output per record:**
```json
{
  "task_id": "prospect_welcome_day0",
  "send": true,
  "channel": "sms",
  "message": "Hi Taylor—welcome to Oak Ridge! ...",
  "why": {
    "channel_reason": "SMS selected: opted in and is top preference.",
    "message_reason": "Day-0 welcome for a short-horizon prospect. Tour CTA chosen to convert intent."
  }
}
```

If no channel is eligible:
```json
{
  "task_id": "...",
  "send": false,
  "channel": null,
  "message": null,
  "why": { "channel_reason": "No eligible channel: all preferred channels have opt-in revoked." }
}
```

**Core constraint:** The pipeline order is fixed and non-negotiable. You cannot pick a channel
without knowing consent. You cannot write a message without knowing the channel.

---

## 2. Pattern Decision

**Chosen: Pattern E — LangGraph Pipeline (Primary Orchestrator)**

The workflow is a strict, ordered pipeline. LangGraph's StateGraph enforces node execution
order deterministically. Every run produces a traceable audit entry per node.

**Why not OpenAI Agents SDK:** The SDK lets the LLM decide which tools to call and in what
order. If two residents receive different outputs, we cannot explain why — there is no
guaranteed node sequence and no typed state between steps. LangGraph fixes this: same input
always traverses the same graph; every decision is recorded in typed state; differential
outputs are explainable node by node.

---

## 3. LangGraph Nodes

Four nodes. Each is a pure Python function: `def node_name(state: GraphState) -> GraphState`.

### Node 1 — `consent_node`
**What it does:** Reads the consent flags from state and produces the list of channels the
recipient is actually opted into.

**Reads:** `state["consent"]` — `{email_opt_in, sms_opt_in, voice_opt_in}`

**Writes:** `state["eligible_channels"]` — e.g. `["sms", "email"]`

**Logic:** Deterministic. No LLM. Map opt-in flags to channel names; include only those
where the flag is `true`.

**Edge:** If `eligible_channels` is empty → skip to `output_node` with `send=False`.

---

### Node 2 — `channel_node`
**What it does:** Selects the best channel by intersecting the recipient's preference order
with the eligible channels.

**Reads:** `state["eligible_channels"]`, `state["channel_preferences"]`

**Writes:** `state["selected_channel"]` (str or None), `state["send"]` (bool),
`state["channel_reason"]` (str — human-readable explanation for "why this channel")

**Logic:** Deterministic. Walk `channel_preferences` in order; return the first one that
appears in `eligible_channels`. If none found: `selected_channel=None`, `send=False`.

**Example channel_reason:** `"SMS selected: opted in and ranked #1 in preferences."`
**Example channel_reason (fallback):** `"Email selected: SMS opted out; email is next preference and opted in."`

**Edge:** If `send=False` → skip to `output_node`.

---

### Node 3 — `composer_node`
**What it does:** Calls an LLM (OpenAI (e.g. gpt-4o)) to generate a personalized
message and explain why this message fits this person.

**Reads:** `state["selected_channel"]`, `state["persona"]`, `state["lifecycle_stage"]`,
`state["input"]` (profile, property_name, move_date_target, amenity_interest, etc.)

**Writes:** `state["message"]` (str — the actual message body),
`state["message_reason"]` (str — the "why" for the message content)

**LLM prompt contract:**
The system prompt instructs the model to:
1. Write a message appropriate for the selected channel (SMS: ≤160 chars, conversational;
   Email: subject + body, structured)
2. Include an opt-out instruction (required)
3. Tailor content to the persona and lifecycle stage
4. Return a JSON object: `{"message": "...", "message_reason": "..."}`

**Logic:** LLM call. No tool use inside — just a single structured generation.

**No LLM call if `send=False`:** This node is only reached if `send=True`.

---

### Node 4 — `output_node`
**What it does:** Assembles the final output record from the state fields written by prior nodes.

**Reads:** All state fields.

**Writes:** `state["output"]` — the final dict to return to the caller.

**Logic:** Deterministic. Packages:
```json
{
  "task_id": "...",
  "send": true | false,
  "channel": "sms" | "email" | null,
  "message": "..." | null,
  "why": {
    "channel_reason": "...",
    "message_reason": "..." | null
  }
}
```

---

## 4. Graph Structure

```
START
  │
  ▼
consent_node
  │
  ├─ eligible_channels empty ──────────────────────────────► output_node ──► END
  │
  ▼
channel_node
  │
  ├─ send=False (no preference matches eligible) ──────────► output_node ──► END
  │
  ▼
composer_node
  │
  ▼
output_node
  │
  ▼
END
```

Conditional edges after `consent_node` and `channel_node` route directly to `output_node`
when no channel is available — `composer_node` is never called when there is nothing to send.

---

## 5. GraphState (TypedDict)

```python
class GraphState(TypedDict):
    # --- Input (from JSONL record) ---
    task_id: str
    persona: str
    lifecycle_stage: str
    consent: dict                   # {email_opt_in, sms_opt_in, voice_opt_in}
    channel_preferences: list[str]
    input: dict                     # {profile, property_name, timezone, last_interaction, ...}

    # --- Derived by nodes ---
    eligible_channels: list[str]    # consent_node
    selected_channel: str | None    # channel_node
    send: bool                      # channel_node
    channel_reason: str             # channel_node
    message: str | None             # composer_node
    message_reason: str | None      # composer_node

    # --- Final output ---
    output: dict                    # output_node
```

---

## 6. Backend File Structure

```
backend/
    main.py          → FastAPI: POST /run  (single record), POST /run-batch (all JSONL records)
    graph.py         → LangGraph StateGraph: wire the 4 nodes, define conditional edges, export compiled_graph
    state.py         → GraphState TypedDict
    agent.py         → run_record(record: dict) -> dict: parse JSONL record → init GraphState → invoke graph → return output
    nodes/
        consent.py          → consent_node(state: GraphState) -> GraphState
        channel.py          → channel_node(state: GraphState) -> GraphState
        composer.py         → composer_node(state: GraphState) -> GraphState  [LLM call here]
        output.py           → output_node(state: GraphState) -> GraphState
    data/
        sample.jsonl        → JSONL test records (converted from sample.json)
```

No ChromaDB. No SQLite. No eval runner. No frontend. Those come after PoC validates the core flow.

---

## 7. API Contract

### `POST /run`
**Request body:** one JSONL record as a JSON object (same shape as a single line of `sample.jsonl`)

**Response:**
```json
{
  "task_id": "prospect_welcome_day0",
  "send": true,
  "channel": "sms",
  "message": "Hi Taylor—welcome to Oak Ridge! ...",
  "why": {
    "channel_reason": "SMS selected: opted in and ranked #1 in preferences.",
    "message_reason": "Day-0 welcome message for a short-horizon prospect. Tour CTA to convert intent."
  }
}
```

### `POST /run-batch`
**Request body:** `{ "records": [ ... ] }` — array of JSONL records

**Response:** `{ "results": [ ... ] }` — one output object per input record, in order

---

## 8. Phase Build Order (PoC)

```
Phase 0  Architect   →  This document                                     Gate: human approval (AWAITING)
Phase 1  Developer   →  state.py, node stubs (4 files), graph.py shell    Gate: graph compiles with stubs
Phase 2  Developer   →  Implement all 4 nodes + composer LLM prompt       Gate: /run returns valid output for sample.jsonl records
Phase 3  Developer   →  main.py FastAPI routes + sample.jsonl conversion  Gate: POST /run and POST /run-batch work end-to-end
```

**Phase 1 deliverables:**
- `backend/state.py` — `GraphState` TypedDict exactly as defined in Section 5
- `backend/nodes/consent.py` — `consent_node` stub (signature + docstring, raises NotImplementedError)
- `backend/nodes/channel.py` — `channel_node` stub
- `backend/nodes/composer.py` — `composer_node` stub
- `backend/nodes/output.py` — `output_node` stub
- `backend/graph.py` — StateGraph with all 4 nodes wired, conditional edges defined, compiled graph exported; stubs will raise NotImplementedError but the graph must compile without error

**Phase 2 deliverables:**
- `backend/nodes/consent.py` — full implementation: map opt-in flags to eligible_channels
- `backend/nodes/channel.py` — full implementation: preference-ordered selection + channel_reason
- `backend/nodes/composer.py` — full implementation: OpenAI SDK call, structured JSON response, writes message + message_reason
- `backend/nodes/output.py` — full implementation: assemble final output dict
- Verified: `python -c "from graph import compiled_graph; print('OK')"` exits 0
- Verified: running a single sample record through `agent.run_record()` returns a valid output dict

**Phase 3 deliverables:**
- `backend/agent.py` — `run_record(record: dict) -> dict`: initializes GraphState, invokes compiled_graph, returns `state["output"]`
- `backend/main.py` — FastAPI with `POST /run` and `POST /run-batch`
- `backend/data/sample.jsonl` — `sample.json` converted to JSONL (one JSON object per line)
- Verified: `POST /run` with `sample.jsonl` record 1 returns correct channel and non-empty message
- Verified: `POST /run-batch` with both sample records returns 2 output objects

---

## Open Questions

1. **LLM provider confirmed?** Recommend OpenAI `claude-sonnet-4-6`. This avoids adding a second SDK dependency (no OpenAI SDK needed). Awaiting confirmation.

2. **`voice` channel scope?** `sample.json` has `voice_opt_in` but voice message generation differs significantly from SMS/email (script vs. text). For PoC, recommend treating voice as eligible for channel selection but generating a text script in `composer_node` with a note. Awaiting confirmation.

3. **`sample.jsonl` format?** The existing `sample.json` is a JSON array. The JSONL conversion (one object per line, no wrapping array) is a Phase 3 task. Confirm the file lives at `backend/data/sample.jsonl`.
