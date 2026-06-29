# Inc 4A — Status / Now Playing (Design)

**Date:** 2026-06-29
**Status:** **Design v2 — Phase-1 revised (HA-state-primary, summary-only).** For review — **no
implementation.** Stop for approval before writing code or scripts.
**Related:** [assistant-tooling-design.md](2026-06-27-assistant-tooling-design.md) (umbrella, §4
`status() -> now-playing/queue`, §7 Inc 4), [F1 design](2026-06-28-F1-synchronous-command-result-design.md)
(§2 `CommandResult`, §3 capability lifecycle, §5 "Status … F1 is the natural fit"),
[F1-R addendum](2026-06-28-F1-R-chatgpt-tool-result-relay-design.md) (hard tool return),
[assistant-capabilities.md](assistant-capabilities.md), [ONBOARDING.md](ONBOARDING.md).
**Build reference / plan:** [plans/2026-06-29-inc4a-status-now-playing.md](plans/2026-06-29-inc4a-status-now-playing.md).

## v1 decisions (locked 2026-06-29, after critical review + real-code follow-up)
1. **HA-state-primary.** Source = `media_player.ceiling_speakers` state/attributes. **v1 read mechanism
   = HA REST `GET /api/states/media_player.ceiling_speakers`** (locked; preferred over HA WS — smallest
   implementation, isolated per call, no shared-socket response/event interleave, Python 3.5-safe).
   **MA WebSocket is not the v1 source** — future enrichment/fallback only if HA attributes prove
   insufficient. **No MA WS host probe in v1** unless later explicitly approved.
2. **Summary-only.** No `aspect` enum, no per-aspect `chat_text` branches, no invalid-aspect handling.
   One self-sufficient `chat_text`; `metadata` kept broad so aspect-specific wording can be added later
   without a schema change.
3. **Real-code shape.** `status.py` is currently a legacy/stub function (not a real capability). Inc 4A
   creates **`StatusCapability(capability.Capability)`**, adds it to **`core.CAPS["status"]`**, and
   **removes `"status"` from `core._STUBS`**. Rollback reverts all three atomically (§6).
4. **Unconditionally silent.** `spoken_text = None` on **success and error** (rationale in §3). No
   `tts.speak`; no `set_conversation_response`.
5. **Source seam.** Read HA state through `haconn.py`; it has **no** read method today and its existing
   socket is shared, so add a small **read-only, isolated** state reader (§2). **No `maconn.py`
   player/queue read methods in v1** — only added if the HA capture proves insufficient and the MA
   fallback is explicitly approved.

## Why Inc 4A (scope decision)

Inc 4 in the umbrella roadmap is "Status + household (now-playing/status + sleep timer + shuffle
favorites)." Per the accepted priority decision, we carve out **Inc 4A = read-only now-playing/status
only** as the next track — the lowest-risk first use of the completed F1/F1-R foundation:

- **Read-only.** No playback, transport, queue, timer, or config side effects.
- **No external dependencies.** No feeds, provider decisions, or product curation (unlike Inc 2/3).
- **Directly validates `CommandResult.chat_text` for query-style capabilities** — Status is, per F1 §5,
  "inherently a query needing a response," so it exercises the relay in its purest form.

**Explicitly deferred to later Inc 4 sub-tracks (NOT in 4A):** sleep timer (→ resolver per PCL C§5),
shuffle/repeat/queue controls, personal reminders/timers (→ PCL), any PCL work, Inc 2 News, any YTM
work.

## Architecture principle — thin language layer, strong executor

```
natural language → intent/params → deterministic capability executor → HA state → CommandResult
   (ChatGPT + tool                 (the focus of Inc 4A)
    descriptions, thin)
```

**The priority of Inc 4A is the deterministic end-execution side**, not natural-language parsing:
read HA player state → **normalize** it → return a **reliable `CommandResult`** → deliver via the
hard tool return → handle **music / radio / paused / idle / unavailable** correctly.

The **language layer stays minimal**: the resolver does **not** build a phrase-matching / NLU layer,
and v1 has **no `aspect` param**. We assume ChatGPT + the tool description map common user phrasings
onto the status tool. The capability takes (effectively) no params and returns truthful, normalized
state — that is where the engineering effort goes.

---

## 1. User-facing phrases (illustrative — not a parser spec, no aspect param)

