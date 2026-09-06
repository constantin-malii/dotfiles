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
| Purpose | **Forensic / source snapshot** — the unfiltered bytes a canonical file was derived from | Diffable change control |

Raw never leaves the host. Only the sanitized tree is transferred, and only after review. Raw
retention is bounded (keep N most recent, default 10) so it cannot grow without limit.

## 4. Normalization rules

**Two tiers, because "allowlist everything" and "capture behaviour losslessly" cannot both be true.**
HA's action grammar is open-ended and extends every release; a fixed exhaustive key allowlist over
`sequence` or `selector` would either reject valid automations or silently discard behaviour. Both
outcomes are unacceptable, so the boundary is explicit:

| Tier | What | Rule |
|---|---|---|
| **Envelope** | The resource's own top-level keys, and the metadata keys of each `fields.<name>` | **Strict positive allowlist.** An unknown key is a fail-closed error (exit 4). |
| **Behavioural subtree** | `sequence`, `triggers`/`trigger`, `conditions`/`condition`, `actions`/`action`, every `choose` branch, `selector`, and any service `data` within them | **Preserved losslessly.** No allowlist, nothing dropped, arbitrary nesting accepted. |

Inside a preserved subtree: **mapping keys are sorted** (JSON/YAML object key order is not semantic
in HA, so sorting is safe and makes diffs stable), and **list order is preserved verbatim** (it *is*
semantic — see the ordering rule below). Secret scanning traverses the **entire** preserved subtree,
not just the envelope, so losslessness never becomes a leak path.

This is why there is **no `--allow-unknown-fields` flag**. With behavioural subtrees lossless, an
unknown key can only appear on an envelope — a small, stable, well-understood surface where a new key
genuinely means HA changed something we should look at. Silently omitting it and noting it in a
summary would make the export *incomplete while reporting success*, which is precisely the property
fail-closed exists to prevent. An unknown envelope key requires a human to inspect it and update the
allowlist in code. Given that the two most valuable endpoints are undocumented, that is the whole
point, not an inconvenience.

- **Script** — envelope: `alias`, `description`, `mode`, `icon`, `fields`; per field: `name`,
  `description`, `required`, `example`, `default`. Subtrees (lossless): `sequence`, and each field's
  `selector`.
- **Automation** — envelope: `id`, `alias`, `description`, `mode`. Subtrees (lossless):
  `triggers`/`trigger`, `conditions`/`condition`, `actions`/`action`. *(Both singular and plural
  spellings are accepted; 2026.6.4 was observed emitting the plural forms.)*
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

**`.gitattributes` must gain `docs/homebrain/ha/**/*.json text eol=lf` — verified, not conditional,
and deliberately scoped.** The repo's `.gitattributes` currently normalizes only `shell/*` and
`*.sh`; there is **no rule for `.json` or `.py`**. Files authored from this Windows checkout
therefore acquire CRLF, which is precisely why every repo↔host comparison in this system has to pipe
through `tr -d '\r'` before hashing. Without the rule, the exporter's own output would be CRLF
locally and LF on the host, and the drift detection this whole increment exists to provide would
report false differences against itself.

The rule is scoped to the export directory rather than a global `*.json` **on purpose**: a global
rule would also change the working-tree line endings of `mass-resolver/radio.json`, `config.json` and
`news.json`, producing an unrelated renormalization diff and a host re-deploy inside an increment
that is supposed to touch nothing live.

> **Separate, larger observation — not part of this increment.** The same missing rule applies to
> `*.py`, and is the root cause of the CRLF hazard documented for resolver deploys. Adding
> `*.py text eol=lf` would remove that hazard permanently, but it renormalizes every resolver module
> (a large diff plus a full host re-deploy), so it is a deliberate decision to take on its own, not a
> side effect of this plan.

**No timestamps in canonical files.** An `exported_at` field would churn every export even when
nothing changed, destroying the signal the files exist to provide. Timestamps live in the raw
snapshot. `meta.json` records `ha_version` and `exporter_version` only.

**Secret detection — path-aware, not entropy-based.** A blanket "≥20 chars of hex/base64 is a
secret" rule is unusable here and would fire on real data on the first run: Assist pipeline IDs are
**ULIDs** (`01kxygpr39jas5hgsf28cph108`, 26 chars, alphanumeric), RadioBrowser station IDs are
**UUIDs**, and device/registry identifiers look the same. An export that cannot capture a pipeline ID
captures nothing useful.

Detection runs over the **complete preserved payload** — envelope *and* every behavioural subtree —
before anything is written, in this order:

