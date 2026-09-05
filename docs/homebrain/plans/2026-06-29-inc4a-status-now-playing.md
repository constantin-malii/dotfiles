# Inc 4A — Status / Now Playing — Implementation Plan

> **Plan only — do NOT implement. Stop at each marked gate for explicit approval.**
> Parent design (approved, v2 HA-state-primary): [../2026-06-29-inc4a-status-now-playing-design.md](../2026-06-29-inc4a-status-now-playing-design.md)
> Contracts (verified in-repo source): `mass-resolver/command_result.py`, `capability.py`, `core.py`,
> `music.py`, `haconn.py`, `http_server.py`. ·
> [F1](../2026-06-28-F1-synchronous-command-result-design.md) ·
> [F1-R](../2026-06-28-F1-R-chatgpt-tool-result-relay-design.md) · [ONBOARDING](../ONBOARDING.md).

## Approved decisions (locked for this plan — v1)
1. **HA-state-primary.** Source = `media_player.ceiling_speakers` state/attributes. **v1 read mechanism
   = HA REST `GET /api/states/media_player.ceiling_speakers`** (locked; preferred over HA WS — smallest,
   isolated per call, no shared-socket interleave, Python 3.5-safe). **MA WS is not the v1 source**
   (future enrichment/fallback only, approval-gated). **No MA WS host probe in v1.**
2. **Summary-only.** No `aspect` enum, no per-aspect `chat_text` branches, no invalid-aspect test. One
   self-sufficient `chat_text`; `metadata` broad enough to add aspect wording later with no schema change.
3. **Tool/script name:** `script.media_status`.
4. **Real-code shape.** Create `StatusCapability(capability.Capability)`; add `core.CAPS["status"]`;
   remove `"status"` from `core._STUBS`. **Rollback reverts all three atomically** (+ the `haconn` reader).
5. **Unconditionally silent.** `spoken_text=None` on **success and error** (`core.dispatch` owns TTS and
   may speak error `spoken_text` when `announce_failures` is on). No `tts.speak`; no
   `set_conversation_response`.
6. **Source seam.** Read HA state via `haconn.py` (it has **no** read method today, and its socket is the
   shared event-subscription connection → use an **isolated read-only** path, §Phase 4). **No `maconn.py`
   player/queue reads in v1** unless the HA capture is insufficient and the MA fallback is explicitly
   approved.
7. **Exposure not before explicit approval** (separate from the build phases).

## Global constraints (binding — every phase inherits these)
- **Python 3.5.2-safe:** no f-strings, stdlib `unittest` (no pytest), `.encode("ascii","replace")` for
  console.
- **Read-only against HA** — status performs **no** playback/transport/config side effects; emits **no**
  TTS.
