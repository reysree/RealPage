# Insights

## Personalization Judge — SMS Tone Scoring

**What we needed to add:** A channel-aware tone rule to the personalization judge prompt in `backend/eval_runner.py`.

**Why:** The judge prompt's tone criterion ("overall tone feels tailored to this specific person rather than a generic template") consistently scored SMS messages at 0.0 even when all available profile fields were correctly included. This capped the maximum achievable score for SMS cases at 0.8, below the 0.85 `personalization_score_min` threshold used in `prospect_welcome_day0`.

**Root cause:** SMS character constraints make it structurally impossible to match the warmth and narrative richness of an email. A short, complete, conversational SMS that includes `first_name`, `city_interest`, and `property_name` was being penalised for brevity — a format constraint, not a quality failure.

**Instruction added to `_PERSONALIZATION_JUDGE_PROMPT`:**
> Channel-aware tone rule: SMS messages are limited to a short character count by format.
> For SMS, award the full 0.2 tone points when all available profile fields are present and
> the message is conversational in register — do not penalise brevity as a lack of personalisation.
> For email or voice, apply the tone criterion at full strictness.

**Where:** `backend/eval_runner.py` — `_PERSONALIZATION_JUDGE_PROMPT` constant.

**Secondary fix — explicit channel threading:** The judge prompt alone was not sufficient because the judge was inferring the channel from message content rather than receiving it as a fact. `_score_personalization` was updated to accept a `channel` parameter, and `score_output` now passes `generated_message.get("channel")` explicitly. The channel is included in the JSON payload sent to the judge so the SMS-specific tone rule is applied precisely, not guessed from format cues.