1. **Literal match** against the actual on-host secrets (`.ha_token`, `.http_secret`, `.ma_token`),
   read into memory and **never printed or logged**. The strongest check available, and possible only
   because the exporter runs on the host. No exemption can suppress this rule.
2. **Sensitive key names** — a mapping key matching
   `password|passwd|token|api_?key|secret|cookie|authorization|credential|private_key|client_secret`
   with a non-empty scalar value.
3. **Value shapes that are secrets regardless of key** — `Bearer\s+\S+`, JWT
   (`eyJ`-prefixed, three dot-separated base64url segments), PEM `-----BEGIN … PRIVATE KEY-----`, and
   credentials embedded in a URL (`scheme://user:password@host`).
4. **Entropy heuristic, narrowly scoped.** Applied *only* to values that are not at an exempt
   identifier path and do not match a known identifier shape (UUID, ULID, 32-char hex digest).

**Exempt identifier paths** (rule 4 only — rules 1–3 always apply): `id`, `unique_id`, `entity_id`,
`device_id`, `pipeline_id`, `preferred_pipeline`, `wake_word_id`, `wake_word_entity`, `agent_id`,
`conversation_engine`, `stt_engine`, `tts_engine`, `tts_voice`, `uri`, `media_id`, `item_id`,
`media_content_id`.

Any hit → **exit 6, nothing written**. The summary names the resource and the JSON path, and
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
                     [--probe-only] [--strict-inventory]
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

### 5.1 Transaction, promotion and crash semantics

The earlier draft claimed both "nothing is captured on failure" and "raw responses are retained",
and implied one atomic operation spanning two roots. Neither was coherent. The precise definition:

**"Atomic" means: the canonical tree is never partially replaced.** It explicitly does *not* mean a
single transaction across the raw and canonical roots — they are different filesystems' worth of
different concerns and are promoted **independently**.

| Phase | Action | On failure |
|---|---|---|
| 1 | Probes (§2) | Nothing written anywhere. Exit 2/3/4. |
| 2 | Fetch every managed resource **into memory** | Nothing written. Exit 5/7. |
| 3 | Normalize + render canonical bytes in memory | Nothing written. Exit 4. |
| 4 | Secret scan over raw payloads **and** canonical bytes | Nothing written. Exit 6. |
| 5 | Write both trees to temp dirs, each on the **same filesystem** as its final parent — `<raw-dir>/.tmp-<pid>/` at `0700`, `<out>/../.tmp-ha-export-<pid>/` | Delete **both** temp trees; previous outputs untouched. |
| 6 | Promote raw: `rename` temp → `<raw-dir>/<UTC-ts>/` (a **new** directory; never replaces) | Delete both temp trees. |
| 7 | Promote canonical: `rename <out>` → `<out>.prev-<ts>`, `rename` temp → `<out>`, then delete `.prev` | See crash window below. |

Nothing whatsoever is written before phase 5 — so a probe, fetch, schema or secret failure leaves the
filesystem exactly as it was, including any previous successful export.

**Raw is promoted first, deliberately.** It is additive and harmless, and if canonical promotion then
fails you still hold the source snapshot that explains why. The converse — canonical output with no
raw to justify it — is the worse state.

**Replacing a non-empty `--out`:** the swap in phase 7 replaces the tree wholesale rather than merging
into it. That is what gives deterministic **deletion** handling: a resource removed from the manifest
disappears from the canonical tree instead of lingering as a stale file that no export would ever
touch again.

**Crash window:** phase 7 is two renames, so a crash between them leaves `<out>` absent and
`<out>.prev-<ts>` present. This is detectable and recoverable, not corrupting — on startup the tool
checks for an orphaned `<out>.prev-*` with no `<out>` and restores it, reporting that it did so. The
runbook documents the one-line manual equivalent. A single-rename design is not available because
`<out>` is a directory that must be replaced, not a file.

**Permissions:** raw dirs `0700`, raw files `0600`, applied at creation via `os.makedirs(mode=…)` plus
explicit `os.chmod`, not left to umask. POSIX only — the assertion tests are
`skipUnless(os.name == 'posix')`, since the dev machine is Windows and cannot enforce these modes;
the host run is the one that proves it.

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
  order and indentation. Hash-order independence is tested by **launching separate interpreters**
  (`subprocess.check_output([sys.executable, …], env={"PYTHONHASHSEED": seed})` over several seeds)
  and comparing bytes across processes. Setting `PYTHONHASHSEED` inside the running interpreter tests
  nothing — the seed is fixed at startup.
