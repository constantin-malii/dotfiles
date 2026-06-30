# HomeBrain Personal / Communication Layer — Architecture Brainstorm

**Date:** 2026-06-28
**Status:** Brainstorm / architecture review — *no implementation*
**Author:** Constantin (with senior-architect assist)
**Scope constraint:** Design only. Do not modify the live host, Home Assistant, the media/radio resolver, or expose new tools.
**Reconciliation:** Reconciled 2026-06-28 against the live repo docs (ONBOARDING, F1, F1-R, assistant-tooling-design, assistant-capabilities, local-music-architecture, F1-R music-remigration). Docs were read as *current-state truth*; design positions remain the author's own. Changes from the first (pre-reconciliation) draft are flagged inline with **⟲ Reconciled**.

> **Naming note (⟲ Reconciled).** In HomeBrain, "**assistant**" already means the **ChatGPT voice tool surface for the media system** (`assistant-tooling-design.md`, `assistant-capabilities.md`). To avoid overloading the term, this document names the new layer the **Personal / Communication Layer (PCL)** and refers to its service as **`homebrain-companion`** (working name, see §A naming decision). "Resolver" = the existing `mass-resolver`. "Media assistant" = the existing ChatGPT media tool surface.

---

## 1. Executive Summary

HomeBrain today is a **deterministic command resolver** (`mass-resolver`) for home/media intents (music, radio, transport; News/Status/Acquire on the roadmap). It exposes a synchronous `POST /command` HTTP endpoint returning a **`CommandResult`** and owns execution and TTS. The F1/F1-R line of work made command outcomes *truthful*: `validate`-before-`execute` so "not found" is honest, plus a proven mechanism (F1-R) to relay the real result text to ChatGPT.

The proposed **Personal / Communication Layer (PCL)** is a different animal from the resolver. The resolver is *deterministic, action-oriented, near-stateless, low-privacy, and TTS-owning*. The PCL is *conversational, stateful, memory-bearing, and personal-data-bearing* — questions, drafts, decisions, notes, receipts, reminders, family logistics. These accumulate, must be recalled, and carry privacy weight.

**Core recommendation:** Build the PCL as a **separate sibling service** (`homebrain-companion`), *not* inside `mass-resolver` and *not* primarily inside Home Assistant. It **reuses the resolver's proven patterns** — the `resolve→validate→execute→CommandResult` lifecycle, the `CommandResult` wire contract, the LAN-bound shared-secret HTTP ingress, and the F1-R relay — but owns its **own datastore, security perimeter, and lifecycle**. (⟲ Reconciled: the resolver's capability framework is genuinely reusable, which makes "just add modules to the resolver" more tempting than the first draft implied — but data gravity, privacy, iteration isolation, **and the resolver host's Python 3.5.2 constraint** still tip firmly to a separate, containerized service.)

**Contract recommendation (⟲ Reconciled — changed):** Do **not** fork the wire contract. The ChatGPT relay is built entirely on `CommandResult.chat_text`/`spoken_text`, so **anything the PCL exposes to ChatGPT must emit a `CommandResult`-compatible payload and use the F1-R relay verbatim.** Keep a richer **internal** `AssistantResult` model for conversation/memory, but **project it down to a `CommandResult`-shaped payload at the LLM edge.** (First draft proposed a parallel contract; reading F1-R showed the relay *is* the contract.)

**MVP recommendation:** The first safe slice is **notes only — create / recall / forget — on local SQLite, validated over HTTP and exposed to ChatGPT via the F1-R relay only after a sentinel-probe**, with audit + delete from day one. (Durable reminders move to P1; light decisions and short-term referents move to P2 — see §15.) **Gate status (2026-06-29):** the two prerequisite gates are now **met** (F1-R closed/accepted complete; Speaker reconnect bug fixed/deployed — CHANGELOG 2026-06-28/29) and the **F1-R relay is landed**, so **PCL P0 is unblocked**. No receipts/images, no cloud, no multi-user, no semantic memory in the MVP.

The rest of this document argues these positions with trade-offs, the security model, and a phased roadmap with an explicit "do not build yet" list — slotted against the existing Inc/F1 roadmap.

---

## 2. Current Architecture Recap (⟲ Reconciled to the live system)

```
                       ┌─────────────────────────────────────────────┐
   Phone voice ───────▶│            Home Assistant (HAOS VM)          │
   (text replies only) │  Assist pipelines:                          │
                       │   • "Home Assistant" (deterministic, def.)  │
   Ceiling speakers ◀──│   • "ChatGPT" (OpenAI Conv, gpt-4o-mini)    │
   (TTS via host)      │  Exposed tools = a few helper SCRIPTS only  │──┐ tool call
                       │  Pipeline reply-TTS: OFF (Piper crashes)    │  │ (HTTP relay)
                       └───────────────┬─────────────────────────────┘  │
                          speaks via   │ rest_command POST /command       ▼
                          host Piper   │ (X-Resolver-Key, response_variable)
                          (NAT-IP URL) ▼                       ┌──────────────────────┐
                       ┌───────────────────────┐              │   mass-resolver       │
                       │ media_player.ceiling  │◀─ plays ──────│  POST /command :8770  │
                       │ _speakers (MA Univ.)  │   via MA      │  (192.168.122.1)      │
                       └───────────────────────┘              │  resolve→validate→    │
                                  ▲                            │  execute → CommandRes │
                       ┌──────────┴──────┐                     │  modules: core/music/ │
                       │ Music Assistant │◀── MA WS ───────────│  radio/news*/acquire*/│
                       │ (HAOS add-on)   │                     │  status*  (*=stubbed) │
                       └─────────────────┘                     │  SOLE TTS OWNER       │
                                                               │  Python 3.5.2 host    │
                                                               └──────────────────────┘
```

**Load-bearing current-state facts (⟲ Reconciled — these correct/replace first-draft assumptions):**

- **Synchronous `/command` + `CommandResult` are live** (F1). The resolver already has HTTP ingress at `http://192.168.122.1:8770/command`, LAN-bound, guarded by an `X-Resolver-Key` shared-secret header (0600 file). Capability lifecycle = `resolve → validate → execute → handle() → CommandResult`. Adapters: HA-event (legacy), HTTP (new), MCP (future) — all over the same `handle()`.
- **`CommandResult` schema (live):** `ok, intent, request_id, spoken_text, chat_text, error{code,reason}, metadata, actions[]`. `chat_text` is *always present* (what ChatGPT reports). `spoken_text` = TTS line or `null` (null ⇒ say nothing). `error.code` enumerated. `metadata` is capability-specific (e.g. `find` → `stations[]`/`count`). `actions[]` is **reserved for follow-up suggestions** ("say 'play the first one'").
- **ChatGPT relay (F1-R, proven):** `set_conversation_response` is **ignored** by the OpenAI Conversation agent when it calls a script as a tool. The working path: the HA script **returns** `{chat_text}` as its `ServiceResponse` via `stop`+`response_variable`; a one-line agent Instruction ("relay `chat_text` verbatim") yields exact fidelity. This is the *only* validated way text reaches ChatGPT.
- **Resolver is the SOLE TTS owner.** It speaks `spoken_text` once via host Piper during `/command`. **Success is silent** (`spoken_text` null on success); ChatGPT's relayed `chat_text` is the only success confirmation. Failures/announcements speak exactly once. Pipeline reply-TTS is **disabled** (Piper crashes it).
- **Voice I/O constraints:** phone gets **text replies only** — TTS URLs resolve to the NAT IP `192.168.122.10`, which the **phone/LAN cannot reach** (macvtap split); only the **host** can fetch them, so ceiling-speaker TTS works but phone TTS does not.
- **Exposure discipline:** only a small set of purpose-built `script.*` are exposed to the conversation agents (+ `weather`). `expose_new_entities` is off. Rule: **nothing is exposed to ChatGPT until validated.**
- **Host runtime:** the resolver runs on Ubuntu 16.04 / **Python 3.5.2** (no f-strings; "Python 3.5-safe" is a carried constraint). HAOS-side code (if any) runs in HAOS's own Python.
- **Roadmap state (⟲ updated 2026-06-29):** Inc 0 (foundation) ✅, Inc 1 (radio) ✅, **F1** (CommandResult framework) ✅, **F1-R** relay ✅ **closed/accepted complete** (all three media scripts — `play_music`/`play_radio`/`find_stations` — relay `chat_text` via `stop`+`response_variable`; CHANGELOG 2026-06-28/29), **Inc 4A Status / now-playing ✅ shipped 2026-06-29** (`script.media_status`), Inc 2 News, Inc 3 Acquire — note the Status/household line brushes against PCL territory (§13).

**What the resolver is good at and should stay good at:** turning a clear intent into a verified action with a truthful result, and being the single TTS owner. That purity is an asset. The PCL must not pollute it.

---

## 3. Problem Statement

We want a **Personal / Communication Layer** handling:

- asking questions / brainstorming decisions
- drafting messages (draft only; a human sends)
- setting timers / reminders
- saving receipts
- taking notes
- tracking lightweight decisions
- family / home logistics
- later: querying prior notes / receipts / decisions

These differ from resolver commands along axes that drive the architecture:

| Axis | Resolver (`/command`) | PCL |
|---|---|---|
| **Determinism** | High — intent → action | Low–medium — open-ended dialogue |
| **State** | Near-stateless per call | Stateful: short-term context + long-term memory |
| **Data gravity** | ~Zero (transient) | High — accumulates notes/receipts/decisions |
| **Privacy weight** | Low (which song played) | High (family logistics, receipts, personal notes) |
| **Failure mode** | "Action didn't happen" | "Wrong memory recalled / data lost / data leaked" |
| **TTS** | Owns it; success silent | Must not create a 2nd TTS path (§6/§9) |
| **Runtime** | Pinned to host Python 3.5.2 | Wants modern Python (containerized) |
| **LLM role** | Tool-caller picks an intent | LLM is a first-class reasoning participant |

