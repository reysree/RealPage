# RealPage PoC — Build Plan
**Date:** 2026-05-13
**Goal:** Working demo ready for Thursday panel

---

## What This System Does

One JSON record comes in. One decision comes out.

```
IN  → prospect profile, consent, preferences
OUT → should we send? which channel? what message? when?
```

No conversation. No memory. No session. Stateless per request.

---

## Folder Structure

```
realpage-poc/
├── backend/
│   ├── main.py               → FastAPI app, /run and /health routes
│   ├── agent.py              → Agent definition, system prompt, tool registration
│   ├── schemas.py            → All Pydantic input/output models
│   ├── constants.py          → Fair Housing rules, brand style guide
│   ├── tools/
│   │   ├── __init__.py       → ALL_TOOLS list
│   │   ├── consent.py        → check_consent tool
│   │   ├── channel_selector.py → select_channel tool
│   │   ├── message_composer.py → compose_message tool
│   │   ├── timing.py         → determine_send_time tool
│   │   └── compliance.py     → check_compliance tool
│   ├── data/
│   │   └── sample.jsonl      → 2 test records
│   └── eval_runner.py        → CLI eval, runs both records, prints PASS/FAIL
├── frontend/
│   ├── src/
│   │   ├── App.jsx           → two panel UI
│   │   ├── api.js            → fetch wrapper for /run
│   │   ├── main.jsx
│   │   └── index.css
│   ├── package.json
│   └── vite.config.js
├── tests/
│   ├── test_schemas.py
│   ├── test_tools.py
│   └── test_agent.py
├── requirements.txt
└── README.md
```

---

## The 5 Tools

| Tool | File | What it does | How |
|------|------|-------------|-----|
| `check_consent` | `tools/consent.py` | Reads consent flags, returns eligible channels | Python — dict lookup |
| `select_channel` | `tools/channel_selector.py` | Picks first eligible channel from preferences | Python — loop |
| `compose_message` | `tools/message_composer.py` | Writes personalized body, subject, CTA | LLM — GPT-4o |
| `determine_send_time` | `tools/timing.py` | Calculates send time in recipient timezone | Python — datetime |
| `check_compliance` | `tools/compliance.py` | Checks Fair Housing, PII, opt-out in message | Python — regex + rules |

**Rule:** If `select_channel` returns null → agent returns `send: false` immediately. Other tools are not called.

---

## Schemas (schemas.py)

```
ConsentRecord     → email_opt_in, sms_opt_in, voice_opt_in (all bool)
UserProfile       → first_name, city_interest, amenity_interest
InputRecord       → property_name, move_date_target, last_interaction,
                    timezone, language, profile
TestCase          → task_id, persona, lifecycle_stage, consent,
                    channel_preferences, input, assertions, thresholds, expected
MessageOutput     → channel, send_at, subject, body, cta
NextAction        → type, name
AgentOutput       → send, next_message, next_action
RunRequest        → same shape as TestCase
RunResponse       → output, tools_used, latency_ms
```

---

## Constants (constants.py)

Two strings. Always injected into LLM calls in full. Never in ChromaDB.

```python
FAIR_HOUSING_RULES = """
The Fair Housing Act prohibits discrimination based on:
race, color, national origin, religion, sex, familial status, disability.
Never reference or imply decisions based on any of these.
"""

BRAND_STYLE_GUIDE = """
- Address by first name
- Friendly, warm, not corporate
- One clear CTA per message
- SMS: short, numbered reply options
- Email: brief subject, 2-3 sentences
- Always end with opt-out instruction
- Never use: "pursuant to", "as per", "please be advised"
"""
```

---

## Agent (agent.py)

```python
Agent(
    name="Outreach Agent",
    instructions=SYSTEM_PROMPT,   # includes FAIR_HOUSING_RULES + BRAND_STYLE_GUIDE
    model="gpt-4o",
    tools=ALL_TOOLS,
    output_type=AgentOutput
)
```

System prompt tells the agent:
- Always call check_consent first
- If no eligible channel → return send: false, stop
- Always call check_compliance after compose_message
- Never guess consent — only read from input

---

## API Routes (main.py)

Only two routes:

```
POST /run       → takes RunRequest, returns RunResponse
GET  /health    → returns { status: ok }
```

That is all. No run history. No batch route. Add later if time allows.

---

## Compliance Check Logic (tools/compliance.py)

Three checks in one tool. All must pass:

```
1. Fair Housing    → LLM judge, temperature 0.0, score must be 1.0
2. PII check       → regex for phone number and email patterns
3. Opt-out check   → "STOP" must appear in message body
```

If any fail → `passed: false` → agent does not send.

---

## Send Time Logic (tools/timing.py)

```
1. Read last_interaction timestamp
2. Add 1 day
3. Convert to recipient timezone
4. Set time to 9:00 AM
5. Return ISO 8601 string with UTC offset
```

Always 9am next day local time. Hard rule. No exceptions for PoC.

---

## Next Action Logic (inside compose_message or agent)

```python
days_until_move = (move_date - today).days

if persona == "prospect" and days_until_move < 45:
    next_action = { "type": "start_cadence", "name": "prospect_welcome_short_horizon" }

if persona == "prospect" and days_until_move >= 45:
    next_action = { "type": "start_cadence", "name": "prospect_welcome_long_horizon" }
```

---

## Eval Runner (eval_runner.py)

Simple CLI script. No framework.

```
python eval_runner.py

→ loads sample.jsonl
→ runs each record through /run
→ prints per-record PASS/FAIL
→ prints aggregate score at the end
```

PASS means:
- Correct channel selected
- send_at in correct timezone
- Compliance passed
- next_action type is correct

---

## Frontend (App.jsx)

Two panels. Nothing more.

```
Left panel  → paste JSON record → Run button
Right panel → show output:
                should_send: true/false  (large, clear)
                channel chosen
                generated message body
                compliance checks PASS/FAIL
                send_at time
                next_action
```

---

## Build Order

```
Phase 1 → constants.py + schemas.py + tests/test_schemas.py
Phase 2 → all 5 tools  + tests/test_tools.py
Phase 3 → agent.py     + tests/test_agent.py
Phase 4 → main.py      (just /run and /health)
Phase 5 → eval_runner.py (run both JSONL records, both PASS)
Phase 6 → frontend (two panel UI, paste and run)
```

---

## Install Command

```bash
pip install openai fastapi uvicorn pydantic pytz pytest pytest-asyncio httpx
```

---