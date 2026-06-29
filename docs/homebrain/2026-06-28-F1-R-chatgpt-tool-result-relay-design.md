# F1-R — ChatGPT Tool Result Relay (Design Addendum)

**Date:** 2026-06-28
**Status:** Design proposal only — **no implementation**. Stop for review.
**Parent:** [F1 — Synchronous Command Result Framework](2026-06-28-F1-synchronous-command-result-design.md)
**Triggered by:** T11 Gate G1 failure — see the *Outcome* section of
[plans/2026-06-28-F1-T11-T12-script-migration.md](plans/2026-06-28-F1-T11-T12-script-migration.md).

## Problem

F1 built and validated everything *except the last hop to ChatGPT*:

| Leg | State |
|---|---|
| Resolver `/command` endpoint (auth, 200/4xx) | ✅ live |
| `CommandResult` contract (`chat_text`/`spoken_text`/…) | ✅ live |
| Capability interface (`resolve→validate→execute`) | ✅ live |
| Resolver = sole TTS owner (Piper speaks `spoken_text`) | ✅ live |
| HA `rest_command` + `response_variable` **capture** of `chat_text` | ✅ proven (T9) |
| **ChatGPT receives `chat_text` and reports it** | ❌ **unsolved** |

**Root cause (proven in T11):** the HA script relayed `chat_text` via
**`set_conversation_response`**. That action sets the *Assist pipeline's* response text. The **OpenAI
Conversation agent ignores it** when it invokes a script **as a tool** — it composes its own reply
(`"Playing <query>."`) from the user's request, regardless of the script's conversation response. A
sentinel string placed in `set_conversation_response` was **not** echoed by ChatGPT, while the tool was
confirmed to have run. So `set_conversation_response` is the wrong channel for an LLM tool call.

**Goal of F1-R:** deliver `CommandResult.chat_text` to ChatGPT as the **actual tool/function result**
(the value the model consumes to form its answer), not as a side-effecting conversation response.

## Background — how HA hands a tool result to the OpenAI agent

When a script is exposed to the assistant and the OpenAI Conversation agent calls it, HA passes the
script's **returned response** (a `ServiceResponse`) back to the model as the **function-call result**.
That return value — not `set_conversation_response` — is what the model reads. The model then writes a
natural-language reply grounded in that result. Two levers therefore matter:

1. **Make the script return a response** containing `chat_text` (so the function result is non-empty
   and carries our text).
2. **Make the model relay it faithfully** (so the answer *is* `chat_text`, not a paraphrase or a
   confabulated "Playing X").

## Options considered

### A — Script returns a `ServiceResponse` (via `stop` / `response_variable`) as the tool result
End `script.play_music` by **returning** a response built from `r.content.chat_text` (HA's supported
"script returns data to its caller" mechanism — the `stop` action's `response_variable`), instead of
calling `set_conversation_response`. The OpenAI agent then receives `{ "chat_text": "…" }` (or the
bare string) as the function result.

- **Pros:** smallest change; keeps the **three existing scripts**; resolver untouched; fully reversible
  (restore the event-firing backup, as in T11). No HA custom code, no HA restart.
- **Cons / unknowns:** must confirm on the **live HA version** that a *response-returning script* is (i)
  permitted as an LLM tool and (ii) its response is surfaced to the OpenAI agent as the function result.
  T9 only proved a script can **capture** a `rest_command` response internally — not that the script's
  **own** returned response reaches the model. This is the single thing to probe first.
- On its own, A makes the result *available* to the model but does not guarantee verbatim wording → pair
  with B.

### B — Agent instruction for faithful/verbatim relay (config-only)
Add to the OpenAI Conversation agent's **Instructions** (its system prompt in the integration options,
**not** a model change): *"When a tool returns a `chat_text` field, reply to the user with exactly that
text and nothing else."*

- **Pros:** config-only; additive; reversible (edit the prompt back); composes with A or D; no model
  change (instruction text only).
- **Cons:** LLM adherence is high but not contractual — verify with a sentinel; keep the instruction
  narrow so it doesn't distort other replies.

