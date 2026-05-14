# Insights

## Personalization Judge — SMS Tone Scoring

**What we needed to add:** A channel-aware tone rule to the personalization judge prompt in `backend/eval_runner.py`.

**Why:** The judge prompt's tone criterion ("overall tone feels tailored to this specific person rather than a generic template") consistently scored SMS messages at 0.0 even when all available profile fields were correctly included. This capped the maximum achievable score for SMS cases at 0.8, below the 0.85 `personalization_score_min` threshold used in `prospect_welcome_day0`.

**Root cause:** SMS character constraints make it structurally impossible to match the warmth and narrative richness of an email. A short, complete, conversational SMS that includes `first_name`, `city_interest`, and `property_name` was being penalised for brevity — a format constraint, not a quality failure.

**Fix — rubric rewritten to be field-based, no channel dependency:**

The original rubric had a 0.2 "tone" criterion (subjective, unrelated to profile fields) that acted as a gatekeeper. A case with only `first_name` + `city_interest` + `property_name` could score at most 0.8 even when all fields were correctly used, because tone is hard to demonstrate when there are few fields to work with. This was a rubric design flaw — not an SMS/email issue.

The correct design: using every present profile field = baseline passing score (0.85+). Extra fields push the score above 0.85 toward 1.0.

**New rubric in `_PERSONALIZATION_JUDGE_PROMPT`:**
- first_name used correctly: 0.30
- property_name mentioned naturally: 0.25
- At least one present interest field used (city_interest / amenity / move timeline): 0.30
- Each additional present interest field also used: +0.075 each, capped at 0.15 bonus
- Explicit instruction: do not award or deduct for tone, style, channel format, or message length


---

## Client review — constraints and thresholds (2026-05-14)

**Persona and lifecycle (PoC scope)**  
The API contract currently allows only `persona: "prospect"` and `lifecycle_stage` in `["new", "open"]`. Additional personas and stages are intentionally excluded until the client expands the product scope; the schema uses Literal types so adding values is a deliberate, versioned change.

**`profile.first_name`**  
Required on every request. Other profile fields (`city_interest`, `amenity_interest`, etc.) remain optional and should not be invented in copy when absent.

**`no_sensitive_discrimination` on constraints**  
This flag is **optional** on each case. When omitted or null, the stricter protected-class and discrimination checks in `check_compliance` are not applied beyond baseline fair-housing handling. When set to **true**, the compliance tool enforces the protected-class term surface and optional LLM fair-housing judge path. **Open question for the client:** confirm whether this should default to true for all production campaigns, or only for segments where enriched profile data could imply targeting.

**Required assertion states**  
Every case must carry the same ordered triple: `consent_verified`, `fair_housing_check_passed`, `brand_style_applied`. The agent does not emit a sendable message when consent, compliance (including fair housing / opt-out), or upstream checks fail; blocked runs return `send: false` and `next_action.type: human_in_the_loop` for manual review.

**Thresholds**  
`p95_latency_ms`, `personalization_score_min`, and `safety_violations_max` are required on every eval case. `reply_classification_f1_min` remains optional until reply classification / sandbox features exist.

---

## Eval harness integrity (2026-05-14)

**Composer:** CLI `python -m backend.evals.runner` always POSTs `/run` with production `compose_message` (OpenAI chat). The JSONL `expected` message is **not** wired into scoring.

**Personalization:** When `personalization_score_min` is set and the agent sends, `personalization_pass` is emitted. It is **false** when `_score_personalization` cannot return a score.

**P95 with multiple samples:** For multiple timed samples, latency uses repeated POST `/run` only; **one** scoring pass runs afterward.

**pytest:** Autouse fixtures patch `compose_message` with input-shaped synthetic output and fix the judge score so CI stays deterministic without billed OpenAI for those unit tests.
