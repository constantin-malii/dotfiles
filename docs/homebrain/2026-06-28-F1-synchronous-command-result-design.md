# Foundation F1 — Synchronous Command Result Framework (Design)

**Date:** 2026-06-28
**Status:** Design only (pre-implementation) — **stop for review before the implementation plan**
**Related:** [assistant-tooling-design.md](2026-06-27-assistant-tooling-design.md) (umbrella),
[local-music-architecture.md](local-music-architecture.md), [assistant-capabilities.md](assistant-capabilities.md)

## Why F1

Today, capabilities are invoked **fire-and-forget**: ChatGPT calls an HA script → the script fires an
HA event (`mass_play_request` / `mass_radio_request`) → the resolver handles it asynchronously and the
**speaker** (Piper) announces the truth. The script returns immediately, so **ChatGPT never receives
the outcome** and must *infer* it — producing wrong text ("Playing My Way" when it wasn't found;
"couldn't find any" when the speaker actually listed stations). The speaker is honest; ChatGPT's text
is not.

F1 replaces fire-and-forget with a **synchronous request/response**: every capability returns a
structured `CommandResult`, and the calling HA script relays it back to ChatGPT — so ChatGPT reports
exactly what happened. This supersedes the backlog item "synchronous play-result" and makes all future
capabilities honest **by construction**.

This is a **foundation** increment: no new user-facing feature, but it strengthens the platform that
News/Status/Acquisition build on.

---

## 1. Architecture proposal

**Today (async):**
```
ChatGPT → script.play_music → fire event mass_play_request ──(returns void)──> ChatGPT guesses
                                         │ (async)
                                 resolver dispatch → capability → MA play + Piper announce
```

**F1 (synchronous):** add a request/response path. The resolver gains a small **local HTTP command
endpoint**; HA scripts call it and **get the `CommandResult` back**, then relay `chat_text` to the
conversation and speak `spoken_text`.
```
ChatGPT → script.play_music → rest_command POST /command {intent,params}
              → resolver: resolve → validate → execute → CommandResult (JSON)  ──(returns)──>
          script: set_conversation_response = chat_text ; (if spoken_text) tts.speak
              → ChatGPT reports the REAL result
```

Key points:
- The resolver's capability functions **already return a result dict** (Inc 0/1 contract:
  `ok/intent/spoken/...`). F1 **formalizes** that into `CommandResult` and exposes it **synchronously**.