- Reuse the live `resolve → validate → execute → CommandResult` lifecycle (`capability.run`), the
  authenticated `/command` adapter (`http_server.py` already routes any registered intent — **no adapter
  change**), and `rest_command.resolver_command` (30 s, `X-Resolver-Key`). **No** new HA REST command;
  **no** agent-instruction change; **no** event adapter (status is query-only; **no** legacy event
  wrapper like `music.py`'s `resolve_music`).
- **Additive/reversible.** `StatusCapability` + a read-only `haconn` reader + a brand-new
  `script.media_status` (no existing script edited). The three existing scripts, the event adapter,
  `mass_sync_request`, gpt-4o-mini, and all MA/HA config stay untouched.
- **Service restarts are never automatic** — any resolver restart is user-run and **requires explicit
  approval**.
- Secrets only in 0600 files; never logged/committed; secret-scan before any commit; no AI attribution;
  **commit only when asked**; do not stage unrelated files.
- The resolver source of truth is version-controlled at `docs/homebrain/mass-resolver/` (mirrors the
  host). Repo-only phases edit the mirror; deploy copies the mirror to the host (gated).

---

## Phase 1 — Repo-only design finalization / doc update  ✅ (this revision)
**Goal:** lock the v2 design as the build reference. **Location:** repo only. **Approval:** none.

- Design + plan updated to: HA-state-primary; summary-only (no `aspect`); `StatusCapability` + `CAPS`/
  `_STUBS` change; unconditional silence; `haconn` read-only seam; no-host capture replacing the MA
  probe; atomic rollback; edge/concurrency tests; raw-`media_player`-exposure rejection note.
- **Exit criteria:** both docs consistent with the seven locked decisions; no aspect references remain
  except as a documented future enhancement.
- **Rollback:** n/a (repo text). **Commit:** only when asked (docs-only, separate from unrelated dirty
  files). **No STOP** — repo-only.

---

## Phase 2 — **No-host HA attribute capture** (default) · MA WS probe = contingency only
**Goal:** confirm the exact HA attributes (and the radio-vs-track discriminator + station-name source)
**without any host access**, before coding the normalizer.

**Capture method (no SSH, no script, no host):**
- The **user** opens **Home Assistant → Developer Tools → States**, selects
  **`media_player.ceiling_speakers`**, and pastes the **sanitized** `state` + `attributes` for:
  - **local music playing**
  - **radio playing**
  - **paused** (if easy)
  - **idle / off**
- "Sanitized" = no tokens/URLs with secrets; attribute **keys + representative values** only
  (title/artist/station/content-type/volume). Paste into the design as a field-mapping table.
- From the capture, record in the design: HA-attribute → `metadata` mapping, the **discriminator rule**
  (`source = music | radio | none`), and the volume field. TDD (Phase 3) codes against these confirmed
  fields.

**Contingency (only if HA attributes are insufficient — e.g. cannot distinguish radio/track or lack a
station name):**
> ### 🔴 STOP — APPROVAL REQUIRED (MA WS fallback)
> Falling back to a **read-only MA WS probe** (and later adding `players/get`/`player_queues/get` to
> `maconn.py`) requires **explicit approval** to read MA state from the host. **Do not run an MA probe
> or add MA read methods without it.** Default path uses **no host access at all.**

**Exit criteria:** confirmed HA field mapping + discriminator recorded in the design.
**Rollback:** n/a (capture is user-pasted text; no host/HA change).

### Outcome — capture DONE (2026-06-29)
Four sanitized `media_player.ceiling_speakers` captures (radio playing, idle-after-radio, paused radio,
track playing) were reviewed; the **confirmed field mapping + discriminator are recorded in design §2**
(empirical mapping table). Key results: states seen = `playing/paused/idle`; **`media_content_type` is
`music` for both radio and track** (not a discriminator); **discriminator = `media_content_id` prefix**
(`library://radio/` vs `library://track/`, only when `state==playing`); **radio station =
`media_album_name`**; **`media_artist` may be `"[unknown]"`/intermittent → `None`**; **`idle` retains
stale `media_*`** → gate on `state`; HA has a colliding `source` attribute → normalized field renamed to
**`content_kind`**. **No host access used** (user-pasted). MA WS fallback **not** needed. Phase 3 fixtures
= these four captures.

---

## Phase 3 — Repo-only TDD for `StatusCapability`
**Goal:** failing tests first, then the pure logic, entirely in-repo against the mirror.
**Location:** repo only (`docs/homebrain/mass-resolver/`). **Approval:** none.
**Method:** TDD; stdlib `unittest` (`python tests/test_status.py` from `mass-resolver/`).

Build the **deterministic core first**:
1. **Normalizer (pure):** `normalize_status(ha_state) -> metadata` mapping the HA `state`+`attributes`
   (fields confirmed in Phase 2 / design §2) → `player_state ∈ {playing,paused,idle,off,unavailable}`,
   `content_kind ∈ {music,radio,none}` (via `media_content_id` prefix, **only when `state==playing`**;
   gated otherwise), `title` (`media_title`), `artist` (`media_artist`, **`"[unknown]"`/empty → None**),
   `station` (`media_album_name`, radio only), `album` (`media_album_name`, music only),
   `media_content_id`, `volume_level (0–1)`, `volume_percent (0–100 int, round half-up)`, `available`.
   **Stale `media_*` in `idle` is ignored** (gate on `state`); paused metadata is treated as valid.
2. **`chat_text` builder (pure):** `status_chat_text(metadata) -> str` — one self-sufficient summary
   (state + title/artist-or-station + volume; idle → "Nothing is playing right now."). **No aspect, no
   parsing.**
3. **Capability stages (mirror `MusicCapability`):** `resolve` (isolated read-only HA state read via the
   seam; no side effects), `validate` (returns `None`), `execute` (normalize → build → `cr.ok(...,
   spoken_text=None, metadata=...)`, or `cr.err(..., "unavailable"/"upstream_error", ...,
   spoken_text=None)`). HA reads go through a **mockable seam** so tests use fixtures (no live HA).

**Unit tests — fixtures from the Phase-2 capture:**

| Test (fixture = Phase-2 capture) | Asserts |
|---|---|
| music playing (Capture 4) | `ok=true`, `content_kind=music` (via `library://track/`), `title` set, `volume_percent`, summary `chat_text` |
| radio playing (Capture 1) | `ok=true`, `content_kind=radio` (via `library://radio/`), `station`=`media_album_name`, no fabricated artist |
| paused (Capture 3) | `player_state=paused`, "paused" wording, metadata treated as valid (not stale) |
| idle (Capture 2 — stale `media_*` present) | `ok=true`, `content_kind=none`, "Nothing is playing right now." (**stale fields ignored**) |
| off | `content_kind=none`; distinct `player_state=off` preserved |
| unavailable / error | seam raises / entity unavailable → `ok=false`, `error.code=unavailable`, `available=false`, `spoken_text=None` |
| **discriminator** | `media_content_id` prefix decides radio vs music; only honored when `state==playing` |
| **`[unknown]` artist** | `media_artist=="[unknown]"` (Capture 4) → `artist=None`; chat omits "by" |
| **missing/intermittent radio artist** | radio with no `media_artist` (Capture 1) → lead with station, no fabrication |
| **silence on success** | success result `spoken_text is None` |
| **silence on error** | error result `spoken_text is None` (so `announce_failures` can't make status speak) |
| null volume | `volume_level=None` handled; `volume_percent` None, no crash |
| zero volume | `0.0 → 0%` |
| near-silent volume | `0.09 → 9%` reported truthfully |
| rounding | `0.355 → 36` (round half-up; pin the rule) |
| missing station/title | empty media fields while `playing` → no fabrication |
| missing `media_content_id` while playing | `content_kind=music` if title present, else generic; no crash |

**Exit criteria:** all tests green on a 3.5-compatible interpreter; every row covered.
**Rollback:** n/a (repo). **Commit:** only when asked.

---

## Phase 4 — Resolver integration (repo)
**Goal:** wire `StatusCapability` into the live lifecycle + add the read-only HA seam.
**Location:** repo only (mirror). **Approval:** none.

- **`status.py`:** replace the legacy stub function with `class StatusCapability(capability.Capability)`
  (`name="status"`).
- **`core.py`:** add `import status`; set `CAPS["status"] = status.StatusCapability()`; **remove
  `"status"` from `_STUBS`**.
- **`haconn.py` (read-only seam):** add a small **isolated** read-only state reader — **v1 (locked):**
  an HA **REST `GET /api/states/media_player.ceiling_speakers`** helper (token as `Bearer`, fresh
  per-call, stdlib `http.client`/`urllib.request`, Python 3.5-safe). **Must not** read on the shared
  persistent event socket. No mutation, no `call_service`. (A fresh per-call HA WS `get_states` was the
  considered alternative — not used in v1.)
- **No** event adapter / legacy wrapper for status.
- Integration test (fakes for the HA read): `core.dispatch(ctx,"status",{})` → correct `CommandResult`
  (`intent=="status"`, `spoken_text is None`, full `metadata`), and **`status` no longer hits the
  `_STUBS` "not available yet" path**.

**Exit criteria:** `dispatch` returns a correct status `CommandResult` for each fixture; full suite
green; diff limited to `status.py` + `core.py` registration + the `haconn` reader + tests.
**Rollback:** n/a (repo); the **atomic 3-part revert** (restore stub, drop from `CAPS`, re-add to
`_STUBS`) + revert the `haconn` reader = `git revert` of the 4A commit. **Commit:** only when asked.

---

## Phase 5 — Host deploy gate
**Goal:** deploy the resolver change to the host and load it. **Location:** **host.** **Live phase.**

- Pre-deploy backup: copy current host `status.py`, `core.py`, `haconn.py` to `~/mass-resolver/.4abak/`
  (note the git baseline SHA).
- Deploy: copy the mirror `status.py` + `core.py` + `haconn.py` to `~/mass-resolver/`.
- **Load** requires a **resolver service restart**.

> ### 🔴 STOP — APPROVAL REQUIRED (host deploy + restart)
> Copying files and **restarting `mass-resolver`** is user-run and needs explicit approval. **Do not
> copy or restart without it.** No HA changes in this phase.

**Validation (post-deploy):** resolver healthy; existing capabilities unaffected (quick
`play`/`radio`/`find` smoke via existing paths from a captured/restored baseline); `/command` health
`200`/`401`.
**Rollback (live):** restore `~/mass-resolver/.4abak/{status.py,core.py,haconn.py}` (the **atomic
3-part** state). A **resolver restart to load the rollback requires explicit approval** (user-run).
`/command`, the event adapter, `mass_sync_request`, and the three scripts are unaffected by a
status-only revert.

---

## Phase 6 — Direct `/command` validation (no HA script, no audio)
**Goal:** prove the deployed capability returns truthful, normalized `CommandResult`s against **real HA
state** — independent of any HA script/ChatGPT. **Location:** **host** (post-deploy), read-only.

- With the user placing the speaker into each state (reuse the Phase-2 states), call `/command`
  (`intent=status`) and assert the §5 matrix: music / radio / paused / idle-off / unavailable.
- Assert `spoken_text` is `null` and **the resolver speaks 0 times** for status (success and error).
- **Concurrency / no-regression:** issue a status call **during/after** a `play` and confirm the play is
  unaffected and status returns correctly.
- Auth: `200` with `X-Resolver-Key`, `401` without.

**Exit criteria:** every matrix row passes against live HA; no TTS; no side effects; no regression.
**Rollback (live):** none needed (read-only); else fall back to the Phase-5 (approval-gated) revert.

> ### 🟡 CHECKPOINT — report Phase 6 results and stop before touching HA.

---

## Phase 7 — HA script creation gate (`script.media_status`)
**Goal:** create the brand-new `script.media_status`. **Location:** **Home Assistant.** **Live HA phase.**

- Create (not edit) `script.media_status` via `POST /api/config/script/config/media_status`:
  alias `Ceiling: Media Status (resolver)`, **no fields** (no `aspect`), and the §4 sequence
  (`rest_command` intent=status, `params:{}` → `response_variable: r` → `variables.resp` guarded
  `chat_text` → `stop` + `response_variable: resp`). **No `set_conversation_response`; no `tts.speak`.**
  Then `POST /api/services/script/reload`.

> ### 🔴 STOP — APPROVAL REQUIRED (modify Home Assistant)
> Creating a script + reloading **modifies Home Assistant** — explicit approval required. The script is
> **not exposed** to any assistant in this phase.

**Validation:** readback — alias present, **no `aspect` field**, **`set_conversation_response` absent**,
**`tts.speak` absent**, has `rest_command` + `stop`/`response_variable: resp`; confirm **NOT exposed** to
`conversation`.
**Rollback (live):** **delete** `script.media_status` + `script.reload` (brand-new → fully removed; no
existing script touched). No restart.

---

## Phase 8 — Script hard-return validation (no audio, no exposure)
**Goal:** prove the script returns `{chat_text: …}` as its service response without exposure.
**Location:** **host/HA**, controlled tests.

- WS `call_service script.media_status` with `return_response:true`, per state: assert response ≈
  `{chat_text: "<resolver chat_text>"}` and equals the Phase-6 `/command` `chat_text` for that state;
  **no playback, no TTS.**
- Exercise the `continue_on_error` fallback (simulate `/command` briefly unreachable → graceful fallback
  `chat_text`).

**Exit criteria:** return shape correct for all rows; matches `/command` ground truth; no side effects.
**Rollback (live):** delete the script (Phase 7). Resolver revert per Phase 5 if needed.

> ### 🟡 CHECKPOINT — report Phases 7–8 and stop. Capability is **validated but unexposed.**

---

## Phase 9 — ChatGPT exposure gate (separately approved)
**Goal:** expose `script.media_status` and validate end-to-end. **Location:** HA exposure +
`assistant-capabilities.md`/Instructions update.

> ### 🔴 STOP — SEPARATE APPROVAL REQUIRED (expose a new ChatGPT tool)
> Exposure is its **own** approved step. **Do not expose in the build phases.** Note: raw
> `media_player.ceiling_speakers` is **not** exposed (widens the LLM surface + re-enables broken
> built-in intents — design §7); the guarded `script.media_status` is the surface.

On approval (future):
- Expose via WS `homeassistant/expose_entity` (`assistants:["conversation"]`); add a concise **STATUS**
  line to `assistant-capabilities.md` + the OpenAI Instructions **in lockstep** (tool count 3 → 4).
- Conversational validation: the example phrases each relay the resolver's `chat_text` verbatim;
  resolver speaks **0** times; correct state reported; no fabricated station for a song.
**Rollback (live):** un-expose via `expose_entity` + revert the capabilities/Instructions edits.

---

## Approval stop-points (summary)
| Gate | Action requiring approval |
|---|---|
| **Phase 2 (contingency only)** | Run an MA WS probe / add `maconn.py` reads — **only if** HA capture is insufficient. *Default Phase 2 needs NO host access.* |
| **Phase 5 STOP** | Deploy resolver code to host **+ restart `mass-resolver`** |
| **Phase 7 STOP** | Create `script.media_status` on HA + `script.reload` |
| **Phase 9 STOP** | **Separately approve** exposing the new tool to ChatGPT |
| Phase 6 / 8 CHECKPOINT | Report + pause before advancing |

> **Net vs the original plan:** the default build has **two live gates** (Phase 5 deploy+restart,
> Phase 7 HA script) + the separate Phase 9 exposure. The host MA-probe gate is **removed** from the
> default path (no host access in Phase 2).

## Rollback summary (per live phase)
| Phase | Rollback | Restart? |
|---|---|---|
| 2 (capture) | None — user-pasted text; no host/HA change | No |
| 5 (deploy) | Restore `.4abak/{status.py,core.py,haconn.py}` — **atomic 3-part** (stub + drop `CAPS` + re-add `_STUBS`) + revert `haconn` reader | **Only with explicit approval** |
| 6 (/command) | None (read-only); else Phase-5 revert | Per Phase 5 |
| 7 (HA script) | Delete brand-new `script.media_status` + `script.reload` | No |
| 8 (validation) | Delete the script (Phase 7) | No |
| 9 (exposure) | Un-expose via `expose_entity` + revert capabilities/Instructions | No |

## Python 3.5 compatibility (carried)
No f-strings; `.format()`/`%` only. Stdlib `unittest` (no pytest); `python tests/test_status.py` from
`mass-resolver/`. No new third-party deps; the `haconn` REST reader uses stdlib `http.client`/
`urllib.request`. ASCII-only console. No HAOS-side Python in 4A (the script is YAML/JSON config).

## Out of scope (explicit)
`aspect` enum; sleep timer; shuffle/repeat/queue/transport; personal reminders/timers; any PCL work;
Inc 2 News; any YTM work; MA WS reads (contingency only, approval-gated); any change to
`play_music`/`play_radio`/`find_stations`, the event adapter, `mass_sync_request`, the agent model, or
MA/HA config beyond creating the one new (initially-unexposed) script.

## Self-review
- HA-state-primary; **no-host HA attribute capture replaces the host probe**; MA WS probe contingency &
  approval-gated ✓.
- Summary-only; **no `aspect`** enum/branches/invalid-aspect test ✓; metadata broad for future wording ✓.
- Real-code shape: `StatusCapability` + `CAPS` add + `_STUBS` removal; **atomic 3-part rollback** (+
  `haconn` reader) ✓; restart never implied automatic ✓.
- Unconditional silence (`spoken_text=None` on success **and** error) with explicit silence tests ✓.
- Source seam in `haconn.py` (isolated read-only; shared-socket hazard avoided); **no `maconn.py` reads
  in v1** ✓.
- Edge tests (null/zero/near-silent volume, rounding, missing artist/station/title, off vs idle,
  playing-but-empty) + concurrency/no-regression ✓.
- Raw `media_player` exposure rejected (noted) ✓. Keeps `script.media_status`, hard return, no event
  adapter, no change to existing scripts, no exposure before approval, Python 3.5 ✓.
- Nine phases retained; **default path has two live gates + separate exposure** (host probe gate removed).
- **No implementation performed; no host/HA changes; nothing exposed** — *plan only at authoring time
  (see Execution outcome below).*

---

## Execution outcome — Phases 1–7 DONE (2026-06-29; Inc 4A **validated-but-unexposed**)

**Phases 1–4 (repo).** `StatusCapability` (+ pure `normalize_status` / `build_chat_text`) implemented
HA-state-primary, summary-only; wired into `core.CAPS["status"]` with `"status"` removed from
`_STUBS`; read-only HA REST reader `haconn.HA.get_entity_state()` added (fresh per-call, not the shared
event socket); legacy `status()` stub removed and `test_stubs.py` updated. Full suite **160 tests OK**.
Committed `f110d67` (six files: `core.py`, `haconn.py`, `resolver.py`, `status.py`, `tests/test_status.py`,
`tests/test_stubs.py`).

**Phase 5 — host deploy (DONE).**
- Deployed the four runtime files to `~/mass-resolver/`: `core.py`, `haconn.py`, `resolver.py`,
  `status.py` (tests not deployed). Backup: **`/home/costea/mass-resolver/.inc4a-bak/20260629T200033Z/`**.
- Checksums host==local (all four); modes preserved (664 core/haconn/status, 755 resolver); host
  Python 3.5.2 `py_compile` clean; import check `status in CAPS`, `status not in _STUBS`.
- Service **restarted successfully** (user-run sudo); 0 startup tracebacks.
- `/command` auth: **401 without key / 200 with key**.
- Direct status validated against live state:
  - radio: `Playing 101 SMOOTH JAZZ at 27% volume.` — `content_kind=radio`, `spoken_text=null`.
  - music: `Playing "Zeit" by Rammstein at 27% volume.` — `content_kind=track`.
- **No speaker announcement** for status (ANNOUNCE count unchanged).
- No-regression: `music`, `radio` play, `radio` find all OK via `/command`; playback baseline restored.

**Phase 7 — HA script (DONE).**
- Created **`script.media_status`** (alias **`Ceiling: Media Status (resolver)`**, mode `single`, **no
  fields**). Sequence calls `rest_command.resolver_command` (`intent=status`, `params={}`),
  `response_variable: r`, returns `{chat_text: r.content.chat_text}` via `stop` + `response_variable: resp`.
- Structural readback: alias/mode/sequence/intent/params/`response_variable`/final-stop all correct;
  **no `tts.speak`**, **no `set_conversation_response`**, **no fields**.
- Invoked with `return_response=true` → service response exactly
  **`{chat_text: "Playing 101 SMOOTH JAZZ at 27% volume."}`**; **no speaker announcement**.
- Existing scripts **unchanged by SHA**: `play_music`, `play_radio`, `find_stations`.
- **Not exposed to ChatGPT** (no expose API called).

**Current state.** Inc 4A is **validated-but-unexposed**: the resolver capability and `script.media_status`
are live and validated, but the script is **not exposed to the conversation agent**, so **ChatGPT cannot
call it yet**. **Phase 9 exposure remains a separate explicit gate.**

**Rollback.**
- Resolver: restore the four files from `/home/costea/mass-resolver/.inc4a-bak/20260629T200033Z/`
  (atomic 3-part: stub `status.py` + drop from `CAPS` + re-add to `_STUBS`); resolver restart is
  approval-gated (user-run), never automatic.
- HA script: **delete `script.media_status` + reload scripts** (brand-new entity; no existing script
  touched). **No resolver rollback is needed for a script-only failure** (`/command` is independent and
  was validated in Phase 5).

**Phase 9 — exposure §2a–§2b DONE (2026-06-29).**
- **§2a:** added a `description` to `script.media_status` (touched only the new script); structural
  readback unchanged (alias `Ceiling: Media Status (resolver)`, mode `single`, `rest_command` /
  `intent=status` / `params={}` / `stop`+`response_variable: resp`, **no `tts.speak`**, **no
  `set_conversation_response`**, no fields, `description_matches`); hard return `{chat_text}` confirmed;
  silent (ANNOUNCE count unchanged).
- **§2b:** exposed only `script.media_status` to the `conversation` assistant.
  **Exposure delta: baseline 11 → 12; added `script.media_status`; removed none; changed none.**
  `play_music`/`play_radio`/`find_stations` remain exposed; `media_player.ceiling_speakers` and
  MA/`media_player.*` remain unexposed.
- **§3 (docs) — DONE in repo (uncommitted):** `assistant-capabilities.md` (table + active STATUS note +
  routing rule + prompt block incl. CHECKING WHAT'S PLAYING and the verbatim-relay line; corrected
  `ceiling_play_radio` as not-exposed), `CHANGELOG.md`, this plan.
- **§3 (Instructions) DONE** — append-only STATUS additions (WHAT YOU CAN DO bullet + CHECKING WHAT'S
  PLAYING block) pasted in the HA UI; the verbatim-relay RULES line preserved; model settings unchanged.
- **§4 (conversational validation) DONE (2026-06-29):** all four status prompts via
  `conversation.openai_conversation` called `script.media_status` and relayed the real now-playing state
  (exact volume `27%` present in every reply — unobtainable without the tool; **no fabrication**);
  **silent** (ANNOUNCE 65→65 across the status prompts). No-regression: `play jazz radio`,
  `play Rammstein`, `find jazz stations` all routed and executed (resolver log: RADIO PLAYING / Rammstein
  PLAYING / mode=find). Exposure sanity: **exactly 12** (baseline 11 + `script.media_status`), no
  `media_player`/MA exposed. Baseline restored (idle). *Note:* ChatGPT sometimes lightly re-cases/rephrases
  the relayed text (e.g. "101 Smooth Jazz") — substance correct (same accepted cosmetic behavior as F1-R
  radio). **Inc 4A Phase 9 COMPLETE — `script.media_status` live and conversationally validated.**
