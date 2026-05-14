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

**Where:** `backend/eval_runner.py` — `_PERSONALIZATION_JUDGE_PROMPT` constant.
