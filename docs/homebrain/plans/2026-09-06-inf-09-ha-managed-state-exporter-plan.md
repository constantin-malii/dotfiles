# INF-09 — Home Assistant Managed-State Exporter (read-only) — Implementation Plan

> **Plan only — do NOT implement. Stop here for review.**
> No live-system access was used to write this plan. Every endpoint below was observed earlier on
> **2026-09-06** during ordinary operational work and is recorded as *observed*, not *verified for
> this purpose* — §11 lists exactly what still needs a read-only probe before coding.
> Prerequisite, not replaced by this work: **off-host encrypted HA backups** (in progress — the NAS
> agent). A managed-state export is change control, **not** disaster recovery.

## Why

The resolver is version-controlled and provably in sync with the host. The Home Assistant half of
HomeBrain is **not tracked at all**. On 2026-09-06 alone, four live-only changes were made — the
pause/stop routing, `finished_speaking_detection`, the `play_radio` tool schema, and the
`play_favorite` sentence trigger — and the `CHANGELOG.md` prose is their only record.

This is not inert configuration. **`script.play_radio`'s `fields` descriptions are the LLM's tool
schema**: editing that text changes model behaviour, which is exactly what happened twice that day.
That is source code living in a database with no history, no diff and no review.

## Non-goals for this increment

- **No apply, import, restore or mutation of any kind.** Export only.
- No automated HA changes; no change to resolver deployment; no live access during planning.
- **This does not replace encrypted off-host HA backups** and must never be described as doing so.
  It captures a hand-picked app-layer surface, not the instance.

## Not a duplicate of `tools/snapshot.py`

`snapshot.py` is a **runtime media-state** probe: host-run, human-readable, prints HA player state
and the MA queue for a moment in time. This exporter captures **configuration/managed state** as
canonical machine-readable files for Git. Different axis, no overlap. The one thing INF-09 should
copy from it is its shape: host-resident, stdlib-only, read-only, no secrets printed, 3.5-safe.

## 1. Managed resources and their data sources

| Resource | Source | Interface | Status |
|---|---|---|---|
| HA version | `GET /api/config` → `version` | REST | **Public** |
| Script inventory | `GET /api/states` → `script.*` (object_id) | REST | **Public** |
| Script config *(incl. `fields` tool schema)* | `GET /api/config/script/config/<object_id>` | REST | **Undocumented / version-coupled** |
| Automation inventory | `GET /api/states` → `automation.*` → `attributes.id` | REST | **Public** |
| Automation config *(incl. sentence triggers)* | `GET /api/config/automation/config/<id>` | REST | **Undocumented / version-coupled** |
| Assist pipelines | WS `assist_pipeline/pipeline/list` | WebSocket | **Undocumented** |
| Satellite pipeline assignment | `GET /api/states/select.respeaker_*_assistant[_2]` | REST | **Public** |
| Satellite settings (`finished_speaking_detection`, wake words, sensitivity) | `GET /api/states/select.respeaker_*` | REST | **Public** |
| Conversation exposure | WS `homeassistant/expose_entity/list` | WebSocket | **Undocumented** *(already the established convention — `assistant-capabilities.md` §NL-02 step 5)* |

**Two of the highest-value resources sit behind undocumented frontend routes.** They are not in HA's
public REST reference; they back the UI editors and are coupled to the frontend's shape. Treat them
as version-pinned: probe before use, fail closed on an unexpected shape, and record the HA version
that produced every export.

**Transport:** reuse `mass-resolver/wsutil.py` — a stdlib-only raw WebSocket client already used by
`maconn`. **No `aiohttp`, no new dependency**; the whole resolver is stdlib-only and this stays so.

## 2. Capability and schema probes (fail closed)

`--probe-only` runs these and writes nothing. A full export runs them **first** and aborts before any
capture if any fails.

1. **Auth/transport** — REST `GET /api/config` returns 200; WS authenticates. Failure → exit 2.
2. **Version pin** — compare `version` against the manifest's `ha_version_expected`. A mismatch is a
   **warning** recorded in the summary, not a failure; combined with a shape probe failure it is the
   explanation.
3. **Capability probe, per endpoint** — each source is called once for one known resource and must
   return the expected top-level type (object / list). A 404, a 401, or an HTML body → exit 3.
4. **Schema probe, per resource type** — every key in the response is checked against that type's
   positive allowlist (§4). Any unknown key → exit 4, **before** anything is written.

Fail-closed means exit non-zero **and leave the output tree untouched**. Never a partial export.

## 3. Raw vs sanitized — strict separation