- Add a **synchronous transport adapter** (an HTTP server inside the resolver) **alongside** the
  existing HA-event adapter. Capabilities are transport-agnostic; the same `CommandResult` flows to:
  the HTTP adapter (new), the HA-event adapter (existing, kept for transition + Lidarr sync), and a
  future **MCP** adapter (also synchronous — F1's contract is exactly what MCP wants).
- **Transport choice:** resolver exposes `POST /command` (JSON in → `CommandResult` JSON out), bound to
  the LAN/loopback interface the HA VM reaches (`192.168.122.x`), with an **optional shared-secret
  header**. HA calls it via **`rest_command` with `response_variable`** (supported in current HA), so
  the script captures the result. This is also the same HTTP ingress the §11 hardware-volume feature
  wanted — one ingress, reused.
  - *Fallback if `rest_command` response capture proves limited on this HA version:* a `python_script`
    or a tiny custom integration performing the request/response. The plan will confirm the mechanism
    on the live HA before committing.
- **Latency:** the ChatGPT tool call now waits for `resolve+validate+execute`. Music/radio play is
  ~0.2–0.4 s (fine). Slow operations (e.g. acquisition) return a fast **"queued"** `CommandResult`
  rather than blocking. The plan will set per-capability timeouts.
- **Security:** endpoint bound to the internal interface only; optional bearer/shared-secret in the
  `rest_command` header (stored in a 0600 file like the other secrets). No new external exposure.

---

## 2. `CommandResult` schema

```json
{
  "ok": true,
  "intent": "music",
  "request_id": "ab12cd34",
  "spoken_text": "Playing Du Hast.",
  "chat_text": "Playing \"Du Hast\" by Rammstein on the ceiling speakers.",
  "error": null,
  "metadata": { "uri": "filesystem_smb--…/track/…", "title": "Du Hast", "artist": "Rammstein", "source": "library", "played": true },
  "actions": []
}
```
Failure example:
```json
{
  "ok": false,
  "intent": "music",
  "request_id": "ef56…",
  "spoken_text": "Sorry, I couldn't find My Way in the local library.",
  "chat_text": "\"My Way\" isn't in your local library yet.",
  "error": { "code": "not_found", "reason": "no preferred-provider match for 'My Way'" },
  "metadata": { "query": "My Way" },
  "actions": []
}
```

Fields:
- **`ok`** (bool) — overall success.
- **`intent`** (str) — `music|radio|news|status|acquire|sync|…`.
- **`request_id`** (str) — correlation id.
- **`spoken_text`** (str|null) — concise line for **TTS** on the speaker; `null` = say nothing.
- **`chat_text`** (str) — **always present**; what ChatGPT/the caller reports to the user (may be
  richer than spoken_text). This is the field that ends fire-and-forget guessing.
- **`error`** (obj|null) — `null` on success; else `{ "code", "reason" }`. **`code` is enumerated**
  (initial set): `not_found`, `invalid_input`, `play_failed`, `upstream_error`, `not_implemented`,
  `unauthorized`, `unavailable`. `reason` is human-readable.
- **`metadata`** (obj) — structured, capability-specific (music: uri/title/artist/source/played;
  radio: station/source/uri; find: `stations[]`/`count`; status: state/title/artist/volume).
- **`actions`** (array, optional, future) — suggested follow-ups (e.g. "say 'play the first one'").

**Backward-compat mapping** (Inc 0/1 dict → CommandResult): `ok`→`ok`; `spoken`→`spoken_text`;
`reason`→`error.reason` (+ infer `error.code`); `speak_success` → speak `spoken_text` on success;
remaining extras (`uri`/`station`/`source`/`played`/`stations`) → `metadata`. `chat_text` defaults to
`spoken_text` when a capability hasn't yet been migrated to set it explicitly.

---

## 3. Common capability interface (`resolve → validate → execute → CommandResult`)

Every capability implements the same lifecycle (pure stages where possible, side effects isolated to
`execute`):

```python
class Capability:
    name = "music"

    def resolve(self, ctx, params) -> Resolved:
        # Interpret intent into concrete target(s). NO side effects.
        # e.g. query → ranked candidate items.

    def validate(self, ctx, resolved) -> Validation:
        # Decide feasibility BEFORE acting: found? provider available? input valid? allowed?
        # On failure → CommandResult(ok=False, error=not_found/invalid_input/...) and DO NOT execute.

    def execute(self, ctx, resolved) -> CommandResult:
        # Perform the side effect (play, fetch headlines, add to Lidarr). Report play_failed etc.

def handle(ctx, intent, params, rid) -> CommandResult:
    # Orchestrates resolve → validate → execute, builds CommandResult, maps exceptions to
    # error=upstream_error. This is what every transport adapter (HTTP, event, MCP) calls.
```

Why this shape: **`validate` runs before `execute`**, so "not found" / "invalid" are determined
*synchronously and truthfully* and returned without side effects — exactly the honesty fix. `execute`
owns the only side effects, so dry-run = run `resolve`+`validate` and skip `execute`. The dispatcher
(`core`) and all adapters depend only on `handle(...) -> CommandResult`.

---

## 4. Migration plan — Music and Radio

Incremental, dual-path, one capability at a time:

- **F1-A — Contract + interface:** add `CommandResult` + the `resolve/validate/execute/handle` shape;
  refactor `music.py` and `radio.py` to it; keep returning a superset so the **existing event path
  still works** (an adapter maps `CommandResult` → today's announce behavior). Pure unit tests.
- **F1-B — Synchronous transport:** add the resolver `POST /command` HTTP server (capability-agnostic;
  calls `handle`). Unit-test the request/response + error mapping with fakes.
- **F1-C — HA wiring:** add a `rest_command` (with `response_variable`) and update `script.play_music`,
  `script.play_radio`, `script.find_stations` to call it, set `set_conversation_response = chat_text`,
  and `tts.speak` the `spoken_text`. **Keep the old event-firing scripts saved** (backups) for instant
  rollback.
- **F1-D — Validate + cut over:** dry-run + audible + **conversational** ("play My Way" → ChatGPT now
  says "not in your library" truthfully; "find jazz stations" → ChatGPT relays the list). Migrate
  music first, validate, then radio. Retire the event path **per capability** only after its sync path
  passes. The **`mass_sync_request`** (Lidarr) event stays (no user-facing result needed).

No HA restart beyond the resolver service restart for the new HTTP server; scripts edited via API.

---

## 5. Impact on future News, Status, Acquisition, TV

All new capabilities implement `resolve/validate/execute` and return `CommandResult` from day one — no
fire-and-forget debt:

- **News (Inc 2):** `validate` = feed reachable / has items; `execute` = TTS headlines or play a news
  station; `metadata.headlines[]` / `station`; `chat_text` = a short summary. Synchronous = ChatGPT can
  actually read back "Top headline: …".
- **Status (Inc 4):** inherently a **query needing a response** — F1 is the natural fit. `execute`
  gathers now-playing; `metadata` = {state,title,artist,volume}; `chat_text`/`spoken_text` = "Playing X
  by Y at 35%."
- **Acquisition (Inc 3):** `validate` = found in Lidarr + not already present + guardrails; `execute` =
  add+search → `ok`/"queued"; `error=not_found|unavailable`. ChatGPT can say "Added Dire Straits;
  downloading" or "couldn't find it" **truthfully**.
- **TV (future, out of scope):** same contract would apply if ever added; today the assistant still
  declines TV. F1 imposes no TV work.

Net: F1 is the platform that makes Inc 2–4 honest and uniform.

---

## 6. Rollback strategy

- **Additive & dual-path:** `CommandResult`, the HTTP endpoint, and the new scripts run **alongside**
  the existing event path; nothing is removed until each capability's sync path is validated.
- **Per-capability, reversible cutover:** each migrated HA script is **backed up before editing**;
  rollback = restore the backup (re-point the script to fire the event). 
- **Resolver:** keeps both adapters; disabling the HTTP server reverts to event-only behavior.
- **Baseline:** the Inc 0/1 event path remains fully functional throughout; the original monolith
  fallback (`resolver.py.orig`) also remains. 
- Each F1 sub-step is its own commit, so `git revert` of a step is clean.

---

## 7. Transition plan (Inc 0/1 keep working during migration)

- The **event adapter** (`mass_play_request` / `mass_radio_request` / `mass_sync_request`) stays live
  for the whole of F1. Existing exposed scripts keep working until each is individually migrated and
  validated.
- **Dual-run:** the HTTP endpoint is added without removing events. Capabilities return `CommandResult`;
  the event adapter maps it to today's announce behavior → **zero regression** for un-migrated paths.
- Migrate **one capability at a time** (music → validate → radio → validate). Lidarr's sync event is
  untouched.
- **ChatGPT exposure unchanged** until each migrated script is validated (same rule as Inc 0/1).
- No HA restart beyond the resolver service restart (for the HTTP server); scripts via API reload.

---

## Roadmap / backlog changes (made with this design)

- **Folded in:** the backlog item *"synchronous play-result"* is **superseded by F1** and removed as a
  standalone item.
- **Unchanged:** the *GPT-4o evaluation* remains a **separate, gated** backlog item — evaluate only
  **after F1 is complete** and only **if** tool-selection issues remain.
- **Build order:** **F1 is the next increment** (foundation), before Inc 2 (News). Inc 2/3/4 then build
  on the `CommandResult` contract.

## Constraints (carried)

Python 3.5-safe; secrets only in 0600 files (incl. any HTTP shared-secret), never logged/committed;
additive/reversible; user runs sudo/restarts; do not expose new functionality to ChatGPT until
validated; no AI attribution in commits; secret-scan before commits.

---

**Next step:** review this design. On approval, I'll write the F1 implementation plan (task-by-task,
TDD, subagent-driven — same as Inc 0/1). **No implementation until the plan is approved.**
