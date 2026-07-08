# DV-01 / DV-02 / HA-06 — Household Read-Models — Implementation Plan

> **Plan only — do NOT implement. Stop at each marked gate for explicit approval.**
> Parent designs (delivered, on `main`): [HA-06 device-health](../2026-07-06-ha-06-device-health-readmodel-design.md) ·
> [DV-01/DV-02 status read-models](../2026-07-06-dv-01-02-household-status-readmodels-design.md) ·
> inventory [ha-device-inventory.md](../ha-device-inventory.md) (HA-01).
> Reuses the **Inc 4A `status` / F1-R hard-return** pattern ([plan](2026-06-29-inc4a-status-now-playing.md),
> ONBOARDING). Branch: **`homebrain/dv-ha06-readmodels`** (bundles the coupled cluster per approval).
> BACKLOG live gate (§10) currently **FREE**.

## Scope (locked with approval)
Build the **coupled read-model cluster** as one increment on one branch:
- **HA-06** — the *supplier*: a pure device-**health** model (`health.py`) turning HA state → health records.
- **DV-02** — *needs-attention*: a resolver read capability consuming HA-06 → ranked "what needs attention".
- **DV-01** — *home status*: a resolver read capability composing now-playing + presence + weather, with
  honest **not-observable** flags.

All three are **read-only** (no control, no state change, no side effects), reuse the
`resolve→validate→execute→CommandResult` lifecycle, and are surfaced (later, gated) as **hard tool
returns** via `stop`+`response_variable` — exactly like `script.media_status`/`script.news`.

## Global constraints (binding — every phase inherits)
- **Python 3.5.2-safe**; stdlib only (no new deps); stdlib `unittest` (no pytest); ASCII-only console.
- **Read-only against HA** — no playback/control/config writes; **no TTS** (silent, `spoken_text=None`,
  like `status`). No `set_conversation_response`.
- Reuse the live `/command` adapter (`http_server` routes any registered intent — **no adapter change**),
  the `CommandResult` contract, and the F1-R hard-return script shape.
- **Honest reporting (designs §2/§5):** Present / Absent / Unknown — report only observable facts; a
  category with **no entities** is explicitly **not observable**, never "healthy"/"all clear". Carry
  `observable` flags so DV can say *"nothing observable needs attention"* truthfully.
- **HA-06 never masks the SA safety path** — SA remains the authoritative life-safety FAULT owner; HA-06
  is general/property health only.
- **House-wide only** (no room-scoping until the area map is populated — HA-01 §4).
- **One live gate at a time** (BACKLOG §10); all host/HA/exposure steps **approval-gated**. Config-driven
  thresholds (no magic numbers in code). Secrets only in 0600 files; never log the HA token;
  secret-scan before commits; no AI attribution; `CHANGELOG`/`BACKLOG` edited at merge (§9), not mid-branch.

## New/changed code (target shape)
- **`haconn.py`** — add read-only **`get_all_states()`** → REST `GET /api/states` (fresh per-call HTTP,
  isolated from the shared event socket; `Bearer` token; never logged). Refactor to share a helper with
  the existing `get_entity_state()`.
- **`health.py` (HA-06, new, pure):** `health_records(states, cfg) -> [ {entity_id,kind,status,severity,
  value?,since?,observable} ]` implementing design §3 detection (battery / availability / staleness /
  update / backup), the **exclusion list** (notify/stt/MA favorite buttons → `unknown_expected`,
  severity none), and `observable` flags for absent categories. No I/O.
- **`needs_attention.py` (DV-02, new):** `NeedsAttentionCapability` — reads states (seam) → `health_records`
  → rank (safety>offline>battery/backup>updates) → `chat_text` ("N things need attention: …" or the honest
  "Nothing needs attention right now." after actually checking; qualified by observability).
- **`home_status.py` (DV-01, new):** `HomeStatusCapability` — composes now-playing (reuse
  `status.normalize_status`), presence (`person`/`device_tracker`), weather (`weather.forecast_home`),
  sun, and an explicit **not-observable** list (doors/windows/lights/climate absent) → `chat_text`.