### C — HA entity / state sensor bridge — **rejected**
Resolver writes the result to an `input_text`/sensor; ChatGPT reads it back.
- **Rejected:** needs a **second round-trip** (a separate "get last result" tool call), is **race-prone**
  (which request's result?), adds latency, and widens state exposure. Strictly worse than A/D. Kept only
  as a theoretical last resort.

### D — Custom `llm.Tool` integration (resolver-backed tool) — robust fallback
A small HA **custom integration** registers a first-class LLM tool whose handler calls the resolver
`/command` and **returns `CommandResult` directly** as the tool result.

- **Pros:** architecturally cleanest — the resolver's result **is** the tool result *by construction*;
  no script / `response_variable` / `set_conversation_response` indirection. Could **consolidate** the
  three scripts into one resolver-backed tool. The Python-3.5 constraint does **not** apply (this code
  runs in HAOS's Python, not on the resolver host; the resolver `/command` stays as-is).
- **Cons:** heaviest option — a `custom_components/` integration to write, install, and maintain;
  **HA restart** to load; and it **changes the exposed-tool surface** (so it needs explicit sign-off
  against the "no new tools unless justified" rule). HA's built-in *MCP Server/Client* integrations
  don't fit cleanly (they expose/consume HA tools, not arbitrary external tools to the OpenAI agent),
  so a local `llm.Tool` proxy is the concrete form of D.

## Recommendation — phased, verify before building

1. **Phase 0 — Probe A+B (no production change).** On a *throwaway* edit of `play_music` (immediately
   reverted, exactly like the T11 sentinel test): return a **sentinel** `chat_text` via the
   `stop`/`response_variable` mechanism, add the Phase-B verbatim instruction, ask ChatGPT to play a
   guaranteed no-match, and check whether the reply **contains the sentinel**. This definitively answers
   whether the script's returned response reaches the OpenAI agent. *(Design only here — the
   implementation plan will script this probe; nothing runs until approved.)*
2. **If the probe passes → adopt A+B** as the F1-C/F1-D relay mechanism (re-run T11/T12 with the script
   returning a response instead of `set_conversation_response`). Smallest, reversible, keeps three
   scripts.
3. **If the probe fails → escalate to D** (custom `llm.Tool`), with explicit user sign-off on the
   tool-surface change and an HA restart.
4. **C stays rejected.**

| Option | Change size | Reversible | Keeps 3 scripts | HA restart | Confidence it relays |
|---|---|---|---|---|---|
| A+B | small (scripts + prompt) | yes | yes | no | **to be proven by Phase-0 probe** |
| C | medium | yes | adds state+tool | maybe | low (race/2-hop) — rejected |
| D | large (custom integration) | yes (uninstall) | consolidates | yes | high (result *is* the tool return) |

## Invariants preserved (all options)
- Resolver remains **sole TTS owner**; `spoken_text` is spoken once during `/command`. F1-R changes only
  how **`chat_text`** (text) reaches ChatGPT.
- **Additive / reversible**: every change has a backup or uninstall path; the Inc-0/1 **event path**
  stays the working baseline until a relay mechanism is validated.
- **Python 3.5** governs only the resolver host (unaffected; `/command` is unchanged). Any HA-side code
  (Option D) runs in HAOS's own Python.
- **No GPT model change.** Option B edits the agent's *instruction text*, which is prompt config, not a
  model swap.
- **Secrets** stay in 0600 files; the existing `X-Resolver-Key` continues to guard `/command`.
- **No new tools exposed** under A+B. Option D's tool-surface change requires explicit approval.

## Open questions for the reviewer
1. Approve **Phase 0** (the A+B sentinel probe) as the next executable step?
2. If A+B works, re-migrate **all three** scripts, or **music only** first (as in T11)?
3. If we fall to D, is **consolidating** the three scripts into one resolver-backed tool acceptable, or
   keep three named tools for ChatGPT's tool-selection clarity?

## Out of scope
No implementation; no T12; no model change; no Inc 2. This document only proposes the mechanism and the
verification order. On approval, the next artifact is an implementation plan that starts with the
Phase-0 probe.
