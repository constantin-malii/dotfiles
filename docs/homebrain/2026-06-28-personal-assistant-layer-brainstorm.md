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

**MVP recommendation:** The first safe slice is **notes + durable reminders + light decisions, local SQLite, exposed to ChatGPT via the F1-R relay**, with audit + delete from day one. **Hard dependency:** the PCL's ChatGPT exposure rides on the **F1-R relay being landed** (currently approved-design, music re-migration pending). No receipts/images, no cloud, no multi-user, no semantic memory in the MVP.

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
- **Roadmap state:** Inc 0 (foundation) ✅, Inc 1 (radio) ✅, **F1** (CommandResult framework) live, **F1-R** relay proven (music-only re-migration = design approved, *pending execution*), Inc 2 News, Inc 3 Acquire, **Inc 4 Status + household (sleep timer, shuffle)** — note Inc 4 brushes against PCL territory (§13).

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

## 7. ChatGPT / Tool Integration Model (⟲ Reconciled — bound to the F1-R relay)

**Principle: expose *capabilities*, not *internals*; the LLM orchestrates, deterministic code executes/persists; and every exposed result rides the proven relay.**

### The relay is the contract
Any companion tool exposed to ChatGPT MUST:
1. Be backed by an HA script that calls `rest_command` → `POST /companion` and captures the result in `response_variable`.
2. **Return `{chat_text: …}` via `stop`+`response_variable`** (NOT `set_conversation_response` — F1-R proved the agent ignores it).
3. Rely on the existing one-line agent Instruction ("relay `chat_text` verbatim").
4. Emit a `CommandResult`-shaped payload (so `chat_text`/`spoken_text`/`error` semantics carry over unchanged).

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
2. **Firing + delivery** (HA-owned): at `due_at`, fire via **ceiling-announce** (room; works because the host fetches the NAT-IP TTS URL) and/or **mobile push** (the phone path, since phone TTS is unreachable). The companion must not speak directly (single-TTS-owner discipline, §6).

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

## 14. MVP Proposal

**Goal:** prove the sibling-service shape + truthful memory at lowest privacy/operational risk, reusing the resolver's contracts and the F1-R relay.

**Hard dependency (⟲ Reconciled; locked — see Appendix C §6):** PCL implementation does **not start** until **(a) F1-R music is stable** and **(b) the Speaker WebSocket reconnect bug is fixed**. ChatGPT exposure additionally rides on the **F1-R relay being landed** (music re-migration currently pending execution). Until those gates pass, the MVP may be *designed* but not built; once building, it can be validated **over HTTP only** (like F1 validated `/command` before scripts) and exposed to ChatGPT *after* the relay path is live and the new tool is validated (carried "don't expose until validated" rule).

**In scope (MVP):**
- New containerized `homebrain-companion` sibling; `POST /companion` (LAN + shared secret); SQLite store; modern Python.
- **Notes:** create / recall (tag/keyword/recency) / forget.
- **Durable reminders:** create with **confirmed absolute time**; simplest reliable firing (poll + push/ceiling-announce); list/complete.
- **Light decisions:** record + recall (enables "save that decision").
- **Short-term context** for the canonical flows: numbered-list referents ("the second one") via deterministic resolution against cached `metadata.stations[]`; "save that decision" snapshotting.
- **`CommandResult`-shaped results** (honest-by-construction) + the F1-R relay for any ChatGPT exposure.
- **Audit log** + `forget` from day one.
- Read-back via the existing ChatGPT-text path (no new TTS; no HA script changes until validated).

**Explicitly out of MVP:** receipts (esp. images) / OCR; cloud storage; multi-user/per-person privacy (single-shared only; `owner` field present for later); semantic/vector recall; auto-learned preferences/silent memory; new HA automations/YAML; message *sending* (draft-only); any change to `script.play_music`/`play_radio`/`find_stations` or the resolver.

**Definition of done:** "take a note…", "remind me…", "help me compare X / save that decision", "what notes about Y", and "play the second one" (delegated) all work — and every confirmation ChatGPT relays is *true* (verified against store/resolver via `CommandResult`), with an audit trail and a working delete. No second TTS path; resolver remains sole TTS owner.