- **`core.py`** — register `CAPS["home_status"]` and `CAPS["needs_attention"]` (intent names — Q1).
- **`config.json` / `config.py`** — add health thresholds + exclusions:
  `battery_warn_pct` (30), `battery_crit_pct` (15), `backup_stale_days` (e.g. 3), per-kind
  `staleness_max`, and `health_exclude` (patterns for legitimately-stateless entities). Tunable, no code.
- **Tests:** `tests/test_health.py`, `tests/test_needs_attention.py`, `tests/test_home_status.py`
  (+ a `get_all_states` test against a localhost stub, like the Inc 4A `haconn` REST test).

---

## Phase 1 — Plan finalization (repo-only)  ✅ (this doc)
No gate. Exit: designs' next-actions realized as this plan; open questions (below) resolved with you.

## Phase 2 — Read-only HA field probe (host, gated) — confirm state shapes before coding
> ### 🔴 STOP — APPROVAL REQUIRED (read-only host)
Confirm the **current** live shapes the read-models parse, via a **read-only** `GET /api/states`
(fresh per-call; no changes): battery `device_class` + `%`, `update` entity states, backup sensor
names/attrs, `person`/`device_tracker` states, media_player states incl. the **offline soundbar**, and
the stateless-`unknown` set to exclude. **Fallback:** HA-01 inventory (`ha-device-inventory.md` §7) is the
offline source of truth if you'd rather skip a live probe. Output: a field-mapping note appended to the
HA-06 design; TDD fixtures derived from it. **No writes, no restart.**

## Phase 3 — Repo TDD (no gate)
TDD each pure layer first, then the capabilities (HA reads behind a **mockable seam**; fixtures from
Phase 2 / HA-01):
1. **`health.py`** — battery ok/low/critical + null; **offline-as-fault** (soundbar unavailable);
   **exclusion** of notify/stt/MA buttons (`unknown_expected`, severity none); `update` on→info; backup
   stale/failed; `observable=false` for absent categories.
2. **DV-02** — ranking order; "nothing needs attention" only after checking observable set (never implies
   unobservable is fine); silent (`spoken_text=None`); full `CommandResult` shape.
3. **DV-01** — composes media+presence+weather+sun; explicitly lists **not-observable** (doors/windows/
   lights/climate); honest wording; silent.
4. **`get_all_states()`** — localhost-stub test (returns states list; sends `Bearer`; raises on non-200).
Exit: `python -m unittest discover -s tests` green (incl. all new tests); Python-3.5-safe.

## Phase 4 — Resolver integration (repo, no gate)
Wire `core.CAPS["home_status"]`/`["needs_attention"]`; `capability.run` integration tests
(`intent` correct, `spoken_text is None`, `CommandResult` well-formed). Diff limited to the new modules +
`core.py` + `haconn.py` + `config.py`/`config.json` + tests.

## Phase 5 — Host deploy gate (host) — **claims the live gate (§10)**
> ### 🔴 STOP — APPROVAL REQUIRED (deploy + restart)
Backup live files to `~/mass-resolver/.dvbak/<ts>/`; deploy changed resolver files (`haconn.py`,
`health.py`, `needs_attention.py`, `home_status.py`, `core.py`, `config.py`, `config.json`); host
`py_compile` + import check (`home_status`/`needs_attention` in `CAPS`); **user-run restart**. Verify
service active, 0 tracebacks, `/command` 401/200, existing intents (music/radio/news/status/find)
no-regression. **Restart never automatic.**

## Phase 6 — Direct `/command` validation (host, read-only after deploy)
`intent=needs_attention` and `intent=home_status` against live HA: honest output (e.g. "soundbar offline"
appears; low-battery phones listed by threshold; "not observable" for doors/lights/climate); `spoken_text`
null + **0 announcements**; no side effects; matches HA-01 reality. 🟡 checkpoint + report.

## Phase 7 — HA scripts creation gate (Home Assistant)
> ### 🔴 STOP — APPROVAL REQUIRED (create scripts + reload)
Create **`script.home_status`** and **`script.needs_attention`** (aliases TBD Q1; mode single; **no
fields**; hard return `{chat_text}` via `stop`+`response_variable`; **no `tts.speak`**, **no
`set_conversation_response`**). Structural readback; confirm **not exposed** yet. No existing script edited.

