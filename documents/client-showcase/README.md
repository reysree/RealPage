# Client showcase

Runnable demo cases live in two sibling folders:

- `expected-input/` — POST to `/run` or paste into the Case runner (`output` plus `latency_ms`), one JSON object per scenario.
- `expected-output/` — illustrative decision shape per scenario (`send`, `next_message`, `next_action`; live message body may vary).

Matching pairs use the same base name, for example:

- `expected-input/01-send-sms-new-prospect.json`
- `expected-output/01-send-sms-new-prospect.json`

## Scenarios

1. `01-send-sms-new-prospect` — consent allows SMS and SMS is the first preference.
2. `02-send-email-long-horizon` — only email is consented for an open prospect.
3. `03-fallback-to-email` — SMS is preferred but not consented, so the agent falls back to email.
4. `04-fallback-to-sms` — email is preferred but not consented, so the agent falls back to SMS.
5. `05-voice-only` — voice is the only consented/preferred channel.
6. `06-no-send-all-opted-out` — every channel is opted out, so the agent should not communicate.
7. `07-no-send-security-block` — input contains prompt-injection text, so the agent blocks before channel selection.
