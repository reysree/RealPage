# Architecture Decision Skill
# RealPage Lumina — AI Property Management Platform

## Purpose

This skill is read by the Solution Architect Agent before producing any architecture decision.
It defines the decision framework for choosing between agent patterns, tool designs,
eval strategies, and data layers.

Do not choose a pattern because it sounds impressive.
Choose the pattern that matches the problem's actual complexity.
Over-engineering is a defect, not a feature.

---

## Pattern Decision Framework

### Step 1 — Classify the Problem

Answer these four questions before choosing a pattern:

| Question | Yes → Consider | No → Avoid |
|----------|---------------|------------|
| Is there a single conversational domain? | Pattern A | Pattern B |
| Are there multiple distinct domains that need their own tools? | Pattern B | Pattern A |
| Does any workflow require an auditable, identical execution path? | Pattern C | Pattern A or B |
| Does the conversation have distinct phases that change what the agent can do? | Pattern D | Pattern A or B |

---

### Pattern A — Single Agent + Atomic Tools (OpenAI Agents SDK)

**Use when:**
- One primary domain (e.g. leasing assistant, maintenance tracker)
- Tool boundaries are clear and non-overlapping
- Conversational interface — the user leads, the agent responds
- No regulatory requirement for deterministic step audit trails

**Structure:**
```
Agent (GPT-4o + system prompt)
    ├── tool_1: search_knowledge_base   → ChromaDB retrieval
    ├── tool_2: calculate               → deterministic math
    └── tool_3: ...                     → one more atomic action
```

**Code signature:**
```python
from agents import Agent, Runner, function_tool

agent = Agent(
    name="Lumina Leasing Agent",
    instructions=SYSTEM_PROMPT,
    model="gpt-4o",
    tools=[search_knowledge_base, calculate],
)

result = await Runner.run(starting_agent=agent, input=messages)
```

**When to reject:**
Do not use Pattern A when a workflow requires the same steps to execute
in the same order every time with a verifiable audit trail. That is Pattern C.

---

### Pattern B — Multi-Agent with Handoffs (OpenAI Agents SDK)

**Use when:**
- Multiple distinct domains exist (leasing, maintenance, finance, operations)
- Each domain has its own tool set with no overlap between domains
- Routing between domains is clean and well-defined
- Each specialist agent can be tested and audited independently

**Structure:**
```
Orchestrator Agent
    ├── handoff → Leasing Agent    (tools: search_units, check_availability)
    ├── handoff → Maintenance Agent (tools: submit_request, check_status)
    └── handoff → Finance Agent    (tools: calculate_rent, view_ledger)
```

**Code signature:**
```python
from agents import Agent, handoff

leasing_agent = Agent(name="Leasing", tools=[search_units, check_availability])
maintenance_agent = Agent(name="Maintenance", tools=[submit_request, check_status])

orchestrator = Agent(
    name="Lumina Orchestrator",
    instructions="Route to the correct specialist based on user intent.",
    tools=[handoff(leasing_agent), handoff(maintenance_agent)],
)
```

**When to reject:**
Do not use Pattern B if the domains are not clearly distinct — routing ambiguity
causes incorrect handoffs. If in doubt, start with Pattern A and add handoffs
when a second distinct domain genuinely needs isolation.

---

### Pattern C — SDK Agent + LangGraph Inside a Tool

**Use when:**
- Conversational flexibility is needed (user can ask anything, agent responds naturally)
  AND a specific subprocess must execute identically every time with a full audit trail
- Regulatory context: Fair Housing, lease application processing, credit checks
- The subprocess is complex enough that it needs state, branching, and checkpoints

**How it works:**
```
SDK Agent (conversational face)
    └── @function_tool: process_lease_application
            └── LangGraph workflow (invisible to the agent)
                    ├── Step 1: validate_identity
                    ├── Step 2: run_credit_check
                    ├── Step 3: evaluate_income_ratio
                    └── Step 4: generate_decision
```

The SDK agent calls `process_lease_application` as a regular tool call.
It gets back a structured result. LangGraph ran inside — the agent never knows.

**Why this works for compliance:**
LangGraph produces identical execution graphs for identical inputs.
Those graphs are provable audit trails for HUD investigations under the Fair Housing Act.
The SDK conversation is flexible. The subprocess is deterministic. Both are preserved.

**When to reject:**
Do not add LangGraph if there is no compliance or audit requirement.
If the workflow just needs multiple steps, use Pattern D instead.
LangGraph adds complexity — it must earn its place.

---

### Pattern D — Phase-Based Orchestration (SDK)

**Use when:**
- The conversation has distinct phases that change what the agent can do
- Example: intake → qualification → recommendation → confirmation
- Each phase gates the next — you cannot skip ahead
- The agent's tool access and context changes per phase