- **Secret scan — must FAIL** — a bearer token in a script `sequence`; a JWT; a `password:` key; a
  PEM block; credentials in a URL; and the literal on-host token value. Each → exit 6, output dir
  untouched, message names the JSON path and **not** the value.
- **Secret scan — must PASS** — a fixture carrying a pipeline **ULID**
  (`01kxygpr39jas5hgsf28cph108`), a RadioBrowser **UUID**, a 32-hex device id, `entity_id`s and
  `media_content_id`s. These are real shapes from this system and a naive entropy rule rejects all of
  them; this test is what keeps the exporter usable at all.
- **Envelope vs subtree** — an unknown key on a resource **envelope** → exit 4. A novel, deeply
  nested, never-seen-before action inside `sequence` → **preserved byte-for-byte**, and a secret
  buried at its deepest level is still **caught** (losslessness must not become a leak path).
- **Missing resource** — manifest names an automation HA does not return → exit 5. With
  `--strict-inventory`, an unmanaged resource present in HA → exit 5; without it, summary only.
- **Partial API failure** — one source raises mid-run → exit 7, **nothing written**.
- **Failure leaves prior state intact** — run a successful export, then a failing one; assert the
  previous canonical tree is **byte-identical** afterwards and that no `.tmp-*` residue survives, for
  each of exits 2/3/4/5/6/7.
- **Interrupted promotion** — simulate a crash between the two renames of phase 7; assert the orphan
  `<out>.prev-*` is detected and restored on the next run, and that the recovery is reported.
- **Deletion handling** — remove a resource from the manifest, re-export, assert its file is **gone**
  from the canonical tree rather than left stale.
- **Permissions** (`skipUnless(os.name == 'posix')`) — raw dirs `0700`, raw files `0600`.
- **Stable normalization** — Cyrillic names survive unescaped; runtime metadata (`last_changed`,
  `context`) is stripped; `sequence` and `choose` **list order is preserved** while mapping keys
  within them are sorted; `options` and the exposure list are **sorted**. The order-preservation case
  is the one that would silently corrupt behaviour, so it gets an explicit test per resource type.

## 8. First live export — approval-gated

1. **Bootstrap deployment of `ha_export.py`. Gate: approval.** The manifest-based resolver deploy does
   not exist yet, and `tools/` has never been deployed at all — `snapshot.py` is repo-only — so this
   is a one-time hand deployment and must be verifiable rather than assumed:
   - compute `sha256` of the local file with `tr -d '\r'` applied (mandatory — see the CRLF note);
   - `scp` it to `~/mass-resolver/tools/`;
   - recompute on the host the same way and **compare the two digests explicitly**; abort on any
     mismatch rather than proceeding;
   - `python3 -m py_compile` it on 3.5.2;
   - record the digest and the date in the `CHANGELOG.md` entry, so the deployed artefact has a
     recorded identity until the manifest deploy subsumes it.
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
- **Residual risk introduced by the identifier exemptions (§4).** Exempting identifier paths from the
  entropy heuristic means a secret *stored at one of those paths* — say, a token pasted into a
  `media_id` — escapes rule 4. Rules 1–3 still apply and the literal on-host match is never exempt,
  so a real HomeBrain token is still caught; an unrelated third-party secret in that position would
  not be. That is a deliberate trade: the alternative rejects every pipeline ULID and station UUID
  and the exporter never runs at all. Worth revisiting if the exempt list grows.
- **Residual risk in the promotion crash window (§5.1).** Two renames cannot be collapsed into one
  for a directory, so a crash between them is possible. It is recoverable and self-detecting rather
  than corrupting, but it is a real state the tool must handle on startup, and the test for it
  simulates the crash rather than assuming it cannot happen.
- **Scope honesty:** this tracks a hand-picked surface. Everything outside `MANIFEST.json` remains
  untracked, and the runbook must say so plainly rather than implying HA is "in Git".
- **Not disaster recovery.** Stated three times on purpose.

## 13. Proposed BACKLOG note (not applied — `BACKLOG.md` is out of scope for this branch)

> **`INF-09` HA managed-state exporter (read-only).** Plan ready
> (`plans/2026-09-06-inf-09-ha-managed-state-exporter-plan.md`). Depends on off-host HA backups being
> configured first (disaster recovery is the prerequisite, not the substitute). Deliverables:
> `tools/ha_export.py`, fixture tests, `docs/homebrain/ha/` baseline, and
> `runbooks/ha-managed-state-export.md`. Export only — no apply path in this increment.