## Phase 8 — Script hard-return validation (host/HA, no exposure)
`return_response=true` for each → exactly `{chat_text}`, matching `/command`; no playback/TTS. 🟡 checkpoint.

## Phase 9 — Exposure gate (separately approved) — per the NL-02 lockstep checklist
> ### 🔴 STOP — SEPARATE APPROVAL REQUIRED (expose new tools)
Expose **only** the two scripts to `conversation` (`homeassistant/expose_entity`) — exposed set
**13 → 15**, delta = the two DV scripts, no `media_player`/MA leak. Update the **live Instructions** +
`assistant-capabilities.md` (table + routing + prompt block) **in lockstep** (NL-02 §checklist).
Conversational validation via `conversation.openai_conversation`: "what's on / what's the status of the
house?" → `home_status`; "what needs attention / anything wrong?" → `needs_attention`; tool actually
called, relays `chat_text`, no fabrication, silent; no-regression of the other tools. Baseline restored.

## Gate register / rollback (per live phase)
| Gate | Approval | Rollback |
|---|---|---|
| Phase 2 probe | read-only host | none (delete scratch note) |
| Phase 5 deploy | deploy + restart | restore `~/mass-resolver/.dvbak/<ts>/` + gated restart |
| Phase 7 scripts | create + reload | delete both scripts + reload (brand-new; no existing script touched) |
| Phase 9 exposure | **separate** | un-expose via `expose_entity` + revert Instructions/`assistant-capabilities.md` |
- Repo phases: `git revert` on the branch. **No SA path touched.** Resolver rollback only if `/command`
  itself breaks (independent of exposure).

## Tests to include (summary)
health: battery ok/low/crit/null · offline-as-fault (soundbar) · exclusion (notify/stt/MA buttons) ·
update-available · backup stale/failed · observable=false (absent categories). DV-02: ranking; honest
empty; silence; shape. DV-01: compose media+presence+weather+sun; not-observable list; honest wording;
silence. haconn: `get_all_states` stub (Bearer sent, non-200 raises). Plus full-suite no-regression.

## Out of scope (explicit)
Control/actions (HA-02/03/NL-01); room-scoping (area map — HA-01 §4); DV-03 dashboards; DV-04 energy;
SA supervision path (HA-06 never masks it); any change to existing scripts/intents; model change.

## Open questions (resolve before Phase 3)
1. **Intent + script + tool names:** `home_status` (DV-01) + `needs_attention` (DV-02) — OK? Script
   aliases e.g. `Ceiling: Home Status (resolver)` / `Ceiling: Needs Attention (resolver)`?
2. **One tool or two at exposure?** Two distinct questions ("what's on" vs "what needs attention") → I
   recommend **two** tools (13→15). Acceptable, or prefer one combined "household status" tool w/ a mode?
3. **Config thresholds:** `battery_warn_pct=30`, `battery_crit_pct=15`, `backup_stale_days=3`, and the
   `health_exclude` patterns (notify.\*, stt.\*, MA favorite buttons) — accept these defaults?
4. **Phase 2:** run the gated read-only `/api/states` probe, or build against the HA-01 inventory offline?
5. **Silence:** DV read-models silent by default (`spoken_text=None`, like `status`) — confirmed?

## Self-review
- Read-only cluster (HA-06 supplier + DV-02 + DV-01) reusing lifecycle + `CommandResult` + F1-R ✓;
  new multi-entity read seam `get_all_states` isolated/Bearer/never-logged ✓; config-driven thresholds ✓;
  honest Present/Absent/Unknown + `observable` flags ✓; SA path untouched ✓; house-wide (area-map gap) ✓.
- Phased with gates mirroring Inc 4A: probe (read-only) → repo TDD/integration → deploy → `/command` →
  scripts → validation → **separate** exposure; one live gate at a time; per-phase rollback ✓.
- Python 3.5-safe; no new deps; secrets/commit/lock discipline (§9) ✓.
- **No implementation performed — plan only.** Awaiting answers to the 5 open questions + your go.