**How it works:**
```python
# Phase 1: Intake — agent collects basic info
intake_agent = Agent(
    name="Intake",
    instructions="Collect: name, desired move-in date, unit type preference.",
    tools=[save_intake_data],
)

# Phase 2: Qualification — agent checks eligibility
qualification_agent = Agent(
    name="Qualification",
    instructions="Check income requirements and availability.",
    tools=[check_income_ratio, search_available_units],
)

# Phase 3: Recommendation — agent presents options
recommendation_agent = Agent(
    name="Recommendation",
    instructions="Present the top 3 matching units from the qualification results.",
    tools=[search_knowledge_base, calculate],
)
```

Each phase is a separate agent with separate tools and a separate system prompt.
The orchestrator hands off between phases using recall state to carry context.

**This is the Zahan AI pattern** — phase-limited tool access, dynamic context per phase.
It prevents the agent from jumping ahead, hallucinating about unavailable options,
or accessing tools that are not appropriate for the current workflow stage.

**When to reject:**
Do not use Phase-Based if the conversation does not have genuine phases.
Single-domain Q&A does not need this — use Pattern A.

---

## Tool Design Rules

### Rule 1: One Responsibility

Every tool does exactly one thing. If you can write "AND" in the tool description,
split it into two tools.

Good: `search_knowledge_base` → retrieves documents from ChromaDB
Bad: `search_and_summarize` → retrieves AND summarizes

### Rule 2: No Overlap

No two tools should be callable for the same situation.
If two tools could both answer the same user query, the model will hallucinate
which one to call. Remove the overlap before deployment.

Tool audit — for every pair of tools, ask:
"Is there any user query where the model might call either of these?"
If yes: redesign.

### Rule 3: Structured Return

Tools return **structured data**, not presentation prose. The agent builds the user-facing layer.

- **In-process helpers (RealPage orchestration):** return `ToolResultEnvelope` with a dict `result` and optional `error` / `error_code` — no `json.dumps` between callers in the same Python process.
- **SDK-exposed `@function_tool` targets:** the decorated function returns **`str`**. Serialize envelopes with `ToolResultEnvelope(...).model_dump_json(exclude_none=True)` (or equivalent).

```python
# Structured (in-process)
return ToolResultEnvelope(error=None, result={"value": value, "units": "USD"})

# SDK boundary
return ToolResultEnvelope(error=None, result={...}).model_dump_json(exclude_none=True)

# Bad — prose substitutes for data
return f"The result is {value} dollars"
```

### Rule 4: Deterministic Math Lives in Tools

The LLM must not do arithmetic. Any calculation — total, average, prorate,
percentage — is routed to the `calculate` tool. LLMs hallucinate numbers.
Tools do not.

---

## Eval Design Rules

### Mandatory Cases (every domain)

1. **Grounding check** — factual query answered from tool output, not LLM training data
2. **Calculation check** — numeric query routes to calculate tool, not freeform LLM
3. **Out-of-scope check** — agent declines gracefully for queries outside its domain
4. **Multi-turn check** — agent uses conversation history correctly across turns
5. **Fair Housing check** — agent refuses any recommendation based on protected class data

### Eval Runner Pattern

Evals run from the CLI — never inline in the application code.

```python
# eval_runner.py — run with: python eval_runner.py

import asyncio
from agent import run_agent

CASES = [
    {
        "id": "grounding_001",
        "input": "What units are available at Sunset Ridge?",
        "expected_tool": "search_knowledge_base",
        "grading": "response mentions specific unit types from ChromaDB data"
    },
    {
        "id": "calculation_001",
        "input": "What is my prorated rent if I move in on the 15th for a $1500/month unit?",
        "expected_tool": "calculate",
        "grading": "response contains correct prorated amount"
    },
    # ... more cases
]

async def run_evals():
    results = []
    for case in CASES:
        result = await run_agent(case["input"], history=[])
        results.append({
            "id": case["id"],
            "tools_used": result["tools_used"],
            "expected_tool": case["expected_tool"],
            "tool_correct": case["expected_tool"] in result["tools_used"],
            "response": result["response"],
        })
    return results
```

### LLM-as-Judge for Grading

For cases where the correct answer cannot be checked programmatically,
use a separate LLM call as the judge. The judge prompt is specific — not "is this good?"

```python
JUDGE_PROMPT = """
You are evaluating an AI assistant's response.

User query: {query}
Agent response: {response}
Evaluation criterion: {criterion}

Respond with ONLY:
PASS — if the response meets the criterion
FAIL — if the response does not meet the criterion
FLAG — if the response is ambiguous and needs human review

Then on the next line, one sentence explaining your decision.
"""
```

---

## LangGraph vs SDK — When to Raise It

If any of these conditions are true, LangGraph is worth considering:

| Condition | Why it matters |
|-----------|---------------|
| Workflow must produce identical steps for identical inputs | Legal audit trail |
| Steps must be provable to a regulator | Fair Housing / HUD |
| Partial completion must be resumable | Long-running workflows |
| Steps require human approval checkpoints | Lease signing, credit approval |

If none of these conditions apply: use the SDK. Do not add LangGraph for complexity's sake.

When LangGraph is used, it runs inside a `@function_tool` — invisible to the SDK agent.
The agent calls a tool and gets a result. LangGraph ran inside. The interface never changes.