---

## 15. Phased Roadmap (⟲ Reconciled — slotted against the live Inc/F1 roadmap)

This is a **separate track ("Track P")** from the media increments. It must not block or entangle Inc 2–4. It *depends on* F1-R for ChatGPT exposure.

| Phase | Theme | Adds | Gate to enter |
|---|---|---|---|
| **P0** | Foundation (MVP) | Containerized companion, SQLite, notes, durable reminders, light decisions, short-term context, `CommandResult` projection, audit, forget | This doc approved; **F1-R music stable** **and** **Speaker reconnect bug fixed**; **F1-R relay landed** (for exposure); resolver/HA untouched |
| **P1** | Voice + HA delivery | One HA companion tool → `/companion` via F1-R relay; reminder firing via HA timer/automation + push + ceiling-announce | P0 stable; "don't change HA" lifted deliberately; new tool validated before exposure |
| **P2** | Drafting + recall depth | Message drafting (human sends), richer recall, decision history | Notes/reminders trusted in daily use |
| **P3** | Receipts (structured) | Receipt *meta* (no image), categories, retention policy | Retention/audit/delete proven on notes |
| **P4** | Receipts (images) + OCR | Local blob storage, restricted dir, optional OCR | P3 stable; explicit privacy review |
| **P5** | Multi-user / family | Identity from HA, per-user partitioning, explicit family sharing | Dedicated privacy/security review passed |
| **P6** | Smart memory (opt-in) | Auto-learned prefs, semantic recall — opt-in + inspectable | Strong evidence of need; volume justifies |

Coordination notes: **Inc 4** (media) introduces a *sleep timer* and "household" features — align timers/reminders ownership so they're not built twice (§9). Keep PCL tool descriptions and `assistant-capabilities.md` in lockstep when anything is exposed (the media side already treats that doc + the OpenAI Instructions as the source of truth for what ChatGPT may claim).

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
- The PCL **must not create a second TTS path**.
- The **resolver remains the TTS owner**.
- The PCL **returns text**; any voice output must go through the **established path** (single owner) or be **explicitly designed later**.

### C§5 — Timers / reminders ownership
- **Media sleep timer → resolver / media roadmap** (Inc 4).
- **Personal reminders / timers → `homebrain-companion`.**
- **Home Assistant executes** timers, notifications, and entity actions.
- **`homebrain-companion` owns** interpretation, context, **durable reminder records**, and follow-up state.

### C§6 — Roadmap
- PCL stays **Track P** (separate from media Inc 2–4; must not entangle them).
- **Do not start implementation until (a) F1-R music is stable and (b) the Speaker reconnect bug is fixed.**
- First implementation is a **small MVP only**: **notes + durable reminders + light decisions + short-term referents.**
- **Receipts / images, semantic memory, multi-user, and cloud sync remain later gated phases.**

## Appendix B — One-paragraph summary for a teammate

> HomeBrain's `mass-resolver` is pure, deterministic, the sole TTS owner, and pinned to Python 3.5.2; the new Personal/Communication Layer is stateful and privacy-heavy, so it should be a **separate, containerized sibling service** (`homebrain-companion`) with its own **SQLite** store — not bolted onto the resolver and not built in Home Assistant. It **reuses** the resolver's proven contracts: the `resolve→validate→execute→CommandResult` lifecycle, the `CommandResult` wire shape, the LAN shared-secret ingress, and especially the **F1-R relay** (script returns `{chat_text}` via `stop`+`response_variable`; never `set_conversation_response`). HA stays the voice/timer/notification I/O layer; the resolver stays deterministic actions + TTS; the companion owns conversation, short-term context, and long-term memory, and calls `/command` for device actions ("play the second one"). **MVP = notes + durable reminders + light decisions + short-term referents, local-only, audit + delete**, exposed to ChatGPT only after F1-R lands; receipts (esp. images), cloud, multi-user, and semantic memory are gated later phases on a **separate Track P** that must not entangle media Inc 2–4.