The capability answers these query intents on the ceiling-speaker zone. In v1 they all map to the
**single `status` tool** and yield one self-sufficient `summary` `chat_text`:

| Phrase (examples) | Answered by the summary `chat_text` (+ broad `metadata`) |
|---|---|
| "What's playing?" / "What's on?" | state + title/artist or station + volume |
| "What song is playing?" / "Who is this?" | title + artist (music) — present in summary |
| "What station is playing?" | station name (radio) — present in summary |
| "What volume is it?" / "How loud is it?" | volume percent — present in summary |
| "Is anything playing?" | summary states playing/idle |

**v1 = summary-only.** One `chat_text` such as `Playing "Du Hast" by Rammstein at 35% volume.` answers
what's-playing / what-song / how-loud in a single line; idle → `Nothing is playing right now.` ChatGPT
phrases the user's specific question from that text. **No `aspect` enum, no per-aspect branches, no
resolver phrase matching.** `metadata` is comprehensive regardless, so a future `aspect` enrichment is a
pure additive `chat_text` change with **zero** schema/contract impact.

---

## 2. Status data source — HA-state-primary

**Primary (v1):** Home Assistant `media_player.ceiling_speakers` **state + attributes**:
`state` (`playing | paused | idle | off | unavailable`), `media_title`, `media_artist`,
`media_content_type`, `volume_level` (0.0–1.0), and related attributes. This is a **stable HA-core
abstraction** — far less coupled to MA internals than the MA queue/player schema, and it needs no host
probe.

**Read mechanism (real-code finding — `haconn.py`):** `haconn.HA` today has **no state-read method**
(`connect/subscribe/read/call_service/announce/close` only), and its connection is the **shared,
persistent event-subscription socket** (`connect()` sets `settimeout(None)`; the serve loop reads
events on it). **Reading ad-hoc state on that shared socket would interleave responses with subscribed
events** — unsafe. Therefore Inc 4A adds a **small, isolated, read-only** state reader. Two safe shapes:

- **(Recommended) HA REST `GET /api/states/media_player.ceiling_speakers`** with the existing HA token
  as a `Bearer` header, via a **fresh per-call** request (stdlib `http.client`/`urllib.request`,
  Python 3.5-safe). Smallest payload (one entity), no WS framing, no shared-socket interleave.
- **(Alternative) Fresh per-call HA WS `get_states`** connection (open → `get_states` → filter the
  entity → close), mirroring the MA `ma_factory` per-call pattern. Larger payload (all entities); only
  if REST is undesirable.

Either way the read is **isolated from the event socket**. The wrapper lives in `haconn.py` (or a tiny
helper) and is **read-only** — no `call_service`, no mutation.

**MA WebSocket — contingency only.** If the HA attribute capture (Phase 2) shows HA cannot carry a
needed field (e.g. cannot distinguish radio from a track, or lacks the station name), **only then** —
and **only with explicit approval** — add read-only `players/get` / `player_queues/get` wrappers to
`maconn.py` as enrichment/fallback. **Not used in v1; no MA probe in v1.**

**Radio-vs-track discriminator:** derive `source ∈ {music, radio, none}` from HA attributes (e.g.
`media_content_type`, presence of `media_artist` vs a station-style `media_title`). The exact field
mapping is confirmed by the **no-host HA attribute capture** (Phase 2) before the normalizer is coded.

**Normalized `metadata` (built by a pure normalizer):** `player_state`, `source`, `title`, `artist`,
`station`, `media_content_type`, `volume_level` (0–1), `volume_percent` (0–100 int), `available`.

---

## 3. `CommandResult` schema for status

Follows the live F1 contract exactly (verified in `command_result.py`: `ok()`/`err()` produce
`{ok, intent, request_id, spoken_text, chat_text, error, metadata, actions}`; `err()` rejects codes
outside the enum). `intent = "status"`.

**Success — music playing:**
```json
{
  "ok": true, "intent": "status", "request_id": "ab12cd34",
  "spoken_text": null,
  "chat_text": "Playing \"Du Hast\" by Rammstein at 35% volume.",
  "error": null,
  "metadata": { "player_state": "playing", "source": "music",
                "title": "Du Hast", "artist": "Rammstein", "station": null,
                "media_content_type": "music",
                "volume_level": 0.35, "volume_percent": 35, "available": true },
  "actions": []
}
```