| | Raw snapshot | Canonical managed state |
|---|---|---|
| Content | Verbatim API responses, unfiltered | Allowlisted, normalized, secret-scanned |
| Location | `~/ha-state/raw/<UTC-timestamp>/` on the **host** | `docs/homebrain/ha/` in Git |
| Permissions | dir `0700`, files `0600` | normal repo files |
| Git | **Never.** Not in the repo, not copied to the dev machine | Committed after human review |
| Purpose | Rollback reference + post-hoc forensics | Diffable change control |

Raw never leaves the host. Only the sanitized tree is transferred, and only after review. Raw
retention is bounded (keep N most recent, default 10) so it cannot grow without limit.

## 4. Normalization rules

**Positive allowlists per resource type.** Anything not named is dropped. Unknown keys fail closed by
default (exit 4); with `--allow-unknown-fields` they are omitted from canonical output **and
enumerated in the run summary and the raw snapshot**, so the omission is visible rather than silent.

- **Script** — `alias`, `description`, `mode`, `icon`, `fields` (per field: `name`, `description`,
  `required`, `selector`, `example`, `default`), `sequence`.
- **Automation** — `id`, `alias`, `description`, `mode`, `triggers`/`trigger`,
  `conditions`/`condition`, `actions`/`action`. *(Both singular and plural spellings are accepted;
  2026.6.4 was observed emitting the plural forms.)*
- **Satellite select entity** — `entity_id`, `state`, `attributes.options`,
  `attributes.friendly_name`. **Dropped:** `last_changed`, `last_updated`, `last_reported`,
  `context`. These are pure runtime churn and would produce a diff on every single export.
- **Pipeline** — `id`, `name`, `conversation_engine`, `conversation_language`, `stt_engine`,
  `stt_language`, `tts_engine`, `tts_voice`, `tts_language`, `wake_word_entity`, `wake_word_id`,
  `prefer_local_intents`; plus the list's `preferred_pipeline`.
- **Exposure** — `entity_id` → per-assistant exposure flags.

**Ordering — the load-bearing rule.** Mapping keys are sorted. **Lists are only sorted when their
order carries no meaning.** A script's `sequence`, an automation's `triggers`/`actions`, and the
branches of a `choose` are *behaviour*: reordering them changes what the system does, and a sorted
diff would be both wrong and unreviewable. Sort only inventory-like collections (exposure entities,
select `options`, the file-level resource index). This distinction is per-field and explicit in code,
not inferred.

**Encoding.** UTF-8, `ensure_ascii=False`, LF newlines, two-space indent, trailing newline. Station
and entity names are Cyrillic in this system; escaping them to `\uXXXX` would make every diff
unreadable.

**`.gitattributes` must gain `*.json text eol=lf` — verified, not conditional.** The repo's
`.gitattributes` currently normalizes only `shell/*` and `*.sh`; there is **no rule for `.json` or
`.py`**. Files authored from this Windows checkout therefore acquire CRLF, which is precisely why
every repo↔host comparison in this system has to pipe through `tr -d '\r'` before hashing. Without
the rule, the exporter's own output would be CRLF locally and LF on the host, and the drift detection
this whole increment exists to provide would report false differences against itself.

> **Separate, larger observation — not part of this increment.** The same missing rule applies to
> `*.py`, and is the root cause of the CRLF hazard documented for resolver deploys. Adding
> `*.py text eol=lf` would remove that hazard permanently, but it renormalizes every resolver module
> (a large diff plus a full host re-deploy), so it is a deliberate decision to take on its own, not a
> side effect of this plan.

**No timestamps in canonical files.** An `exported_at` field would churn every export even when
nothing changed, destroying the signal the files exist to provide. Timestamps live in the raw
snapshot. `meta.json` records `ha_version` and `exporter_version` only.

**Secret detection**, run on the rendered sanitized bytes before anything is written:

1. **Literal match** against the actual on-host secrets (`.ha_token`, `.http_secret`, `.ma_token`),
   read into memory and **never printed or logged**. This is the strongest check available and is
   possible only because the exporter runs on the host.
2. **Pattern match** — `Bearer\s+\S+`, JWT shape, `password`/`api_key`/`token`/`secret`/`cookie` as a
   key with a non-empty scalar value, and long high-entropy strings (≥20 chars of hex/base64).
3. Any hit → **exit 6, nothing written**, and the summary names the resource and JSON path but
   **never the value**.

## 5. Repository layout, manifest, CLI, exit codes

