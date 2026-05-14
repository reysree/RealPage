# OpenAI Agents SDK Skill
# Context-Aware Message Sending Bot

## Purpose

This skill is read by the Developer Agent and the Solution Architect Agent
before writing or reviewing any OpenAI Agents SDK code.

It covers the full SDK surface: Agent, Runner, function_tool, context,
handoffs, guardrails, lifecycle hooks, streaming, and tracing.

Based on: openai-agents v0.0.7+ (May 2026)
Install: `pip install openai-agents`
Docs: https://openai.github.io/openai-agents-python/

Do not invent API signatures. Every pattern here is verified against the SDK.
If a pattern is not here, look it up — do not assume.

---

## Core Primitives

### Agent

The Agent class defines who the agent is and what it can do.
An Agent instance is stateless — it holds no conversation state.
State lives in the message history passed to Runner.run().

```python
from agents import Agent

agent = Agent(
    name="Outreach Agent",
    instructions="You are a property management assistant...",
    model="gpt-4o",           # always gpt-4o for this project
    tools=[tool_1, tool_2],   # list of @function_tool decorated functions
)
```

Key parameters:
- `name` — string, used in logs and traces
- `instructions` — the system prompt, sets identity and behavior
- `model` — model string, always "gpt-4o" in this project
- `tools` — list of tool functions decorated with @function_tool
- `handoffs` — list of other agents this agent can hand off to (Pattern B only)
- `output_type` — Pydantic model for structured output (when agent must return typed data)

The Agent is constructed once at module import time.
It is shared across all requests — safe because it is stateless.

---

### Runner

Runner.run() executes the agent loop: tool calls, results, final output.
It is always called with `await` — it is an async function.

```python
from agents import Runner

result = await Runner.run(
    starting_agent=agent,
    input=messages,  # list of dicts: [{"role": "user", "content": "..."}]
)

# Access the final response
final_text = result.final_output

# Access what happened during the run
for item in result.new_items:
    print(type(item).__name__, item)
```

`result.new_items` contains all events from this run:
- `MessageOutputItem` — the agent's text output
- `ToolCallItem` — a tool was called (has `.name` attribute)
- `ToolCallResultItem` — the tool returned a result
- `HandoffCallItem` — agent handed off to another agent

Extracting tools used:
```python
tools_used = []
for item in result.new_items:
    if hasattr(item, "name") and item.name not in tools_used:
        tools_used.append(item.name)
```

---

### function_tool

The @function_tool decorator wraps a Python function as an agent tool.
The function's docstring becomes the tool description the model reads.
The function's type annotations become the tool's JSON schema.

```python
from agents import function_tool
from backend.schemas import ToolResultEnvelope

@function_tool
def search_knowledge_base(query: str) -> str:
    """
    TOOL: search_knowledge_base
    Purpose: Retrieve relevant documents from the property knowledge base.
    When called: When the user asks a factual question about properties,
        units, amenities, policies, or lease terms.
    Returns: {"results": [{"content": str, "metadata": dict, "relevance_score": float}]}
    Note: Atomic — one responsibility, no overlap with other tools.
    """
    # implementation
    return ToolResultEnvelope(error=None, result={"results": [...]}).model_dump_json(
        exclude_none=True
    )
```

Rules for function_tool:
- Parameter types must be serializable: str, int, float, bool, list, dict
- **Return type must be `str`** at the decorator boundary — build a **`ToolResultEnvelope`** in this project (`backend.schemas`) and return **`model_dump_json(exclude_none=True)`**. Generic SDK samples may use plain `json.dumps` if the serialized shape matches `{error?, error_code?, result?}`.
- Docstring fields are required: TOOL, Purpose, When called, Returns, Note
- `When called` must name the specific user intent that triggers this tool — not a restatement of Purpose
- `Returns` must show the actual JSON shape with field names and types — not prose
- One function, one responsibility — never combine two actions in one tool

---

## Conversation History

The Agent has no memory between Runner.run() calls.
History must be loaded from storage and injected with every call.