**Success — radio playing:** `chat_text: "Playing 101 SMOOTH JAZZ at 35% volume."`,
`metadata.source:"radio"`, `metadata.station:"101 SMOOTH JAZZ"`, `title/artist: null`.

**Success — paused:** `chat_text: "Playback is paused — \"Du Hast\" by Rammstein."`,
`player_state:"paused"`.

**Success — nothing playing (idle/off):** `ok:true` (the query succeeded), `source:"none"`,
`chat_text:"Nothing is playing right now."`

**Error / unavailable:**
```json
{ "ok": false, "intent": "status", "spoken_text": null,
  "chat_text": "Sorry, I couldn't check what's playing right now.",
  "error": { "code": "unavailable", "reason": "HA state read failed" },
  "metadata": { "available": false }, "actions": [] }
```

Field rules:
- **`ok`** — `true` for any successfully-read state, **including "nothing playing"**. `false` only when
  the status itself could not be read.
- **`chat_text`** — always present; the single summary answer ChatGPT relays verbatim.
- **`spoken_text` — `null` on BOTH success and error (unconditional silence).**
  *Rationale (real-code, `core.py:66-70`):* `core.dispatch` is the single TTS owner and will speak a
  result's `spoken_text` when `ok`, **or on error when `settings.announce_failures` is True**. If a
  status *error* carried `spoken_text`, a mere "what's playing?" query could speak "couldn't check…"
  over current playback. Setting `spoken_text=None` everywhere makes status reliably silent — ChatGPT's
  relayed text is the only answer. (Speaking is also unreachable on phone TTS — NAT-IP split.)
- **`error.code`** — from the live enum (`command_result.ERROR_CODES`): **`unavailable`** (HA
  unreachable / entity `unavailable`), **`upstream_error`** (unexpected exception). No `not_found`
  (status always has an answer). No `invalid_input` for aspect (no aspect in v1).
- **`metadata`** — comprehensive (the §2 fields), so future aspect wording needs no schema change.
- **`actions[]`** — empty for 4A (reserved).

**Edge cases the normalizer must handle (tested in §5):** `volume_level` **null**, **0.0**, and
**near-silent** (e.g. 0.09) — report truthfully, never infer audibility; **rounding** of
`volume_percent` (define: round half-up, e.g. 0.355 → 36); **missing artist** (music with title only);
**missing station/title** (radio with no name; "playing" but media fields empty during the transition
window → report `playing` with whatever is known, don't fabricate); **`off` vs `idle`** (map both to
`source:"none"`; preserve the distinct `player_state`).

---

## 4. Capability + HA script/tool shape

### Resolver capability (real-code shape)
`status.py` is currently a **legacy stub function** (`status(ctx, params, rid)` returning an old-style
dict) and is wired only via `core._STUBS` ("Status isn't available yet."), not the new lifecycle. Inc 4A:
1. **Create `StatusCapability(capability.Capability)`** mirroring `MusicCapability`
   (`resolve → validate → execute`, Python 3.5-safe):
   - **`resolve(ctx, params)`** — no params in v1; perform the **isolated read-only HA state read**
     (§2) and stash the raw state; no side effects beyond the read.
   - **`validate(ctx, resolved)`** — returns `None` (nothing to validate without an aspect; an
     unreadable state surfaces as an error in `execute`, mapped to `unavailable`).
   - **`execute(ctx, resolved, rid)`** — normalize → build the summary `chat_text` → return
     `cr.ok(self.name, rid, chat_text, spoken_text=None, metadata=…)`, or
     `cr.err(self.name, rid, "unavailable"/"upstream_error", reason, chat_text, spoken_text=None, …)`.
     (`capability.run` already maps uncaught exceptions to `upstream_error`.)
2. **Register `core.CAPS["status"] = status.StatusCapability()`** and **remove `"status"` from
   `core._STUBS`**.