```
docs/homebrain/ha/
  MANIFEST.json              # what we claim to own (hand-maintained, reviewed)
  meta.json                  # ha_version, exporter_version
  scripts/<object_id>.json
  automations/<automation_id>.json
  pipelines/<pipeline_id>.json
  satellite/<entity_id>.json
  exposure/conversation.json
docs/homebrain/mass-resolver/tools/ha_export.py
docs/homebrain/mass-resolver/tests/test_ha_export.py
docs/homebrain/mass-resolver/tests/fixtures/ha/…
docs/homebrain/runbooks/ha-managed-state-export.md
```

`MANIFEST.json` is the managed-resource declaration — the analogue of a deploy manifest. It names
`ha_version_expected` and the exact scripts, automations, pipelines, satellite entities and exposure
assistants under change control. Resources present in HA but absent from the manifest are
**unmanaged**: reported in the summary, never exported. `--strict-inventory` turns that into exit 5,
for the day we want the manifest to be exhaustive.

```
python3 ha_export.py --manifest <path> --out <dir> [--raw-dir <dir>]
                     [--probe-only] [--allow-unknown-fields] [--strict-inventory]
                     [--keep-raw N] [--summary-json]
```

| Exit | Meaning |
|---|---|
| 0 | Success — canonical tree written atomically |
| 1 | Usage / environment error (bad args, unreadable token file) |
| 2 | Transport or auth failure — HA unreachable |
| 3 | Capability probe failed — an endpoint is gone or unsupported |
| 4 | Schema probe failed — unknown or changed fields |
| 5 | Managed resource missing (or, with `--strict-inventory`, an unmanaged resource exists) |
| 6 | Secret detected — nothing written |
| 7 | Partial API failure — some resources failed; nothing written |

**Atomicity:** everything is built in a temp dir and moved into `--out` only when every resource
succeeds and the secret scan passes. There is no such thing as a half-written export.

## 6. Approaches considered

**A. Host-resident exporter, stdlib only, two outputs. ← recommended**
Lives in `mass-resolver/tools/`, runs on the host where the tokens already are, reuses `wsutil.py`,
writes raw to `~/ha-state/raw/` and the sanitized tree to a staging dir that is then reviewed and
copied into the repo.
*Pros:* tokens never leave the host; literal-secret matching is possible; matches `snapshot.py`
convention exactly; zero new dependencies; the tests ride the existing suite on **both** Python
3.12 (dev) and 3.5.2 (host).
*Cons:* it is host-deployed code, so it inherits the deploy/drift problem — it must be added to the
deploy manifest under the separate manifest-deploy work, and `tools/` is not currently deployed at
all.

**B. Dev-machine exporter over an SSH tunnel.**
Runs on the dev machine's Python 3.12 against a forwarded HA port.
*Pros:* modern Python, no host deployment, fastest iteration.
*Cons:* **the HA token must travel to the dev machine** — a new secret distribution path, for a
convenience gain. Literal-secret scanning weakens. Rejected on that alone.

**C. Thin host capture + local normalizer.**
Host does a dumb raw JSON dump; all allowlisting, normalization and scanning happen in a repo-side
module.
*Pros:* the complex, frequently-changing half lives where the tests and modern Python are; the host
component is tiny and rarely changes, so host drift matters less.
*Cons:* **raw, unsanitized, possibly secret-bearing JSON must cross to the dev machine** to be
normalized — directly contrary to §3. Fixable by scanning on the host first, but then the host
component is no longer thin and it collapses into A with extra moving parts.

**Recommendation: A** — smallest robust option. C's separation of concerns is genuinely attractive
and worth revisiting if the normalization logic grows, but it inverts the security property that
matters most here.

## 7. Fixture-based tests (no HA connection)

`tests/test_ha_export.py`, fixtures under `tests/fixtures/ha/`. Every test drives the pure
normalize/scan/render functions over recorded JSON — the network layer is injected, never exercised.
Runs in the existing suite on both Pythons.

- **Deterministic output** — normalize the same fixture twice; assert byte-identical, including key
  order, indentation, and a run with `PYTHONHASHSEED` varied.
- **Redaction / secret scan** — a fixture with a bearer token in a script `sequence` → exit 6, output
  dir untouched, message names the JSON path and **not** the value.
- **Unknown / changed schema** — a fixture with an added key → exit 4 by default; with
  `--allow-unknown-fields`, key omitted from output *and* listed in the summary.
- **Missing resource** — manifest names an automation HA does not return → exit 5.
- **Partial API failure** — one source raises mid-run → exit 7, **nothing written** (asserts
  atomicity, not just the code).
- **Stable normalization** — Cyrillic names survive unescaped; runtime metadata (`last_changed`,
  `context`) is stripped; `sequence` and `choose` order is **preserved**; `options` and the exposure
  list are **sorted**. The order-preservation case is the one that would silently corrupt behaviour,
  so it gets an explicit test per resource type.