The central question is a **boundary** question (keep the resolver pure; give personal data a clear owner and security perimeter; show ChatGPT one coherent surface) and a **contract** question (conversational + memory affordances vs. a result type designed for "did this action happen") — the latter now constrained by the proven F1-R relay.

---

## 4. Proposed Architectural Options

Evaluated against the *monolith vs sibling vs separate-service* and *data-boundary* workflows, **updated** with current-state facts.

### Option A — Extend `mass-resolver` (add PCL modules: `note`, `reminder`, `decide`, …)

- ✅ Maximum pattern reuse — the `resolve/validate/execute/CommandResult` lifecycle and `/command` ingress already exist; new capabilities would be near-free to wire. (⟲ Reconciled: this is *more* attractive than the first draft credited.)
- ✅ One surface, one relay, one auth.
- ❌ **Couples a pure, near-stateless, media service to a stateful, data-heavy, privacy-heavy one** — different data gravity in one process.
- ❌ Drags personal/financial/family data into the resolver's security perimeter (which already holds `.ha_token`/`.ma_token` and drives playback).
- ❌ **Pins the PCL to Python 3.5.2** — a poor base for a data/memory service (modern SQLite features, typing, libraries).
- ❌ Blast radius: a note-store bug or migration can take down music/radio — the daily-driver shares fate with the prototype.

**Verdict:** Tempting given the reusable framework, but wrong on data gravity, privacy, runtime, and blast radius.

### Option B — Separate sibling service `homebrain-companion` (recommended)

A new, **containerized** service (modern Python) beside the resolver. Owns its datastore, its `/assist` (or `/companion`) HTTP ingress, its internal `AssistantResult`. **Reuses** the resolver's lifecycle pattern, the `CommandResult` wire contract, the LAN shared-secret ingress pattern, and the F1-R relay. **Calls** the resolver `/command` when a conversation needs a deterministic action ("…play the second one").

- ✅ Clean separation of data gravity and security perimeter; one clear owner for personal data.
- ✅ Independent lifecycle — iterate hard without risking music/radio uptime.
- ✅ **Escapes the Python 3.5 constraint** via its own container.
- ✅ Maximum *pattern* reuse with minimum *coupling* — same shapes, separate process/store.
- ⚠️ Two services to operate; mitigated by shared conventions + one ingress pattern + (optionally) one gateway.
- ⚠️ Needs an internal assistant→resolver call path (LAN HTTP, shared secret).

**Verdict:** Best fit — extract precisely because data boundary, privacy, runtime, and scaling/iteration profiles differ, while still inheriting the resolver's proven contracts.

### Option C — Mostly inside Home Assistant (todo/helpers/timers + OpenAI Conversation)

- ✅ Reuses HA-native timers, todo lists, notifications, user model, voice pipeline.
- ❌ HA's entity/helper model is a poor fit for free-form notes, decisions-with-rationale, receipt blobs, and recall/query.
- ❌ Conversation memory and "show me the camping decision" are awkward in HA.
- ❌ Constraint: **do not change Home Assistant** — anything heavy here violates scope now.
- ❌ Couples a personal knowledge base to HA's upgrade cadence and quirks; and pipeline reply-TTS is off anyway.

**Verdict:** HA is the right *owner of device-native primitives* (timer firing, notifications, the voice pipeline) but the wrong *owner of personal knowledge/memory*. Borrow its primitives; don't build the brain there.

### Option D — Fully separate independent product

- ✅ Maximum long-term freedom.
- ❌ Massive scope; duplicates auth/voice/device access; premature.

**Verdict:** Over-engineering now. Revisit only if the PCL outgrows the home.

### Decision matrix

| Criterion (weight) | A: in-resolver | B: sibling | C: in-HA | D: separate |
|---|---|---|---|---|
| Keeps resolver pure (high) | ✗ | ✓ | ✓ | ✓ |
| Fits personal-data gravity (high) | ✗ | ✓ | ✗ | ✓ |
| Clear security perimeter (high) | ✗ | ✓ | ~ | ✓ |
| Reuses resolver lifecycle/contract/relay (med) | ✓ | ✓ | ~ | ✗ |
| Reuses device/voice/timer primitives (med) | ~ | ~ | ✓ | ✗ |
| Escapes Python 3.5 host constraint (med) | ✗ | ✓ | ✓ | ✓ |
| Low operational overhead (med) | ✓ | ~ | ✓ | ✗ |
| Iterate without risking media uptime (med) | ✗ | ✓ | ~ | ✓ |
| Respects "don't change HA" now (high) | ✓ | ✓ | ✗ | ✓ |
| Time-to-MVP (med) | ✓ | ✓ | ~ | ✗ |

**Winner: Option B** — sibling service that **borrows C's HA primitives** (timer firing, notifications, ceiling TTS) and **inherits the resolver's contracts/relay**, with a clean delegated call to `/command`.

---

## 4A. Architecture Pattern Analysis (⟲ Added 2026-06-28)

§4 chose *where the service lives*. This section evaluates the *internal patterns* the design leans on, against four simpler alternatives, and explains why the composite is best on the criteria that matter (multiple clients, privacy, future satellites, future MCP, notes/reminders/receipts, media handoff).

### The five patterns we adopt
1. **Hub-and-spoke companion.** `homebrain-companion` is the central **policy + context + memory hub**; clients (satellite, mobile, web, HA Assist, dashboard, automation, MCP) are **thin spokes** that submit context; HA and `mass-resolver` are **downstream systems** the hub orchestrates. One brain, many edges.
2. **Client adapter / output adapter.** Every input client **normalizes into a common request** (`InteractionContext` / `AssistantRequest`, §13A) via an *input adapter*; every output is **selected by routing policy** and rendered by an *output adapter* (text · source-device audio · ceiling/media zone · satellite voice · push · dashboard · silent). Adding a client = adding an adapter, **not** changing the core.
3. **`ResponseRoutingPolicy`.** Deterministic, privacy-aware, confirmation-aware, room/person-aware-later (§6A.5). Output destination is a *decision*, never a wired default.
4. **Event bus (HA).** HA carries **events, entities, notifications, delivery**. It does **not** own reasoning, memory, or long-term assistant state. HA is transport + actuation; the companion is the brain.
5. **Context store.** The companion's **own store** holds short-term referents ("the second one") *and* durable notes/reminders/decisions — **never rely solely on ChatGPT memory.**

### Simpler alternatives, and why each falls short
- **PCL inside `mass-resolver`:** couples stateful private data to the pure media executor, pins it to Python 3.5.2, shares blast radius. Loses privacy isolation and independent iteration. (§4 A.)
- **Mostly inside HA:** HA's entity/helper model is wrong for documents/memory/recall, and it would make HA the brain (violates pattern 4) and tie personal data to HA's upgrade cadence. (§4 C.)
- **Satellites directly control outputs:** hard-codes "input device = output device", with no central policy and no privacy gate → private content spoken on shared zones, no cross-client coherence. Directly violates §6A.
- **ChatGPT memory only:** not durable, not local, not private, not deterministically queryable, not truthful (the F1-R lesson), and gives no indexable referents. Loses everything pattern 5 provides.

### Why the composite wins, by criterion
| Criterion | Why hub + adapters + policy + event-bus + store wins |
|---|---|
| **Multiple clients** | Input adapters normalize any client to one request shape; one brain serves all; zero per-client logic duplication. |
| **Privacy** | Deterministic policy + `privacy_level` gating in **one** place; data local-first in **one** owned store. Alternatives scatter or expose it. |
| **Future satellites** | A satellite is just another client adapter + output adapter; routing already abstracts destination → **no re-architecture**. |
| **Future MCP / custom tools** | MCP is another spoke *and* the companion can **expose its own capabilities as MCP tools** over the same `resolve→validate→execute→CommandResult` lifecycle. |
| **Notes / reminders / receipts** | Require a durable, queryable, private store (pattern 5) — only the dedicated companion store provides it; HA and ChatGPT-memory cannot. |
| **Media handoff** | The hub orchestrates downstream: media intents delegate to `/command`; resolver stays pure and the sole media-TTS owner. Clean seam. |

### Conclusion
Adopt the composite. It is the only option that simultaneously delivers **one brain, many thin edges, deterministic privacy/routing, a private durable store, and a clean downstream handoff**. Each simpler alternative optimizes a single axis at the cost of privacy, durability, or coupling. (Reinforces §4–§5 and §18.)

---

## 5. Recommended Architecture

**`homebrain-companion`: a containerized sibling that owns conversation + memory + personal data, reuses the resolver's lifecycle and `CommandResult`/relay contracts, delegates device actions to the resolver `/command`, and delegates device-native primitives (timer firing, notifications, ceiling TTS) to Home Assistant.**

```
                        ┌──────────────────────────────────────────────┐
        Voice / chat ──▶│           Home Assistant (HAOS VM)            │
                        │  "ChatGPT" pipeline · OpenAI Conv (4o-mini)   │
                        │  helper scripts = tool surface · timers ·     │
                        │  notifications · ceiling TTS (host Piper)     │
                        └───┬───────────────────────────────┬──────────┘
                    tool:   │ home/media (existing)   tool:  │ companion (new, F1-R relay)
                            ▼                                ▼
                ┌────────────────────┐         ┌──────────────────────────────┐
                │   mass-resolver     │◀────────│   homebrain-companion          │
                │   POST /command     │ calls   │   POST /companion (LAN+secret) │
                │   → CommandResult   │ /command│   resolve→validate→execute     │
                │   SOLE TTS owner    │         │   → AssistantResult            │
                │   Python 3.5.2      │         │     ↳ projects to CommandResult│
                └────────────────────┘         │       at the ChatGPT edge       │
                                               │   short-term context (sessions)│
                                               │   long-term memory store        │
                                               │   modern Python (container)     │
                                               └───────────┬────────────────────┘
                                                           │ owns
                                                 ┌─────────▼──────────┐
                                                 │ Companion datastore │
                                                 │ SQLite (+ blob dir) │
                                                 │ notes · decisions   │
                                                 │ receipts · prefs    │
                                                 │ reminders · audit   │
                                                 └────────────────────┘
```