```python
async def run_agent(user_message: str, history: list[dict]) -> dict:
    # history is loaded from SQLite — list of {"role": ..., "content": ...} dicts
    messages = history + [{"role": "user", "content": user_message}]

    result = await Runner.run(
        starting_agent=agent,
        input=messages,
    )

    return {
        "response": result.final_output,
        "tools_used": _extract_tools_used(result),
    }
```

History format — matches OpenAI message format exactly:
```python
[
    {"role": "user", "content": "What units are available?"},
    {"role": "assistant", "content": "There are 1BR and 2BR units available..."},
    {"role": "user", "content": "What is the price of the 1BR?"},
]
```

---

## Context Injection

For passing request-scoped data (session_id, user_id, tenant_id) into tools
without threading them through every function signature, use the SDK context.

```python
from agents import Agent, Runner, function_tool
from dataclasses import dataclass

@dataclass
class RequestContext:
    session_id: str
    tenant_id: str

@function_tool
def log_tool_usage(action: str) -> str:
    """
    TOOL: log_tool_usage
    Purpose: Logs an agent action with session context.
    When the agent calls this: When an action should be recorded.
    Returns: Confirmation JSON.
    Note: This tool is atomic.
    """
    # context is injected by the SDK — available as a special parameter
    # see RunContextWrapper pattern in SDK docs for full usage
    from backend.schemas import ToolResultEnvelope

    return ToolResultEnvelope(error=None, result={"logged": action}).model_dump_json(
        exclude_none=True
    )
```

For simpler cases in this project: pass session_id as a closure variable
captured when the tool is defined, or derive it from the call site.

---

## Handoffs (Pattern B — Multi-Agent)

Handoffs let one agent pass control to another.
Used when the current agent cannot handle the request and a specialist can.

```python
from agents import Agent, handoff

leasing_agent = Agent(
    name="Leasing Specialist",
    instructions="You handle unit availability, pricing, and lease terms.",
    tools=[search_units, check_availability, calculate_rent],
)

maintenance_agent = Agent(
    name="Maintenance Specialist",
    instructions="You handle maintenance requests and service history.",
    tools=[submit_request, check_request_status],
)

orchestrator = Agent(
    name="Outreach Orchestrator",
    instructions="""
    Route the user to the correct specialist:
    - Leasing questions → Leasing Specialist
    - Maintenance requests → Maintenance Specialist
    """,
    handoffs=[
        handoff(leasing_agent),
        handoff(maintenance_agent),
    ],
)
```

The handoff carries the full conversation context automatically.
The specialist agent receives the history and continues from where the orchestrator left off.

Do not use handoffs unless you are implementing Pattern B.
For single-domain applications, use Pattern A (one agent, multiple tools).

---

## Guardrails

Guardrails run before the agent processes input or after it produces output.
Use them for input validation and output filtering.

```python
from agents import Agent, input_guardrail, GuardrailFunctionOutput
from pydantic import BaseModel

class SafetyCheck(BaseModel):
    is_safe: bool
    reason: str

@input_guardrail
async def fair_housing_guardrail(
    ctx,
    agent: Agent,
    input: str | list,
) -> GuardrailFunctionOutput:
    """
    Blocks queries that ask for recommendations based on protected class data.
    Fair Housing Act: race, color, national origin, religion, sex,
    familial status, disability.
    """
    # Run a fast classification — lightweight model or keyword check
    flagged_terms = ["race", "nationality", "religion", "children", "disability"]
    input_text = input if isinstance(input, str) else str(input)
    is_flagged = any(term in input_text.lower() for term in flagged_terms)

    return GuardrailFunctionOutput(
        output_info=SafetyCheck(
            is_safe=not is_flagged,
            reason="Fair Housing guardrail" if is_flagged else "ok"
        ),
        tripwire_triggered=is_flagged,
    )

# Apply to agent
agent = Agent(
    name="Outreach Agent",
    instructions=SYSTEM_PROMPT,
    tools=[...],
    input_guardrails=[fair_housing_guardrail],
)
```

When `tripwire_triggered=True`, the agent run stops and raises `InputGuardrailTripwireTriggered`.
Catch this in the route handler and return an appropriate message.

---

## Structured Output

When the agent must return typed data (not free text), use `output_type`.