3. **No legacy event-path wrapper** (unlike `music.py`'s `resolve_music`) — status has **no event
   adapter** (a query has no fire-and-forget meaning), so none is needed.

The HTTP `/command` adapter already routes any registered intent to `dispatch` (`http_server.py`), so
**no adapter change** is required once `status` is in `CAPS`.

### HA tool (new script — created only at the gated implementation step)
A brand-new **`script.media_status`** (proposed alias `Ceiling: Media Status (resolver)`), **no
fields in v1** (no `aspect`), using the proven hard-return pattern:
```jsonc
[
  {"action": "rest_command.resolver_command",
   "data": {"intent": "status", "params": {}},
   "response_variable": "r", "continue_on_error": true},
  {"variables": {"resp": {"chat_text": "{{ r.content.chat_text if (r is defined and r.content is defined and r.content.chat_text is defined) else 'Sorry, I could not check what is playing.' }}"}}},
  {"stop": "done", "response_variable": "resp"}
]
```
- **No `set_conversation_response`. No `tts.speak`.** Resolver stays the sole TTS owner (and status is
  silent — `spoken_text=None`). Reuses the live `rest_command.resolver_command` (30 s, `X-Resolver-Key`)
  — **no new HA REST command, no agent-instruction change, no event adapter.**

---

## 5. Validation matrix

Run during the gated implementation, each from a captured/restored baseline. **No aspect rows** (v1 is
summary-only).

| # | Scenario | Setup | Expected `chat_text` | `ok` | `metadata` checks |
|---|---|---|---|---|---|
| 1 | **Music playing** | play a local track | `Playing "<title>" by <artist> at N% volume.` | true | `source=music`, title/artist set, `volume_percent` |
| 2 | **Radio playing** | play a station | `Playing <station> at N% volume.` | true | `source=radio`, `station` set, no fabricated artist |
| 3 | **Paused** | pause playback | `Playback is paused — …` | true | `player_state=paused` |
| 4 | **Idle / off** | stopped / nothing queued | `Nothing is playing right now.` | true | `source=none` (both off & idle) |
| 5 | **Unavailable / error** | HA read fails / entity unavailable | `Sorry, I couldn't check what's playing right now.` | false | `error.code=unavailable`, `available=false` |

**Edge-case unit tests (fixtures from the Phase-2 capture; no live needed):** null volume; zero volume;
near-silent volume (0.09); rounding (0.355 → 36); missing artist; missing station/title; off vs idle;
playing-but-empty media fields (no fabrication).

**Standard gates (as in F1-R):**
- **Direct `/command`** (`intent=status`) → expected `CommandResult`; `200` w/ key, `401` w/o.
- **Direct script return-shape** — WS `call_service script.media_status` with `return_response:true` →
  `{chat_text: …}`; **no playback, no TTS** (resolver speaks 0 times — `spoken_text=None`).
- **Readback** — script has `rest_command` + `stop`/`response_variable: resp`; **no
  `set_conversation_response`**, **no `tts.speak`**.
- **Concurrency / no-regression** — issuing a status read **during and after** a `play`/`radio`/`find`
  command does **not** regress those commands (see §8: HA-primary reads are isolated; MA, if ever used,
  is fresh-per-call). Existing three scripts, the event adapter, and `mass_sync_request` behave
  unchanged; `/command` health 200/401.
- **ChatGPT conversational** — only after exposure is separately approved (out of the build phases).

---

## 6. Rollback strategy

Additive; cleaner than the F1-R migrations.
- **Resolver — atomic 3-part revert (all together; a half-revert leaves `core` referencing a missing
  handler):** (a) **restore the `status.py` stub**, (b) **remove `status` from `core.CAPS`**, (c)
  **re-add `"status"` to `core._STUBS`**; plus revert the small read-only reader added to `haconn.py`.
  Done via **git revert / restore** of the 4A commit. A **resolver service restart** to load the
  rolled-back code is a **separate action requiring explicit approval** (user-run) — **never implied as
  automatic.**
- **HA script:** `script.media_status` is **brand-new** — rollback = **delete** the script + reload.
  **No existing script is edited.** No restart.
- **Exposure:** not exposed until separately approved; un-expose = WS `homeassistant/expose_entity`
  toggle.
- **Untouched throughout:** `/command`, the event adapter, `mass_sync_request`, the three existing
  scripts, gpt-4o-mini, and all MA/HA **config** (4A is read-only against HA).

---

## 7. Exposure: new tool vs fold into existing

**Recommendation: a new dedicated ChatGPT tool `script.media_status`** (exposed only after validation +
**separate** explicit approval — not in the build phases).

- **Distinct query intent** (vs the action tools) — folding into `play_music`/`play_radio` would
  pollute their descriptions and risk routing regressions.
- The resolver already reserves a **`status` intent** — a 1:1 tool keeps the mapping clean. Tool count
  3 → 4, within the deliberate ~6-tool ceiling.
- **Explicit note — raw `media_player` exposure is rejected.** We deliberately do **not** expose
  `media_player.ceiling_speakers` to the conversation agent for "what's playing." Exposing the raw
  entity **widens the LLM surface** and **re-enables broken built-in intents** (the documented "Oops"
  failures from unsupported `media_player.*` intents — ONBOARDING §8). A purpose-built, read-only,
  resolver-backed `script.media_status` keeps ChatGPT on the guarded surface. This is a *strength* of
  the design, recorded so it isn't second-guessed.
- `assistant-capabilities.md` + the OpenAI Instructions gain a concise STATUS line **in lockstep** at
  exposure time (a separate, approved step).

---

## 8. Risks & unknowns

- **HA attribute sufficiency (the one real unknown).** Whether HA attributes cleanly carry the
  radio-vs-track discriminator + station name is confirmed by the **no-host HA attribute capture**
  (Phase 2). If insufficient → escalate to the **approval-gated** MA fallback (§2). HA-primary
  **reduces MA-internal overfit**.
- **HA shared-event-socket hazard (handled).** Reads must use a fresh/isolated path (REST-per-entity or
  a fresh WS `get_states`), never the persistent event socket — see §2.
- **HA state staleness / drop window.** During a rare HA↔MA drop (self-healed by A1/A2a), the entity may
  read `unavailable`; status then returns an honest "couldn't check," which is acceptable. Steady-state
  now-playing attributes are accurate.
- **Volume semantics.** Report `volume_level`/`volume_percent` truthfully (incl. null/0/near-silent);
  never infer audibility. Read-only — no `volume_mute` calls.
- **Concurrency (low, after real-code review).** MA uses a **fresh socket per call**
  (`core.Ctx.ma_factory`; `music.py` connect/`finally:close`) and the HTTP server is threaded — so even
  if MA is used later, status doesn't share a mutable WS with in-flight commands. **HA-primary v1
  avoids MA player/queue WS reads entirely**, sidestepping large-payload/framing concerns. Still
  validate status during/after a play does not regress existing commands (§5).
- **Model routing.** gpt-4o-mini must pick `media_status`. Mitigation: a clear tool description at
  exposure; summary is a safe single answer. No model change.
- **Latency.** One small HA REST GET — well under the 30 s `rest_command` timeout.

---

## Out of scope (explicit)
`aspect` enum (deferred — summary-only v1); sleep timer; shuffle/repeat/queue/transport; personal
reminders/timers; any PCL work; Inc 2 News; any YTM work; MA WS reads (contingency only, approval-gated);
any change to `play_music`/`play_radio`/`find_stations`, the event adapter, `mass_sync_request`, the
agent model, or MA/HA config beyond creating the one new (initially-unexposed) script.

## Open questions for the reviewer
*All resolved by the locked decisions:* data source = **HA-state-primary**; v1 read mechanism = **HA
REST `GET /api/states/media_player.ceiling_speakers`** (preferred over HA WS); **no `aspect`** (summary-
only); tool name **`media_status`**; silence = **`spoken_text=None` on both success and error**; **no MA
probe in v1** (contingency only, approval-gated); **exposure stops at validated-but-unexposed** — ChatGPT
exposure remains **Phase 9, separately approved**. No open questions remain for v1.

## Self-review
- HA-state-primary; MA WS contingency/approval-gated; no MA probe v1 ✓.
- Summary-only; no `aspect` enum/branches/invalid-aspect ✓; `metadata` broad for future wording ✓.
- Real-code shape: `StatusCapability` + `CAPS` add + `_STUBS` removal, atomic 3-part rollback ✓.
- Unconditional silence (`spoken_text=None` on success **and** error) with the `core.dispatch`
  rationale ✓; no `tts.speak`; no `set_conversation_response` ✓.
- Source seam via `haconn.py` read-only reader (shared-socket hazard noted) ✓; no `maconn.py` reads
  in v1 ✓.
- Edge tests (null/zero/near-silent volume, rounding, missing artist/station/title, off vs idle,
  playing-but-empty) ✓; concurrency/no-regression note ✓.
- Raw `media_player` exposure explicitly rejected ✓. Keeps `script.media_status`, hard return, no event
  adapter, no change to existing scripts, no exposure before approval, Python 3.5 ✓.
- **No implementation performed** — design only.