## 8. First live export — approval-gated

1. Deploy `ha_export.py` to the host (`tools/` is not currently deployed). **Gate: approval.**
2. `--probe-only`. Read-only, writes nothing. Confirms every endpoint exists and every shape is
   known on 2026.6.4. **If this fails, stop** — the plan's §11 assumptions were wrong and the
   allowlists need revising before anything is captured.
3. Full export to a scratch dir **outside the repo**, raw to `~/ha-state/raw/`.
4. **Review the sanitized output before it enters the repo** — read every file, confirm no secret and
   no runtime noise, confirm the tool schemas are captured verbatim.
5. Copy into `docs/homebrain/ha/`, `git add -N`, review `git diff` in full, then commit.
6. Never commit raw. Never commit an export that has not been read.

The first export establishes the baseline, so it is the one that most deserves a slow read: every
subsequent diff is only as trustworthy as this file set.

## 9. Operational documentation (deliverable)

`runbooks/ha-managed-state-export.md`, in the numbered read-only/gated style of the existing
runbooks, covering: what is captured and what is deliberately **not** (helper entities, dashboards,
integrations/config entries, `.storage` internals, secrets, and **the instance itself — that is what
backups are for**); how to run a probe and an export; how to read a diff (a `sequence` change is
behaviour, a `state` change on a select is a setting, an exposure change is a security-relevant
event); and what to do when a probe fails after an HA upgrade. Plus a pointer from `ONBOARDING.md`
§14 "Where things live".

## 10. Deployment / gating summary

| Step | Kind | Gate |
|---|---|---|
| Write exporter + tests + fixtures | repo-code | none (tests are offline) |
| Deploy `ha_export.py` to host | host copy | **approval** |
| `--probe-only` | read-only | **approval** (first run) |
| First full export | read-only write to scratch | **approval** |
| Commit sanitized baseline | repo | **human review of every file** |

Nothing in this increment writes to Home Assistant. There is no restart, no reload, no exposure
change, and no resolver deployment change.

## 11. Assumptions requiring a live read-only probe

Each was **observed on 2026-09-06** in passing, not verified as a contract. `--probe-only` exists to
turn each into a checked fact before any code depends on it.

1. `/api/config/script/config/<object_id>` is keyed by **object_id** (`play_radio`), while
   `/api/config/automation/config/<id>` is keyed by the automation's **`attributes.id`**
   (`voice_ceiling_speakers`). Two different identifier schemes — easy to get wrong.
2. `assist_pipeline/pipeline/list` field names, and whether it returns `preferred_pipeline`. The
   fields listed in §4 are inferred from a partial print and are **not** confirmed complete.
3. `homeassistant/expose_entity/list` exists and its response shape on 2026.6.4. It is cited in
   `assistant-capabilities.md` but was not run during this session.
4. Whether automations/scripts return singular or plural `trigger(s)`/`action(s)` **consistently**;
   the plural form was observed once.
5. Whether **any** managed script or automation currently embeds a secret. If one does, the first
   export exits 6 and the resource needs restructuring before it can ever be tracked.
6. Whether the satellite `select.*` entity ids are stable across a firmware or integration update —
   they are the filenames.
7. Total sanitized output size, to confirm this stays a reviewable diff rather than a dump.

## 12. Self-review

- **Biggest risk:** the two undocumented routes. Mitigated by fail-closed probes and a recorded
  version, but an HA upgrade *will* eventually break this, and the correct response is to fix the
  allowlist deliberately — never to add a permissive fallback that silently exports a shape nobody
  reviewed.
- **Second risk:** list ordering. Sorting a `sequence` would produce a clean-looking diff that
  encodes a behavioural change. This is called out in §4 and gets dedicated tests in §7 because it is
  the failure that would be hardest to notice in review.
- **Scope honesty:** this tracks a hand-picked surface. Everything outside `MANIFEST.json` remains
  untracked, and the runbook must say so plainly rather than implying HA is "in Git".
- **Not disaster recovery.** Stated three times on purpose.

## 13. Proposed BACKLOG note (not applied — `BACKLOG.md` is out of scope for this branch)

> **`INF-09` HA managed-state exporter (read-only).** Plan ready
> (`plans/2026-09-06-inf-09-ha-managed-state-exporter-plan.md`). Depends on off-host HA backups being
> configured first (disaster recovery is the prerequisite, not the substitute). Deliverables:
> `tools/ha_export.py`, fixture tests, `docs/homebrain/ha/` baseline, and
> `runbooks/ha-managed-state-export.md`. Export only — no apply path in this increment.