```python
from pydantic import BaseModel

class UnitRecommendation(BaseModel):
    unit_id: str
    property_name: str
    monthly_rent: float
    reasoning: str

agent = Agent(
    name="Recommendation Agent",
    instructions="Recommend the best matching unit based on the user's criteria.",
    output_type=UnitRecommendation,
    tools=[search_units],
)

result = await Runner.run(starting_agent=agent, input=messages)
# result.final_output is a UnitRecommendation instance — fully typed
recommendation: UnitRecommendation = result.final_output
```

Use structured output when:
- The caller needs to process the response programmatically
- The response must conform to a schema for downstream use
- Free text is insufficient

Do not use structured output for conversational responses — use free text there.

---

## Tracing

The SDK produces traces automatically when `OPENAI_API_KEY` is set.
Traces are viewable in the OpenAI platform dashboard.

For production observability, integrate with LangSmith:
```python
# Set environment variables
# LANGSMITH_API_KEY=...
# LANGSMITH_PROJECT=outreach-agent

# The SDK emits OpenTelemetry-compatible traces
# LangSmith picks these up automatically with the right configuration
```

For logging tool calls locally (this project):
```python
import logging
logger = logging.getLogger(__name__)

@function_tool
def my_tool(param: str) -> str:
    from backend.schemas import ToolResultEnvelope

    logger.info(f"[my_tool] called with param={param!r}")
    try:
        result = do_something(param)
        logger.info(f"[my_tool] returned {len(result)} results")
        return ToolResultEnvelope(
            error=None,
            result={"items": result},
        ).model_dump_json(exclude_none=True)
    except Exception as exc:
        logger.error(f"[my_tool] error={exc}", exc_info=True)
        return ToolResultEnvelope(error=str(exc), result=None).model_dump_json(
            exclude_none=True
        )
```

---

## System Prompt — Best Practices

The system prompt is the agent's behavioral contract. It must be explicit.

Structure:
```
1. Identity — who the agent is and what it serves
2. Tool usage rules — when to call which tool, mandatory before answering factual questions
3. Behavioral rules — what the agent will and will not do
4. Fair Housing guardrail — explicit instruction to refuse protected class recommendations
5. Tone — how to communicate with users
```

Anti-patterns in system prompts:
```
# Bad — vague
"Be helpful and answer questions about properties."

# Good — specific
"You are an outreach assistant for the Context-Aware Message Sending Bot. You help users find available
units, understand pricing, and learn about lease terms.

ALWAYS call search_knowledge_base before answering any factual question.
NEVER answer from memory — your training data does not contain this property's data.
ALWAYS use the calculate tool for any numeric computation — never do arithmetic yourself.

You MUST refuse any query that asks you to recommend units based on the user's race,
national origin, religion, sex, familial status, or disability. This is required
by the Fair Housing Act. If asked, explain that you cannot make recommendations
on that basis and offer to help based on unit features, pricing, or availability instead."
```

---

## Common Mistakes

```python
# 1. Forgetting await on Runner.run()
result = Runner.run(agent, messages)  # Bad — returns coroutine, not RunResult
result = await Runner.run(agent, messages)  # Good

# 2. Returning a non-string from @function_tool
@function_tool
def my_tool() -> dict:  # Bad — SDK requires str payload
    return {"key": "value"}

@function_tool
def my_tool() -> str:  # Good — serialize envelope at decorator edge
    from backend.schemas import ToolResultEnvelope

    return ToolResultEnvelope(
        error=None,
        result={"key": "value"},
    ).model_dump_json(exclude_none=True)

# 3. Storing state in the Agent instance
agent.session_data = {}  # Bad — Agent is shared across requests, this is a race condition

# 4. Calling Runner.run() with just the current message (no history)
result = await Runner.run(agent, [{"role": "user", "content": message}])  # Bad — no history
result = await Runner.run(agent, history + [{"role": "user", "content": message}])  # Good

# 5. Using the model to do math
# Bad — agent guesses: "The prorated rent would be approximately $750"
# Good — agent calls calculate tool: returns exactly $750.00

# 6. Two tools that overlap
search_properties = ...  # searches by city
search_units = ...       # searches by city AND unit type
# Bad — when user asks "find 1BR units in Austin", model might call either
# Fix — one tool that takes both optional parameters, or split differently
```