**Ownership split (the load-bearing decisions):**

1. **Resolver owns** deterministic device/media actions, their truthful `CommandResult`, **and TTS**. Unchanged. The PCL *calls it* for "…play the second one."
2. **Home Assistant owns** device identity, the voice pipeline, notifications, and **timer/reminder firing**. It is the I/O + primitives layer. (No HA changes for the MVP; wiring comes in a later, deliberate phase.)
3. **homebrain-companion owns** the conversation, short-term context, long-term memory, and all personal data. It is the brain + memory layer.
4. **The LLM** is the NL/reasoning surface. It never holds durable state; the companion is the system of record. It receives **only** `CommandResult`-shaped payloads via the F1-R relay.

Three crisp perimeters: *devices* (HA), *deterministic actions + TTS* (resolver), *personal cognition + data* (companion). Each fails, deploys, and is secured independently.

---

## 6. Home Assistant Integration Model (⟲ Reconciled — TTS ownership corrected)

**Principle: HA is an I/O and primitives provider, not the PCL's database — and TTS has exactly one owner.**

What HA provides / is used for:
- **Voice in/out** through the existing "ChatGPT" pipeline. The PCL returns `chat_text`; ChatGPT relays it. **On the phone this is text only** (NAT-IP TTS unreachable) — a real constraint for any "spoken" PCL feature on mobile.
- **Reminder/timer *firing* and notifications.** When a reminder is due, the *firing* is an HA timer/automation or a mobile **push** (push reaches the phone where TTS cannot). The PCL decides *what/when*; HA delivers.
- **Ceiling TTS for proactive speech** (e.g. a reminder spoken in the room) via the existing un-exposed `script.ceiling_announce` primitive — which already resumes prior playback after announcing.
- **One conversation tool** exposed to OpenAI Conversation that routes to the companion (mirroring the resolver's script-as-tool pattern) — added only when validated.

**TTS discipline (⟲ Reconciled — important):** the resolver is the **sole TTS owner**, and success is **silent** (ChatGPT text is the confirmation). The PCL must **not** introduce a second uncoordinated TTS path. Concretely:
- For LLM-mediated turns: PCL returns `chat_text` only, **no TTS** (matches the current "success is silent" model).
- For proactive speech (reminder firing): route through the **single** ceiling-announce primitive, owned/triggered HA-side — never a parallel TTS call from the PCL that could double-speak.

**Integration mechanics (future, not MVP — "don't change HA" holds):**
- A single companion conversation tool forwarding utterance + minimal context (room, optional user) to `POST /companion`, returning `chat_text` via the **F1-R `stop`+`response_variable` relay** (the only proven path).
- Reminder firing: companion stores `due_at`; an HA-side timer/automation or push fires at due-time and reads back via ceiling-announce (room) and/or push (phone).
- **No HA YAML/automation/script changes in the MVP.** The MVP can be exercised over HTTP and validated before any HA wiring, exactly as F1 validated `/command` before touching scripts.

---

## 6A. Satellite / Whole-House Communication Model (⟲ Added 2026-06-28)

**Premise (design correction).** The purchased voice satellites are intended to become **general household communication endpoints** — not just media-control microphones. This breaks the system's current core assumption that *output goes to the ceiling speakers*. With satellites, **where a request comes from and where its answer goes are separate decisions**, and the answer's destination depends on *who asked, from where, on what device, and how sensitive the content is*. Output destination becomes a **policy decision**, never a hard-coded default.

### 6A.1 Satellites as general voice I/O endpoints
Future voice I/O for: **questions, brainstorming, reminders, household messages, timers, notes, communication with family members, and media commands** — the full PCL surface, not just media.

### 6A.2 Separate the conflated concepts
The design must distinguish, as first-class and independent:
- **input device** (where the utterance was captured)
- **output device** (where the response is delivered — *not necessarily the same*)
- **source room** and **target room / person**
- **reply mode:** voice · text · both · silent

Today these collapse into "mic → ceiling." That collapse must end before satellites carry real household communication.

### 6A.3 Do not assume the ceiling speakers
Illustrative content-class → channel mapping (made concrete by the policy in 6A.5):
- **music / radio / media** → ceiling speakers / configured media zone
- **personal answer** → the requesting satellite (only if non-private) **or** phone text
- **family announcement** → selected satellites / whole house (**after confirmation**)
- **receipts / notes** → **text-first**, optional voice confirmation
- **reminders** → phone notification, satellite announcement, or both — per reminder policy **and** privacy
- **mobile / web request** → reply on **that** client, text-first

### 6A.4 `InteractionContext` (concept)
Every interaction carries context that the routing decision consumes:

| Field | Meaning |
|---|---|
| `client_type` | `satellite` \| `mobile` \| `web` \| … |
| `source_device` | the specific device that captured the request |
| `source_room` | room of the source device |
| `user` | requesting user (if identity is available; see 6A.7) |
| `reply_mode` | `voice` \| `text` \| `both` \| `silent` |
| `privacy_level` | content sensitivity (e.g. `public` \| `household` \| `private`) |
| `target_device` | explicit output device, if specified/derived |
| `target_room` | explicit output room, if specified/derived |
| `target_person` | explicit recipient, if specified/derived |
| `conversation_id` | session linkage for short-term context (§8.1) |

### 6A.5 `ResponseRoutingPolicy` (concept)

> **Scope (⟲ 2026-06-29):** `ResponseRoutingPolicy` decides **where a response is delivered** (output side). It is **separate** from the **`InteractionAudioPolicy`** (§6B), which decides whether to **pause/duck same-room media when an interaction *starts*** (input side). Do not conflate them or fold one into the other — `ResponseRoutingPolicy` gains **no** `media_interruption` field.

Given an `InteractionContext` **plus the result's content class/privacy**, the policy **chooses one (or more) output channel(s)** from: **text** (to the source client) · **source-device audio** (the satellite that asked) · **ceiling speakers / media zone** · **push notification** · **dashboard** · **silent result**.

**Default routing (policy-driven — explicitly NOT hard-coded):**
- **Mobile / web clients →** reply on **that client, text-first**.
- **Satellite clients →** reply through the **configured house voice/audio route only when** the response is **non-private** or **household/media-related**.
- **Music / radio / media commands →** **ceiling speakers / configured media zone**.
- **Private notes, receipts, reminders, personal questions →** **do not speak on the ceiling speakers by default**; **return text to the initiating client**, or **ask for confirmation before speaking aloud**.
- **Household announcements →** route to **selected satellites / rooms / whole-house after confirmation**.
- **Timers / reminders →** **confirm to the source client**; later notify/speak based on the reminder's policy.

> **Reject the hard-code.** "Satellite input always replies on the ceiling speakers" is **wrong** and must not be wired in. A reasonable *current practical default* may be: *satellite media/household commands → ceiling speakers; mobile/web → same client* — but that is a **policy default, overridable per `InteractionContext`**, not a fixed rule.

### 6A.5.1 Routing precedence (⟲ Added 2026-06-28)

When inputs conflict, the policy resolves them in this **fixed order** (earlier wins):

1. **Safety / privacy rules (highest).** Private content must **not** be spoken on shared speakers by default; sensitive notes/receipts/reminders take a text/private route **or require confirmation**. *These can never be overridden by a lower rule* — a client hint or a "tell everyone" cannot force private content aloud without explicit confirmation.
2. **Explicit user instruction.** "tell everyone", "send this to my phone", "say it in the kitchen" — an in-utterance directive beats defaults/hints (but still passes the safety gate above; e.g. "tell everyone <private thing>" → confirm first).
3. **Capability / domain default.** media → ceiling speakers / media zone; personal reminder → source-client confirmation + reminder policy; receipt/note query → text/private by default.
4. **Client capabilities.** what the device can actually do — screen present? voice output present? notification present? (Don't pick a channel the client can't render.)
5. **Client routing hints.** `routing_hints.reply_mode` = voice/text/both/silent — a *preference*, **overridable by any rule above**.
6. **System fallback (lowest).** the **safest available** route — usually **text/private**, else **silent + audit**.

> The ordering encodes the core principle (§18.4.2): **privacy and safety dominate; the client's hint is the weakest signal; and when nothing else decides, fail safe.**

**Worked examples (showing the override):**

| Scenario | Winning rule | Decision |
|---|---|---|
| Satellite asks "what's my receipt total?" | (1) privacy | **Do not speak aloud by default** → text to source / phone; or confirm before speaking. Beats the satellite's voice default. |
| Mobile asks a general question | (3) domain + (4) capability | Reply **on the mobile client**, text-first. |
| Satellite asks to **play music** | (3) media default | Output to **ceiling speakers / media zone** (non-private, media) — delegate to `mass-resolver`. |
| "**Tell everyone** dinner is ready" | (2) explicit instruction | **Household announcement** to selected satellites/whole-house — **confirmation if required** (non-private content, so confirm-then-broadcast). |
| Automation fires a reminder | (3) reminder policy | Notify/speak per the **reminder's policy**, **not** the original client's hint; private reminder → push/text, not a shared-zone announce. |

### 6A.6 Ownership (architecture update)
- **Home Assistant owns** the **satellite entities, routing primitives, assist pipelines, and room/device metadata** (which satellite is in which room, its capabilities, its pipeline binding) — and **executes** the actual audio/notification delivery to the chosen channel.
- **`homebrain-companion` owns** communication **intent, memory, reminders, messages, follow-up context**, and **computes the routing decision** (it alone holds the content + `privacy_level` to decide *desired* channel). It expresses the decision declaratively; **HA executes** it.
- **`mass-resolver` remains** the deterministic **media/speaker executor** (ceiling / media zone) and the **sole TTS owner for the media path**.
- The **`ResponseRoutingPolicy` is a shared contract** (a common vocabulary of channels) between companion (decides) and HA (delivers); the resolver continues to own media-zone output.

> **TTS consistency (cf. locked C§4).** The "resolver is sole TTS owner" invariant applies to the **ceiling / media path**. **Satellite voice output is a *new, HA-delivered* path** — the companion never spins up its own TTS; it asks HA to speak on a satellite. This is exactly the "any voice output must go through the established path **or be explicitly designed later**" clause — and the satellite track (6A.8 / Track S) is that explicit later design. No second TTS path is created on the media zone.

### 6A.7 Privacy rules
- **Do not read receipts, private notes, or sensitive reminders aloud by default.** `privacy_level=private` content is never spoken on a shared zone without explicit confirmation.
- **Require confirmation before whole-house announcements.**
- **Support room / person targeting later** (deferred; needs satellite room metadata + targeting UX).
- **Keep multi-user identity a later gated phase** (§11) **unless the satellites already provide reliable user identity** (e.g. per-device or voice ID surfaced by HA) — in which case identity may arrive earlier from satellite metadata, still behind a privacy review.

### 6A.8 Roadmap impact
- **PCL MVP** (now **notes-only** — see §14/§15) is **text-first to the initiating client** — which *needs no routing engine*, so the MVP is unaffected by satellite work.
- **Satellite integration is a required, separate design track ("Track S")** that must land **before real household communication is exposed** on satellites.
- **Do not build satellite routing yet unless specifically approved.**
- **First step (Track S):** **inventory satellite capabilities/entities after they are installed** — entities, room mapping, assist-pipeline binding, per-device TTS reachability (recall the ceiling path depends on the host fetching NAT-IP TTS URLs; satellites may differ), and whether they expose reliable user identity.

---

## 6B. Interaction Audio Policy — deterministic media interruption (⟲ Added 2026-06-29)

**Premise.** When a satellite interaction *starts* in a room where music is playing, the system should **pause or strongly duck that room's media** for the duration of the interaction and the assistant's response — and **not** resume automatically. This is an **input-side / interaction-lifecycle** concern, distinct from `ResponseRoutingPolicy` (which decides *where the answer goes*, an output-side concern). **It is a separate `InteractionAudioPolicy`, never a field of `ResponseRoutingPolicy`.**

**Ownership (boundary).** The `InteractionAudioPolicy` lives in the **deterministic media-interaction layer — `mass-resolver` (executor) + Home Assistant (lifecycle events, room/device metadata) — never in PCL business/memory logic and never in LLM discretion.** PCL **may** supply `InteractionContext` (`source_room`, `source_device`, an interaction phase) but **must not** pause/duck/resume media itself. The resolver already owns volume/pause/resume and is the sole media-TTS owner, so it is the natural owner of the duck/restore mechanics and of the **ephemeral pre-interaction snapshot** (in-memory, per media zone, keyed by interaction id; **not** persisted in the companion's SQLite store and **never** in ChatGPT memory). On resolver restart mid-duck, **fail safe — do not auto-restore from a stale snapshot.**

**Behavior (the locked policy — see Appendix C§8):**
- On `interaction_start` in a room that maps to a *playing* media zone: **snapshot {playback_state, absolute_volume}**, then **duck (lower volume) or pause** — that zone only.
- **Hold** through the interaction and the assistant's response. **No auto-resume by default.**
- **Resume only on an explicit user command** ("resume music", "continue playing", "you can resume"), detected deterministically by the **existing fast local sentence-trigger layer** (it already handles "resume"), or via the resolver `resume` capability when the phrase reaches ChatGPT — either path runs the **same deterministic restore** of the snapshot volume/state and clears the duck flag. Timeout-based auto-resume **MAY** be considered later but **MUST NOT** be the default.
- **Other rooms are never affected.** **Fail safe:** if room↔satellite↔media-zone mapping or current media state is unknown, **do not manipulate media.**

**Concrete constraints (tie-ins to known state):**
- **Use pause or volume-duck, never `media_stop`** — `media_stop` triggers the open stop-wedge / playback-lock (ONBOARDING §6/§8). Note ONBOARDING §11 also warns a long *pause* auto-converts to a locked stop after ~30 s, so **volume-duck is the safer hold for long interactions; reserve pause for short ones.**
- **Reconcile with MA auto-resume.** `script.ceiling_announce` and MA announcements **auto-resume prior playback** (ONBOARDING §5, §6) — which **conflicts** with "no auto-resume." Track S must ensure interaction-ducking does **not** ride the auto-resuming announce path, or must suppress that auto-resume for an interaction hold.

**P0 scope = boundary + hooks only.** P0 defines the policy *name, owner, invariants, and hook points* (interaction-lifecycle signal, room→zone map as Track S data, snapshot-owner rule, explicit-resume routing) and writes **no ducking/pause/resume mechanics and no HA lifecycle wiring**. The full mechanics are **Track S step S2.5** (§15), gated on satellites being installed and inventoried (the room→media-zone map depends on it).

---

## 7. ChatGPT / Tool Integration Model (⟲ Reconciled — bound to the F1-R relay)

**Principle: expose *capabilities*, not *internals*; the LLM orchestrates, deterministic code executes/persists; and every exposed result rides the proven relay.**

### The relay is the contract
Any companion tool exposed to ChatGPT MUST:
1. Be backed by an HA script that calls `rest_command` → `POST /companion` and captures the result in `response_variable`.
2. **Return `{chat_text: …}` via `stop`+`response_variable`** (NOT `set_conversation_response` — F1-R proved the agent ignores it).
3. Rely on the existing one-line agent Instruction ("relay `chat_text` verbatim").
4. Emit a `CommandResult`-shaped payload (so `chat_text`/`spoken_text`/`error` semantics carry over unchanged).
5. **Surface `chat_text` ONLY to the LLM (⟲ Added 2026-06-29).** The HA relay script returns exactly `{chat_text: r.content.chat_text}` — internal `CommandResult` fields (`metadata`, `routing_decision`, `actions[]`, `request_id`, `error.reason`) and any internal routing metadata **must not** be returned to the conversation agent. **Sentinel-probe** each tool before exposure (a value the model would not invent, relayed verbatim) to confirm no internal field leaks.

This means the PCL gets **truthful-by-construction** ChatGPT text for free, the same way music/radio do — no new relay mechanism, no `set_conversation_response`.

### Exposed surface (small, stable — added only when validated)
- `companion_note(text, tags?)`
- `companion_reminder(text, when)`
- `companion_decision(topic, options, chosen?, rationale?)`
- `companion_draft(audience, intent, constraints?)`
- `companion_recall(query, kind?)` — read-only retrieval
- `companion_receipt(meta, image_ref?)` — *later phase*
- (delegation) the existing `home/media` tool stays as-is

Keep the surface tiny — the media side deliberately holds to ~6 tools, "breadth from parameters not tools." The PCL should hold the same line. Each returns a `CommandResult` so the LLM can't fabricate success.

### Kept internal (never exposed to the LLM)
- Raw datastore/SQL/file paths/blob locations; the audit log; secrets/tokens; the resolver's internal endpoints; retention/deletion machinery (offered as the *capability* `companion_forget(id)`, mechanism internal); cross-user joins.

### Deterministic-vs-LLM split (see §10)
- **LLM:** intent understanding, drafting prose, summarizing options, choosing the tool, phrasing.
- **Deterministic code:** parsing `when` → absolute timestamp (with confirmation), writing/reading the store, schema enforcement, IDs, **truthful `CommandResult` construction**, retention/deletion, redaction, **referent resolution** ("the second one").

---

## 8. Context and Memory Model

Two tiers. Conflating them is the classic mistake.

### 8.1 Short-term conversation context (working memory) (⟲ Reconciled — anchored to live metadata)

Scope: a single conversation/session; seconds–minutes; ephemeral.

The canonical flows and how current-state primitives serve them:
- "find jazz stations" → **"play the second one."** The resolver's `find` already returns `metadata.stations[]` + `count`. The companion (or a thin context layer) **caches the last `stations[]`** and resolves "the second one" → `stations[1]` → calls resolver `/command` with that concrete target. **Deterministic index resolution in code, not LLM guesswork.** The reserved `CommandResult.actions[]` field is the natural place to *advertise* such follow-ups ("say 'play the first one'").
- "help me compare camping options" → **"save that decision."** The companion holds the produced comparison in `last_options`/`last_draft`; "save that decision" snapshots it into a durable Decision record.
- "remind me about **this** tomorrow." "this" binds to `current_topic`.

**Design:**
- A **session object** keyed by conversation id (+ room), holding a bounded recent buffer and **typed referent slots**: `last_list` (e.g. the `stations[]`), `last_options`, `last_draft`, `current_topic`.
- **TTL + size cap;** short-term is *not* promoted to long-term without an explicit save.
- **Referent resolution:** deterministic when structured (numbered list → index); LLM only for fuzzy referents ("the cheaper campsite one"). Deterministic resolution is also what keeps "play the second one" *truthful* — the exact failure mode F1-R fought.

> Open dependency: whether the OpenAI Conversation / Assist path exposes a stable conversation id + room/user to key sessions on (see §14 Q1). If not, fall back to room-scoped or single-shared context for the MVP.

### 8.2 Long-term memory (durable knowledge)

Record types: **Notes** (text + tags + ts), **Decisions** (topic/options/chosen/rationale/ts), **Receipts** (structured meta + optional blob ref — *later*), **Reminders** (text + `due_at` + status), **Family/home logistics** (multi-user gated), **Preferences** (opt-in; profiling-sensitive).

- **Promotion path:** short-term → long-term **only on an explicit, auditable action** ("save that decision", "take a note"). **No silent auto-memorization** early.
- **Recall:** `companion_recall(query, kind?)` — start with structured/tag/keyword + recency. **Defer semantic/vector search** until data volume and need justify the dependency and eval burden.
- Every record carries an optional **`owner`** field from day one (forward-compat for multi-user; §11) even while the MVP is single-shared.

---

## 9. Timers / Reminders Model (⟲ Reconciled — firing paths made concrete)

Split the two concerns:

1. **Intent + content + schedule** (companion-owned): the durable reminder record with a concrete `due_at`.
2. **Firing + delivery** (HA-owned, **channel chosen by `ResponseRoutingPolicy`** — §6A.5): at `due_at`, deliver via the policy-selected channel(s) — **mobile push**, **source/target satellite announce**, **ceiling-announce**, or **silent + dashboard** — never a fixed default. **Privacy gate (§6A.7):** a `privacy_level=private` reminder is **not spoken on a shared zone by default** (text/push or confirm-first). The companion must not speak directly (single-TTS-owner discipline for the media path, §6/§6A.6).

**Time parsing** is deterministic-with-LLM-assist: the LLM proposes structured time; **code normalizes to an absolute timestamp** in the home timezone and **echoes it for confirmation** ("Okay — tomorrow, Mon Jun 29, 9:00 AM?"). Confirming the *resolved* time prevents "set it for next year."

**Ephemeral vs durable:** a kitchen "in 20 minutes" timer is a different thing from a durable reminder — it can be an **HA-native timer**, fire-and-forget, arguably **out of PCL scope**. The PCL owns *durable* reminders (survive restart, queryable, editable). Note **Inc 4 already lists a "sleep timer"** on the media roadmap — coordinate so timers don't get built twice (§13).

**MVP stance:** durable reminders stored in SQLite; firing via the simplest reliable path (even a poll + push/announce) before wiring HA automations.

---

## 10. Receipts / Notes Model

### Notes (MVP-eligible)
`{id, text, tags[], created_at, owner?}`. Create / recall (tag/keyword/recency) / forget. Pure text → trivially SQLite, no blobs. **Good first feature.**

### Decisions (MVP-eligible, light)
`{id, topic, options[], chosen?, rationale?, created_at, owner?}`. "save that decision" snapshots `last_options`/`last_draft`. Recall: "what did we decide about camping?"

### Receipts (explicitly *later phase* — highest privacy weight)
Two parts: **structured meta** (vendor, amount, date, category) and an **optional image blob**. Image handling raises storage size, OCR (dependency + accuracy), and **financial PII** — the single highest-sensitivity data type here.
- **Recommendation:** defer until notes/reminders are proven. Build **structured meta first (no image)**, then image blobs behind explicit local-only storage + retention + audit. OCR last.
- **Blob shape:** blobs on the local filesystem in a restricted-perms dir; only a *reference* in SQLite. Never put blobs in DB rows; never send blobs to the LLM.

---

## 11. Security / Privacy Model (⟲ Reconciled — concrete patterns adopted)

The PCL holds the most sensitive data in HomeBrain. Security is a first-class driver.

### Data classification

| Data | Sensitivity | Default handling |
|---|---|---|
| Notes | Medium | Local-only, retain until forgotten |
| Decisions | Medium | Local-only |
| Reminders | Low–Medium | Local-only |
| Receipts (meta) | High (financial) | Local-only, retention policy |
| Receipt images | **Highest** (financial PII) | Local-only, restricted dir, retention, *later* |
| Family logistics | High (others' data) | Local-only, multi-user gated |
| Preferences | Medium (profiling) | Opt-in, inspectable |
| Audit log | High (reveals all activity) | Internal-only, never exposed to LLM |

### Principles (reusing existing HomeBrain conventions)
1. **Local-first by default.** All personal data on the home host (SQLite + local blob dir). **No cloud (Drive/Sheets/external DB) early** — cloud is an explicit, opt-in, later decision with its own threat model.
2. **The LLM is a processor, not a store.** Send only the current turn + minimal context — never the whole memory, never receipt images, audit logs, secrets, or other users' data. Anything sent to OpenAI leaves the house.
3. **Secrets stay in `0600` files** (the established pattern: `.http_secret`/`.ha_token`/`.ma_token`). The companion gets its **own** shared-secret for `/companion` and **reuses the resolver's `X-Resolver-Key` pattern** for its outbound `/command` calls. **Never echo/commit/log secrets; secret-scan before commits** (carried rule).
4. **Audit log** on every personal-data write/read/delete (who/what/when). Internal-only.
5. **Deletion + retention are features:** `companion_forget(id)` and category retention (e.g. receipts auto-expire after N months unless pinned). Deletion really deletes (incl. blobs).
6. **Redaction at the boundary** when recall feeds the LLM for phrasing (don't pass full card numbers to draft a summary).
7. **Authn between services:** `/companion` LAN-bound + shared-secret, same as `/command`. Don't expose it unauthenticated even on the LAN.
8. **Multi-user is a security boundary, not just a feature** (below).
9. **Aloud-output is privacy-gated (⟲ §6A.7).** Receipts, private notes, and sensitive reminders are **not spoken on shared zones (ceiling/satellites) by default**; whole-house announcements **require confirmation**. `privacy_level` on the `InteractionContext` (§6A.4) governs this, enforced by the `ResponseRoutingPolicy` (§6A.5).
10. **The companion is the sole system of record for PCL memory; ChatGPT-native memory/personalization is NOT used for PCL state (⟲ Added 2026-06-29).** Keep any OpenAI-side conversation memory off/ignored for PCL data — relying on it would split the source of truth, evade the audit log, and push personal data outside the house. Only the current turn + minimal context is ever sent to OpenAI (cf. principle 2). The durable store (§8.2) is authoritative; recall comes from it, never from the LLM's own memory.

### Family / multi-user (⟲ Reconciled)
- Early phases: **single shared context** (whoever talks to the home). Simplest; means *all* stored data is household-visible — state this explicitly to users.
- Real multi-user needs: identity from HA (who/which device — note HA's exposure model is shared across conversation agents), per-user partitioning, and an explicit sharing model for family logistics. Real failure modes (leaking one person's notes to another).
- **Recommendation:** ship single-shared first; carry the optional `owner` field from day one so multi-user is a migration, not a rewrite; build true multi-user as a dedicated later phase with its own privacy review.

---

## 12. Storage Decision

Applying the database-selection workflow to this profile (tiny volume; light relationships; single-writer; simple evolving schema; blobs → filesystem):

| Option | Verdict |
|---|---|
| **SQLite (+ local blob dir)** | ✅ **Recommended.** Zero-ops, file-based, transactional, perfect at home scale, trivially local-only, copy-to-back-up, easy to inspect. A **container with modern Python** gets current SQLite features (vs the host's Python 3.5.2). |
| Local JSON files | ⚠️ Prototype-only; no query/transaction story. |
| HA helpers/entities | ❌ Wrong tool for documents/memory (§4 C). |
| Google Drive / Sheets | ❌ Cloud egress of sensitive data; sync conflicts; auth complexity. Not now. |
| Postgres / server DB | ❌ Over-engineered for home scale. |
| Vector DB | ❌ Premature; SQLite (+ an embedding column later) likely suffices if semantic recall is ever justified. |

**Decision:** SQLite as system of record; filesystem for blobs; periodic local file backup. Backup target must itself be "local-only" (§14 Q5 — a NAS likely exists per the local-music NFS work). Reconsider only if true multi-device sync becomes a hard requirement or volume genuinely outgrows SQLite (both unlikely at home scale).

---

## 13. Contract Decision — reuse `CommandResult`, layer `AssistantResult` internally (⟲ Reconciled — reversed from first draft)

**First draft said:** "separate `AssistantResult`, don't overload `CommandResult`." **Reading F1-R reverses the wire decision:** the ChatGPT relay *is* `CommandResult.chat_text`. Forking the wire contract would mean re-solving the relay — which was hard-won. So:

- **At the ChatGPT edge: emit `CommandResult`** (`ok/intent/request_id/spoken_text/chat_text/error/metadata/actions[]`). `chat_text` always present; `spoken_text` null on success (silent); errors use the enumerated codes. The F1-R `stop`+`response_variable` relay carries it. **Zero new relay work.**
- **Internally: keep a richer `AssistantResult`** for conversation/memory (referents, session linkage, recall payloads, draft variants, confirmation prompts). It **projects down** to a `CommandResult`-compatible payload at the edge.
- **Reuse the lifecycle:** PCL capabilities implement the same `resolve → validate → execute → handle() → CommandResult` shape. A `note` capability: `validate` (writable? input sane?) → `execute` (write) → `CommandResult(ok, chat_text="Saved your note.")`. This makes the PCL **honest-by-construction**, the same property F1 gave the resolver.
- **Use `actions[]`** to surface follow-ups ("say 'play the first one'", "say 'remind me tomorrow'") — the field already exists for exactly this.

**Delegation flow ("play the second one"):**
1. Companion holds `last_list` (the `find` result's `stations[]`) in short-term context.
2. "play the second one" → deterministic `last_list[1]` → its concrete target.
3. Companion calls resolver `/command` (music/radio intent) → gets a `CommandResult`.
4. Companion returns that `CommandResult` (or wraps it) so ChatGPT relays the resolver's truthful `chat_text`. Resolver stays pure and the sole TTS owner; the companion adds no TTS.

> Net (⟲ Reconciled): one wire contract (`CommandResult`), one relay (F1-R), one TTS owner (resolver). The PCL's "extra" is an *internal* model and its *own data*, not a parallel public contract.

---

## 13A. Formal Request/Response Contract (⟲ Added 2026-06-28)

Model the PCL boundary like an **LLM / tool-call API**. Just as an LLM request carries *messages + tools + metadata + session + client constraints*, the PCL **`AssistantRequest`** carries *home-aware* context: who, where, what device, how private. **Design principle: the client does not decide the final output route** — it supplies **context + capabilities + hints**; the deterministic `ResponseRoutingPolicy` (§6A.5) decides where output goes.

### `AssistantRequest` — request envelope
```jsonc
{
  "request_id": "uuid",
  "client": {
    "client_type": "mobile|web|satellite|ha_assist|dashboard|automation|mcp",
    "client_id": "kitchen-sat-01",
    "source_device": "...",
    "source_room": "kitchen",
    "capabilities": ["voice_input","voice_output","screen","notification","camera","file_upload"]
  },
  "actor": {
    "user_id": "constantin | null",
    "user_confidence": 0.0,           // identity certainty (0..1); gates privacy, fail-safe low
    "household_role": "adult | child | guest | null"   // later phase
  },
  "conversation": {
    "conversation_id": "uuid",
    "turn_id": "uuid",
    "previous_request_id": "uuid | null",
    "referents_available": ["last_list","last_options","last_draft","current_topic"]
  },
  "input": {
    "mode": "text|voice|image|file|event",
    "text": "play the second one",
    "attachments": []                 // references only; blobs NEVER inlined to the LLM
  },
  "intent": {                          // optional; filled by client, HA, or the LLM
    "name": "note|reminder|decide|recall|draft|media|...",
    "params": { },
    "confidence": 0.0
  },
  "routing_hints": {                   // HINTS ONLY — the policy decides, not the client
    "reply_mode": "text|voice|both|silent",
    "privacy_level": "public|household|private",
    "target_device": "... | null",
    "target_room": "... | null",
    "target_person": "... | null"
  },
  "safety": {
    "requires_confirmation": false,
    "allowed_side_effects": ["write_note","set_reminder","play_media","announce"]
  }
}
```
- **`routing_hints` are hints, not directives.** A satellite may *prefer* voice but cannot *force* private content onto a shared zone — the policy can override every hint.
- **`actor.user_confidence` + `privacy_level` drive the fail-safe** (§18.4.2): low confidence / unknown privacy → least-disclosive route (text-to-source, silent aloud).
- **`safety.allowed_side_effects`** bounds what the request may do — the companion **refuses** side effects not in the list (capability scoping; matters most for `mcp` / `automation` clients).
- **`intent` is optional:** deterministic clients pre-fill it; otherwise the LLM resolves intent from `input.text`.

### Response — `CommandResult` at the external boundary (locked C§3)
```jsonc
{
  "ok": true,
  "request_id": "uuid",
  "chat_text": "Playing the second station, Classic Vinyl HD.",  // always present; relayed via F1-R
  "spoken_text": null,                  // optional; null = silent
  "error": null,                         // | { "code", "reason" }
  "metadata": { },                       // capability-specific (stations[], note_id, ...)
  "routing_decision": {                  // policy output — auditable; HA delivers it
    "channels": ["text_source"],         // e.g. ["satellite_voice","phone_notification"]
    "spoke_aloud": false,
    "confirmation_required": false,
    "reason": "private content -> source text only"
  },
  "actions": []                          // suggested follow-ups ("say 'play the first one'")
}
```
- The external response **stays `CommandResult`** — `routing_decision` is an **extension field inside it**, not a second contract (holds C§3 / "no second external relay"). ChatGPT still consumes `chat_text` verbatim via F1-R; `routing_decision` is for **HA delivery + the audit log**.
- `routing_decision.channels` is the **abstract channel intent**; HA's output adapters resolve it to concrete entities and deliver (the §18.2(2) seam, made concrete).

### Why model it like an LLM API
| LLM API request | PCL `AssistantRequest` |
|---|---|
| `messages` / `input` | `input` (+ `conversation` history & referents) |
| `tools` | `intent` + `safety.allowed_side_effects` (what may be invoked) |
| `metadata` / `session` | `request_id` / `conversation_id` / `turn_id` / `previous_request_id` |
| client modality constraints | `client.capabilities` + `routing_hints` |
| system / policy | `ResponseRoutingPolicy` — **server-side, never the client** |

Same discipline: a **structured envelope** carries everything the server needs to decide; the **client states constraints but not the decision**; the **response is one typed result**. The home-aware twist is that **"where the answer goes" is a first-class server decision**, not an implicit per-client default.

---

## 14. MVP Proposal

**Goal:** prove the sibling-service shape + truthful memory at lowest privacy/operational risk, reusing the resolver's contracts and the F1-R relay.

**Hard dependency (⟲ Reconciled; locked — see Appendix C §6) — GATES MET (2026-06-29):** the two prerequisite gates are now **satisfied** — **(a) F1-R is closed/accepted complete** and **(b) the Speaker WebSocket reconnect bug is fixed and deployed** (CHANGELOG 2026-06-28/29) — and the **F1-R relay is landed** (all three media scripts relay `chat_text`). **PCL P0 is therefore unblocked.** It can now be validated **over HTTP only** (like F1 validated `/command` before scripts) and exposed to ChatGPT *after* the HTTP path is validated and the new tool is sentinel-probed (carried "don't expose until validated" rule).

**In scope (MVP — notes only):**
- New containerized `homebrain-companion` sibling; `POST /companion` (LAN + shared secret); SQLite store; modern Python.
- **Notes:** create / recall (tag/keyword/recency) / forget. `owner` field carried from day one (forward-compat; single-shared for now).
- **`CommandResult`-shaped results** (honest-by-construction) + the F1-R relay (`chat_text` only) for the single notes tool, exposed **only after** HTTP validation + a sentinel-probe.
- **Audit log** + `forget` from day one.
- Read-back via the existing ChatGPT-text path (no new TTS; no HA script changes).

> **Deferred out of P0 (re-sequenced 2026-06-29):** durable **reminders → P1** (they pull in time-parsing + HA firing/delivery); light **decisions + short-term referents → P2** (they depend on a stable conversation id — Q1 — and on intercepting the resolver find-flow). Stripping P0 to notes proves the novel risk — a stateful, private, durable, *truthful*, deletable, audited store — with zero external dependencies.

**Explicitly out of MVP:** durable reminders (→P1); light decisions + short-term referents (→P2); **media-interruption mechanics — P0 defines only the boundary/hooks (§6B); Track S builds the mechanics**; receipts (esp. images) / OCR; cloud storage; multi-user/per-person privacy (single-shared only; `owner` field present for later); semantic/vector recall; auto-learned preferences/silent memory; new HA automations/YAML; message *sending* (draft-only); any change to `script.play_music`/`play_radio`/`find_stations`/`media_status` or the resolver.

**Definition of done (notes-only):** "take a note…" and "what notes about Y" work end-to-end, "forget that note" really deletes, and **every confirmation ChatGPT relays is *true*** (verified against the store via `CommandResult`), with an audit trail. Validated over HTTP first; the single notes tool is exposed only after a sentinel-probe shows `chat_text`-only relay. No second TTS path; resolver remains sole TTS owner. (Reminders/decisions/referents have their own DoD in P1/P2.)

---

## 15. Phased Roadmap (⟲ Reconciled — slotted against the live Inc/F1 roadmap)

This is a **separate track ("Track P")** from the media increments. It must not block or entangle Inc 2–4. It *depends on* F1-R for ChatGPT exposure.

| Phase | Theme | Adds | Gate to enter |
|---|---|---|---|
| **P0** | Foundation (MVP) | Containerized companion, SQLite, **notes only (create/recall/forget)**, `owner` field, `CommandResult` projection, audit; HTTP-validated then **one notes tool** exposed via F1-R relay after sentinel-probe | This doc approved; **prerequisite gates already met** (F1-R closed + Speaker reconnect fixed/deployed, F1-R relay landed — CHANGELOG 2026-06-28/29); host confirmed able to run the service; resolver/HA untouched |
| **P1** | Durable reminders + HA delivery | Durable reminder records (confirmed absolute time, list/complete); firing via HA timer/automation + push + ceiling-announce (privacy-gated) | P0 stable; "don't change HA" lifted deliberately; conversation-id (Q1) + firing-path (Q2) resolved |
| **P2** | Decisions + referents + drafting | Light decisions (record/recall, "save that decision"); short-term referents ("play the second one") via deterministic resolution; message drafting (human sends); richer recall | Reminders trusted in daily use; conversation-id confirmed stable |
| **P3** | Receipts (structured) | Receipt *meta* (no image), categories, retention policy | Retention/audit/delete proven on notes |
| **P4** | Receipts (images) + OCR | Local blob storage, restricted dir, optional OCR | P3 stable; explicit privacy review |
| **P5** | Multi-user / family | Identity from HA, per-user partitioning, explicit family sharing | Dedicated privacy/security review passed |
| **P6** | Smart memory (opt-in) | Auto-learned prefs, semantic recall — opt-in + inspectable | Strong evidence of need; volume justifies |

**Track S — Satellite / whole-house communication (parallel design track; §6A).** A *separate* track from P0–P6, required **before** real household communication is exposed on satellites. Sequence: **S0** inventory satellite entities/rooms/pipelines/TTS-reachability/identity (after install) → **S1** `InteractionContext` capture → **S2** deterministic `ResponseRoutingPolicy` (text-to-source default) → **S2.5** deterministic **`InteractionAudioPolicy`** (media interruption: duck/pause same-room media on interaction start, hold through response, **no auto-resume**, explicit-resume only, preserve prior volume/state, other rooms untouched, fail-safe on unknown mapping; pause/duck never `media_stop`; reconcile MA auto-resume — §6B / C§8) → **S3** privacy gating + confirmation flows → **S4** household announcements + room/person targeting. **Do not build satellite routing until specifically approved.** P0–P2 do **not** depend on Track S (the MVP is text-first to the source client — a degenerate routing case).

Coordination notes: **Inc 4** (media) introduces a *sleep timer* and "household" features — align timers/reminders ownership so they're not built twice (§9, Appendix C§5). Keep PCL tool descriptions and `assistant-capabilities.md` in lockstep when anything is exposed (the media side already treats that doc + the OpenAI Instructions as the source of truth for what ChatGPT may claim).

Each phase is independently shippable and abandonable. Never start a phase before its gate.

---

## 16. Open Questions

1. **Conversation id / context source:** does OpenAI Conversation / Assist expose a stable conversation id + room/user to key short-term sessions on? (If not → room-scoped or single-shared for MVP.)
2. **Reminder firing reliability:** simplest acceptable firing = poll + push/announce, or HA automation from P1? (Determines whether P0 touches HA at all — preferably not.)
3. **One companion tool vs several:** a single `companion` tool with an action arg, or several narrow tools? (Prompt clarity vs sprawl; the media side's ~6-tool discipline argues for few.)
4. **Outbound auth:** reuse the resolver's `X-Resolver-Key` pattern for companion→`/command`? (Likely yes.)
5. **Backup target** that is still "local-only": the NAS implied by the local-music NFS work? the host itself?
6. **Where it runs:** container on the homebrain host (alongside the resolver) vs the HAOS VM vs elsewhere. (Container-on-host leans simplest and keeps it on the LAN the resolver already serves; confirm host can run a modern-Python container on Ubuntu 16.04 — Docker yes.)
7. **Timezone/locale source** for time normalization — from HA config?
8. **Inc 4 overlap:** who owns "timer"/"sleep timer"/household — resolver (Inc 4) or companion? Decide before either builds it.

---

## 17. Risks and Non-Goals

### Risks
- **Truthfulness regression in a new surface.** The F1/F1-R lesson applies *doubly* to memory ("I saved that" when it didn't; "you decided X" when you didn't). Mitigation: reuse `validate`-before-`execute`; emit truthful `CommandResult`; deterministic referent resolution; confirm resolved times.
- **Relay drift.** If a PCL tool uses `set_conversation_response` (the obvious-but-wrong path), ChatGPT silently fabricates replies. Mitigation: mandate the F1-R `stop`+`response_variable` relay for *every* exposed tool; sentinel-probe each before exposure.
- **Double-TTS / breaking the single-owner invariant.** A parallel TTS call from the PCL would double-speak or speak when the system should be silent. Mitigation: PCL emits text only; proactive speech routes through the one ceiling-announce primitive.
- **Privacy/data leakage.** Most sensitive data in HomeBrain, talking to an external LLM. Mitigation: minimize LLM payloads, redact, local-only storage, audit, never send receipt images.
- **Scope creep / data-model lock-in.** Mitigation: phased gates; `owner` field as the only forward-compat concession.
- **Silent memory creep.** Auto-learning erodes trust if invisible. Mitigation: explicit-save only until P6, then opt-in + inspectable.
- **Coupling temptation.** Pressure to "just add modules to the resolver." Mitigation: §4 verdict — reuse patterns, not the process/store/perimeter; and the Python 3.5 host makes in-resolver a poor data home anyway.
- **Roadmap entanglement.** PCL work must not stall Inc 2–4. Mitigation: separate Track P; PCL depends on F1-R but the media increments don't depend on PCL.

### Rollback (PCL phases) (⟲ Added 2026-06-29)
PCL work is additive and reversible at every phase; each phase reverts independently without touching the others.
- **P0 (notes store, not exposed):** stop/remove the container — the LAN port closes, nothing was exposed to ChatGPT, and no HA/resolver change was made, so blast radius is zero. Data is a single SQLite file: keep timestamped copies; a bad schema migration rolls back by restoring the previous DB-file copy (deletion of any blob is real).
- **P0 exposure sub-gate (one notes tool):** un-expose the companion tool (the established `homeassistant/expose_entity` un-expose pattern) and restore the HA relay script from its backup — this reverts the surface while the companion keeps running internally. Exposure rollback is independent of data rollback.
- **P1+ (HA delivery wiring):** per-automation/script backups, same discipline as F1-R's `*.preF1R.json`; the reminder-firing automation can be disabled without touching the companion.
- **Invariant:** resolver and HA stay untouched until a gate is deliberately lifted, so every phase has a clean, independent revert.

### Non-goals (now)
- Replacing or modifying `mass-resolver`, its TTS ownership, or `script.play_music`/`play_radio`/`find_stations`.
- Changing Home Assistant (until P1, deliberately).
- A general-purpose chatbot / open web assistant.
- Cloud sync, multi-device, or off-home access.
- Sending messages on the user's behalf (draft-only).
- Being the source of truth inside the LLM's context.

### "Do not build yet" list (tempting but premature)
- ❌ **Vector/semantic memory & embeddings** — SQLite filters suffice early.
- ❌ **Receipt OCR** — high effort/accuracy burden; P4 at earliest.
- ❌ **Google Drive / Sheets / cloud DB** — sensitive-data egress; not before an explicit threat model.
- ❌ **Auto-learned preferences / silent memory** — trust/privacy hazard; opt-in only, much later.
- ❌ **Multi-user privacy partitioning** — a real security boundary; dedicated phase.
- ❌ **Message *sending* integrations** — draft first; sending is a separate trust decision.
- ❌ **Proactive/agentic behavior** (companion initiating actions unprompted) — out until everything reactive is trusted.
- ❌ **A second TTS path** — never; one TTS owner (resolver) is an invariant.
- ❌ **Custom HA `llm.Tool` integration for the PCL** — only if the F1-R script relay proves insufficient for companion tools (it didn't for music); needs HA restart + tool-surface sign-off (cf. F1-R Option D).
- ❌ **A standalone UI/app** — read-back via existing voice/text first; build UI only if recall genuinely needs it.

---

## 18. Final Analysis & Design Conclusion (designer's synthesis)

This section is my own conclusion as the architect — taking the accepted decisions and the satellite input and resolving the remaining tensions into a single, buildable design. Where the inputs left a choice open, I make the call here.

### 18.1 The one idea the whole design reduces to
HomeBrain has **three concerns that were historically collapsed into one path** ("mic → resolver → ceiling"): *deterministic action*, *personal cognition/memory*, and *output delivery*. Every decision in this document is an instance of **pulling those three apart and giving each a single owner**:
- **Action** → `mass-resolver` (deterministic, truthful, sole media-TTS owner).
- **Cognition + memory** → `homebrain-companion` (stateful, private, the system of record).
- **Delivery** → Home Assistant (entities, rooms, pipelines, notifications) — driven by a **policy**, not a default.

If a future change blurs two of these again, it is wrong. That is the design's load-bearing invariant.

### 18.2 Tensions I'm resolving, and the calls
1. **Who decides routing — companion, HA, or the LLM?** **Conclusion: the companion decides; HA delivers; the LLM never decides.** Routing is a **pure, deterministic function** `route(InteractionContext, content_class, privacy_level) → [channel]`. It must be testable and predictable — the LLM may *phrase* a reply but must never choose *where private content is spoken*. This is the single most important refinement I'm asserting on top of the input: **routing and privacy gating are deterministic code, in the same bucket as truthfulness and persistence (§10).**
2. **Companion needs topology it doesn't own.** Routing needs room/device maps that live in HA. **Conclusion:** the companion emits an **abstract channel intent** (e.g. `reply_source_text`, `announce_household_voice`, `notify_phone`, `silent`), and **HA resolves intent → concrete entities** and delivers. The companion never hard-codes entity IDs; HA never makes privacy decisions. Clean seam, and it survives new devices.
3. **Does the satellite premise threaten the MVP?** **Conclusion: no — it simplifies it.** The MVP's default ("reply to the source client, text-first") is the **degenerate case** of `ResponseRoutingPolicy`. So the MVP needs *no routing engine at all*; the full policy is Track S. The satellite correction therefore **de-risks** the MVP rather than expanding it.
4. **TTS-owner invariant vs. satellite voice.** **Conclusion:** the invariant is scoped to the **media zone** (resolver-owned). Satellite speech is a **distinct, HA-delivered** path the companion *requests* but never *implements* — consistent with C§4's "explicitly designed later." No contradiction.
5. **Identity timing.** **Conclusion:** keep multi-user gated, but allow identity to arrive *earlier* **iff** satellites surface it reliably — and pair it with a **fail-safe**: when identity or `privacy_level` is unknown, route to the **least-disclosive** channel (text to source; never speak aloud). Privacy defaults conservative; capability earns disclosure.
6. **Contract proliferation.** **Conclusion:** hold the line — **one external contract (`CommandResult`), one relay (F1-R)**. Internal models (`AssistantResult`/`NoteResult`/`ReminderResult`) are an implementation convenience that project to `chat_text`. Confirmation prompts and routing intents travel as ordinary `CommandResult` content/`actions[]`, not as a new wire type.

### 18.3 The concluded architecture (one sentence each)
- **`mass-resolver`** — unchanged deterministic media/speaker executor; sole media-TTS owner; `resolve→validate→execute→CommandResult`.
- **`homebrain-companion`** — containerized sibling (modern Python), owns conversation/short-term context/long-term memory/personal data, reuses the resolver's lifecycle + `CommandResult` + F1-R relay, computes routing intent, calls `/command` for device actions.
- **Home Assistant** — I/O, automation, timers/entities, notifications, **satellite entities + room/device metadata**, and **delivery executor** for routing intents.
- **Contracts** — `CommandResult` at every external edge; the **F1-R hard return** for every ChatGPT-exposed tool; `InteractionContext` + a deterministic `ResponseRoutingPolicy` as the routing seam.
- **Data** — local-first SQLite (+ filesystem blobs), audited, deletable, single-owner; nothing to the cloud.

### 18.4 The invariants (the things that must never break)
1. One external contract (`CommandResult`), one relay (F1-R), one media-TTS owner (resolver).
2. **Output destination is always a policy decision; never hard-coded.** When uncertain, fail safe to least-disclosive (text-to-source, silent aloud).
3. **Deterministic code owns** truthfulness, persistence, referent resolution, **routing, and privacy gating.** The **LLM owns language only.**
4. Personal data is local-first, audited, deletable, and single-owned by the companion.
5. Additive/reversible; **nothing exposed to ChatGPT until validated**; no second TTS path on the media zone; resolver/HA untouched until a gate is deliberately lifted.

### 18.5 Recommended build sequence (the actual path)
1. **Gate (not PCL work) — MET (2026-06-29):** F1-R music stable **and** Speaker reconnect bug fixed (CHANGELOG 2026-06-28/29).
2. **P0 — Companion MVP (notes only):** containerized service + SQLite; **notes (create/recall/forget)** + `owner` field; `CommandResult` projection; **degenerate routing (text-to-source)**; audit + delete. Validate **over HTTP first**, then expose **one notes tool** to ChatGPT via the F1-R relay (sentinel-probe it), keeping `assistant-capabilities.md` in lockstep. **Reminders → P1; decisions/referents → P2.**
3. **P1:** durable reminders + HA delivery wiring (push/announce, privacy-gated firing). **P2:** light decisions + short-term referents ("save that decision", "play the second one"); drafting (human sends); richer recall.
4. **Track S (only when approved):** S0 inventory satellites → S1 `InteractionContext` → S2 deterministic `ResponseRoutingPolicy` → **S2.5 deterministic `InteractionAudioPolicy` (media interruption; §6B / C§8)** → S3 privacy gating + confirmation → S4 household announcements + targeting.
5. **Later gated:** receipts (meta → image → OCR), multi-user, semantic memory, cloud.

### 18.6 Conclusion
The design is **sound and buildable as specified**, and the satellite correction strengthens rather than complicates it — because the right abstraction (`InteractionContext` + a deterministic `ResponseRoutingPolicy`, with the companion deciding and HA delivering) makes "everything to the ceiling" just one configurable policy, and makes the MVP a trivial special case of it. The critical discipline to hold during implementation is **#18.4.3 — keep routing and privacy in deterministic code, never the LLM.** With that held, the system can grow from "notes and reminders, text-first" all the way to "whole-house, multi-room, identity-aware household communication" **without re-architecting** — only by enriching the policy and lifting gates in order. The pattern analysis (§4A) confirms the composite (hub-and-spoke + adapters + deterministic policy + HA event-bus + private context store) beats every simpler alternative on the criteria that matter, and the formal envelope (§13A) gives it an LLM-API-shaped boundary where the client states constraints but the server decides routing. **Recommendation: approve the design; begin Track P at P0 once the two gates pass; keep Track S in design until satellites are installed and inventoried.**

---

## Appendix A — Naming decision (CONFIRMED — see Appendix C §1)

"Assistant" is overloaded (media voice tools). **Confirmed:** service name = **`homebrain-companion`**; concept name = **Personal / Communication Layer (PCL)**. Do **not** call the new layer just "assistant" — it collides with the existing media assistant/tooling terminology. (Rejected alternates: `homebrain-concierge`, `homebrain-pa`.)

## Appendix C — Accepted decisions (LOCKED, 2026-06-28)

These were reviewed and accepted by the user. They are binding for the PCL track; supersede any looser wording earlier in this document. Changing one requires an explicit decision update here.

### C§1 — Naming
- Service name: **`homebrain-companion`**.
- Concept name: **Personal / Communication Layer** ("**PCL**").
- **Avoid bare "assistant"** for this layer — it collides with the existing media assistant / tooling terminology (`assistant-tooling-design.md`, `assistant-capabilities.md`).

### C§2 — Architecture
- **`homebrain-companion`** is a **separate, containerized sibling service**.
- **`mass-resolver`** remains the **deterministic home/media command executor** (unchanged).
- **Home Assistant** remains the **I/O, automation, timer/entity, and notification platform**.
- **ChatGPT-facing tools must return via the proven F1-R hard-return mechanism** (script returns `{chat_text}` via `stop`+`response_variable` + the verbatim agent instruction). **Never `set_conversation_response`.**

### C§3 — Contract
- **`CommandResult` is the contract at the external / wire / ChatGPT boundary.**
- The PCL **may** use internal domain models (e.g. **`AssistantResult`**, **`NoteResult`**, **`ReminderResult`**), but for any exposed tool these **project into `CommandResult.chat_text`** (and the rest of the `CommandResult` shape).
- **Do not introduce a second external relay contract** unless there is a proven need.

### C§4 — TTS
- The PCL **must not create a second TTS path** on the **media zone**.
- The **resolver remains the TTS owner** for the media/ceiling path.
- The PCL **returns text**; any voice output must go through the **established path** (single owner) or be **explicitly designed later**.
- **Satellite voice output is HA-delivered** (the companion asks HA to speak on a satellite; it never runs its own TTS) and is the "explicitly designed later" path — see C§7 / §6A.6.

### C§5 — Timers / reminders ownership
- **Media sleep timer → resolver / media roadmap** (Inc 4).
- **Personal reminders / timers → `homebrain-companion`.**
- **Home Assistant executes** timers, notifications, and entity actions.
- **`homebrain-companion` owns** interpretation, context, **durable reminder records**, and follow-up state.

### C§6 — Roadmap
- PCL stays **Track P** (separate from media Inc 2–4; must not entangle them).
- **Prerequisite gates (a) F1-R music stable and (b) Speaker reconnect bug fixed are MET (2026-06-29; CHANGELOG 2026-06-28/29) — PCL P0 is unblocked.**
- First implementation is a **notes-only MVP** (create / recall / forget), validated over HTTP and exposed to ChatGPT only after a sentinel-probe. **Durable reminders move to P1; light decisions + short-term referents move to P2.** *(Narrowed 2026-06-29 — explicit decision update per this appendix's amendment rule.)*
- **Receipts / images, semantic memory, multi-user, and cloud sync remain later gated phases.**

### C§7 — Satellite / whole-house communication & routing (⟲ Added 2026-06-28)
- Satellites are **general household communication endpoints**, not just media mics.
- **Output destination is always a policy decision — never hard-coded.** Specifically: **do not** wire "satellite input always replies on the ceiling speakers." Use the **`ResponseRoutingPolicy`** (§6A.5).
- **`InteractionContext`** (§6A.4: `client_type`, `source_device`, `source_room`, `user`, `reply_mode`, `privacy_level`, `target_device`, `target_room`, `target_person`, `conversation_id`) is captured per interaction and drives routing.
- **Routing is deterministic local code, never the LLM** (the LLM must not decide where private content is spoken).
- **Default routing:** mobile/web → that client, text-first; satellite → house voice route only when non-private/household/media; media → ceiling/media zone; private notes/receipts/reminders/personal answers → text to source or confirm-before-speaking; household announcements → selected satellites/whole-house **after confirmation**; timers/reminders → confirm to source, later notify/speak per policy.
- **Fail-safe:** when `privacy_level` or `user` is unknown, default to the **least-disclosive** channel (text to source; do not speak aloud).
- **Ownership:** HA owns satellite entities/routing primitives/pipelines/room-device metadata **and delivery**; `homebrain-companion` owns communication intent/memory/reminders/messages/follow-up **and computes the routing decision**; `mass-resolver` remains the deterministic media/speaker executor. The policy is a **shared channel vocabulary**.
- **Satellite work is its own track (Track S)**; **do not build satellite routing until specifically approved**; **first step = inventory satellite capabilities/entities after install.** PCL MVP (text-first to source) does not depend on it.
- **The deterministic media-interruption `InteractionAudioPolicy` (C§8) is part of Track S (step S2.5)** — it depends on satellite room context + a room→media-zone map, so it is **design-only until satellites are installed and inventoried**. PCL P0 defines only its boundary/hooks (§6B), never the mechanics.

### C§8 — Deterministic media interruption / Interaction Audio Policy (⟲ Added 2026-06-29)
- When a satellite interaction starts in a room where music is playing: **same-room media ducks or pauses on interaction start.**
- The media is **held paused/ducked through the interaction and the assistant's response.**
- **No auto-resume by default.** **Resume only on an explicit user command** ("resume music" / "continue playing" / "you can resume"). Timeout-based auto-resume MAY be added later but MUST NOT be the default.
- **Preserve the pre-interaction volume + playback state** so restore is accurate.
- **Unrelated rooms are never touched.**
- **Unknown room/satellite/media mapping ⇒ no media manipulation (fail safe).**
- **Mechanics are deterministic code in the resolver/HA media-interaction layer — never PCL business/memory logic, never LLM discretion.** This is a **separate `InteractionAudioPolicy`, not a field of `ResponseRoutingPolicy`** (§6B).
- **Use pause/volume-duck, never `media_stop`** (avoids the stop-wedge; ONBOARDING §6/§8/§11).
- **PCL P0 defines only the boundary/hooks; full mechanics = Track S step S2.5.** PCL P0–P2 do not depend on it.

## Appendix B — One-paragraph summary for a teammate

> HomeBrain's `mass-resolver` is pure, deterministic, the sole TTS owner, and pinned to Python 3.5.2; the new Personal/Communication Layer is stateful and privacy-heavy, so it should be a **separate, containerized sibling service** (`homebrain-companion`) with its own **SQLite** store — not bolted onto the resolver and not built in Home Assistant. It **reuses** the resolver's proven contracts: the `resolve→validate→execute→CommandResult` lifecycle, the `CommandResult` wire shape, the LAN shared-secret ingress, and especially the **F1-R relay** (script returns `{chat_text}` via `stop`+`response_variable`; never `set_conversation_response`). HA stays the voice/timer/notification I/O layer; the resolver stays deterministic actions + TTS; the companion owns conversation, short-term context, and long-term memory, and calls `/command` for device actions ("play the second one"). **MVP = notes only (create/recall/forget), local-only, audit + delete**, exposed to ChatGPT only after the F1-R relay + a sentinel-probe (durable reminders → P1; light decisions/referents → P2); receipts (esp. images), cloud, multi-user, and semantic memory are gated later phases on a **separate Track P** that must not entangle media Inc 2–4.
