# ADR — Assist routing: split control and knowledge agents

> **Status:** Accepted and **implemented live** 2026-08-03 (config only — no firmware, no resolver code).
> Revises decision **(c)/NL-01** of `plans/2026-07-16-s1b-2-satellite-full-assistant.md` by *adding* a second
> agent; it does **not** weaken prefer-local on the control path.
> Related: `2026-07-15-s1b-satellite-ceiling-reply-design.md` (reply route), `assistant-capabilities.md`
> (exposed tool set), CHANGELOG 2026-08-02/03.

## Context

The satellite ran a single agent: `conversation.openai_conversation` (gpt-4o-mini) with the **Assist** LLM API,
behind `prefer_local_intents=true`. Two problems surfaced in live use.

**1. It could not answer questions needing live data.** Asked for the weather in Calgary it replied *"I can't
check the weather for Calgary right now"* — correctly, since it had no web access and only
`weather.forecast_home` exposed. It answered *"100 EUR in CAD"* fine, because that comes from training
knowledge. The distinction is **static knowledge vs live data**, not a defect.

**2. Enabling web search on that same agent would have been the wrong fix.** That agent holds tools that
**control the house**. Feeding it untrusted web content puts *untrusted input*, *private context* and *ability
to act* in one place — the combination that makes prompt injection consequential rather than theoretical.
Today the exposed surface is small (media + volume + weather), so the blast radius is "annoying"; the moment
locks or thermostats are exposed, it is not.

A third option — **inverting to LLM-first with local fallback** — was considered and rejected (below).

## Decision drivers

1. **Never combine web-sourced text with house-control tools in one agent.**
2. **Keep command handling deterministic** — NL-01's original goal; live evidence this week showed the LLM
   mis-selecting tools (volume requests landing on `ceiling_pause`, the wrong station played).
3. **Keep the house working without the internet.** Local intents must remain the primary command path.
4. **No firmware.** The brick-risk OTA gate has been avoided all along and must stay avoided.
5. Latency and cost belong on the *rare* path, not on every "play radio".

## Options

- **A — Enable web search on the existing agent.** One toggle. Rejected: puts untrusted content in the
  tool-capable agent (driver 1).
- **B — Invert to LLM-first, local as fallback.** Rejected: every command pays LLM latency (~2–10 s; ~10 s
  measured in Slice 2), commands become non-deterministic, an outage cannot be detected without first waiting
  for it to fail (so the degraded mode is *slower* than the healthy one), and every utterance leaves the house.
  It also trades a **safe** failure mode ("didn't understand") for an **unsafe** one (**wrong action taken**).
- **C — Split agents, addressed by separate wake words (chosen).** Control keeps tools and no web; a second,
  **tool-less** agent gets web search. The wake word selects the layer.
- **D — Server-side capability in the resolver** for specific live data (the existing `news` pattern). Not
  exclusive with C; still the better answer for data we *know* we want (see Consequences).

## Decision — adopt C

| | Control | Knowledge |
|---|---|---|
| Wake word | **Okay Nabu** (slot 1) | **Hey Jarvis** (slot 2) |
| Pipeline | `Living Room ChatGPT` `01kxygpr39jas5hgsf28cph108` | `Living Room Knowledge` `01kz45tkgbnsn57gpyj25vyfd0` |
| Agent | `conversation.openai_conversation` (gpt-4o-mini) | `conversation.openai_conversation_2` (gpt-4o) |
| `prefer_local_intents` | **true** | **false** |
| Control Home Assistant | **Assist** (tools) | **none** (no tools, no entities) |
| Web search | off | **on**, Medium context, links off, **home location off** |

`prefer_local_intents=false` on slot 2 is deliberate: the **wake word alone** decides which layer answers, so
there is no ambiguity about who handled an utterance — the exact confusion that made volume commands so hard
to diagnose. Web-search *links* are off so Piper does not read URLs aloud; **home location is off** because the
one implicitly-local question that matters ("what is the weather") is already answered better, faster and
without egress by the local intent layer.

## Verification (live, 2026-08-03)

- Knowledge agent, live data: *"what is the weather in calgary"* → returned **today's** forecast (web search
  working).
- **Tool isolation, the load-bearing check** — same question to both:
  `KNOWLEDGE → "I can't check what's playing on the ceiling speakers… ask the main assistant"` ·
  `CONTROL → "Nothing is playing right now."` The knowledge agent cannot see or act on the house; the control
  agent is unchanged.

## Consequences

- **Exposure is unchanged.** No new entities exposed; `expose_new_entities` stays off. The knowledge agent has
  **no** LLM API, so exposure is irrelevant to it — `assistant-capabilities.md` stays in lockstep.
- **Cost lands on the rare path.** gpt-4o serves occasional questions; every command still runs on
  gpt-4o-mini or, better, on local intents at zero cost.
- **Two things to say, not one.** The user must remember which wake word does what. Accepted: it is also the
  mechanism that makes the routing unambiguous.
- **Spoken output needs prompt discipline.** The first live web answer came back as markdown headings and an
  hourly bullet list in Fahrenheit — unusable through a speaker. The knowledge agent's instructions must
  forbid markdown/lists/URLs and prefer metric. This is a *prompt* obligation, not a code one.
- **Long answers required a resolver change.** `say_reply_timeout_ms` 30 s → **180 s**, since the poll
  otherwise truncates a long reply and replays the music over its tail (CHANGELOG 2026-08-03).
- **Option D still stands.** For data we know we want (weather being the obvious one), a resolver capability
  following the `news` precedent remains preferable to web search: deterministic, free, testable, and the
  model never sees raw web text. C handles the open-ended tail; D handles the known cases.
- **Slot 2 is now consumed.** It was reserved in decision (d) as the fallback for a *local-only deterministic*
  pipeline. If that fallback is ever needed, it now conflicts with this ADR and one of the two must give.

## Rollback

1. Set `select.respeaker_living_room_wake_word_2` → `no_wake_word` (instantly disables the knowledge path).
2. Set `select.respeaker_living_room_assistant_2` → `preferred`.
3. Delete the `Living Room Knowledge` pipeline and the second conversation subentry.
4. Nothing else to undo — the control agent, all scripts, and the resolver are untouched by this ADR.

> **Rollback for this document:** `git revert` on `homebrain/s1b-2-slice4-duck-ownership`, or delete this file.
