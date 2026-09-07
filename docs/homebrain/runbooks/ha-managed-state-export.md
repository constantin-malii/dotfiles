# HomeBrain Runbook — Home Assistant Managed-State Export (INF-09, read-only)

> **Purpose:** capture the Home Assistant app-layer surface HomeBrain owns as canonical,
> diffable files, so a live change stops being invisible. Read
> [`../ONBOARDING.md`](../ONBOARDING.md) and
> [`quick-connect-and-health-check.md`](quick-connect-and-health-check.md) first.
>
> **This is change control, NOT disaster recovery.** It captures a hand-picked set of resources.
> It does **not** replace encrypted off-host Home Assistant backups, and must never be described
> as doing so. Losing the HA volume is a *backup* problem; this tool would not restore it.
>
> **Read-only against Home Assistant.** No apply, import or restore exists in this increment, and
> an export never claims the live gate or needs a restart. It does write to the LOCAL filesystem
> (§6), so it is not a no-op on the host.
>
> **The first deployment and the first probe are approval-gated** (§3). Once bootstrapped, routine
> probes and exports need no further approval.

## 1. What is captured

Everything named in `docs/homebrain/ha/MANIFEST.json`, and nothing else:

| Resource | Why it matters |
|---|---|
| Scripts, incl. each field's `description` | **These field descriptions are the LLM's tool schema.** Editing that text changes model behaviour — it happened twice on 2026-09-06. |
| Automations, incl. conversation sentence triggers | The `play_favorite` handles, the pause/stop routing, volume phrasings. |
| Assist pipelines | Which agent, STT, TTS and wake word each pipeline uses. |
| Satellite `select.*` settings | `finished_speaking_detection`, wake words, sensitivity, pipeline assignment. |
| Conversation exposure | Which entities each **declared** assistant can see. Security-relevant. |
| HA version | Recorded in `meta.json`; the version the export was valid for. |

## 2. What is NOT captured

Helper entities, dashboards, integrations and config entries, `.storage` internals, secrets, the
recorder database, add-ons, and **the instance itself**. Anything outside `MANIFEST.json` is
**unmanaged** and is never exported.

**Two different guarantees, worth keeping straight:**

- **Everything you declare is checked to exist.** A manifest entry HA does not have → **exit 5**.
  That includes satellite entities: a declared `select.*` that is gone fails the run.
- **Unmanaged resources can only be *listed* where a discoverable inventory exists** — exactly four:
  **scripts**, **automations**, **pipelines**, and **observed exposure assistants**. The run summary
  lists those so the manifest can be extended deliberately, and `--strict-inventory` makes any of
  them **exit 5** before anything is written, labelled `script.<id>` / `automation:<id>` /
  `pipeline:<id>` / `assistant:<name>`. Strict mode is exhaustive over those four and no further.
- **Satellite entities are not enumerated.** `/api/states` is the whole instance, and separating out
  "the satellite's entities" needs a device or integration boundary — an `entity_id` prefix match is
  a naming heuristic, not a boundary. So a satellite `select.*` you never declared will not be
  reported. Add it to the manifest if you want it tracked.
- **`preferred_pipeline` is a declared singleton** (`include_preferred_pipeline`), not a collection:
  it is either declared and captured or not, and has no unmanaged notion.

**Two singleton surfaces are declared explicitly**, so nothing is captured merely because
HA returned it: `exposure_assistants` filters conversation exposure to the assistants you
name (undeclared ones are reported as unmanaged), and `include_preferred_pipeline` gates
`pipelines/_preferred.json`. The preferred pipeline is a separate global setting, so it is
**not** gated on the `pipelines` list -- `pipelines: []` still captures it if declared.

Increment 1 handles satellite **`select`** entities only. The `switch.*` settings (wake sound,
mute sound) have a different attribute shape and are not yet modelled.

## 3. Bootstrap (first time only — APPROVAL-GATED)

The manifest-based resolver deploy does not exist yet and `tools/` has never been deployed, so both
files are placed by hand and **verified by digest on both sides**. Every `sha256` is computed with
`tr -d '\r'` applied: files authored from the Windows checkout carry CRLF, and a naive digest never
matches.

**Gate: explicit approval before any of this runs.**

```bash
# 1. local digests (repo side)
cd <repo>/docs/homebrain
for f in mass-resolver/tools/ha_export.py ha/MANIFEST.json; do
  echo "$(tr -d '\r' < $f | sha256sum | cut -c1-16)  $f"
done

# 2. create BOTH remote directories FIRST -- tools/ has never been deployed, so it does not
#    exist yet and scp into a missing directory fails.
ssh costea@192.168.1.68 'mkdir -p ~/mass-resolver/tools ~/ha-state'
scp mass-resolver/tools/ha_export.py costea@192.168.1.68:mass-resolver/tools/
scp ha/MANIFEST.json costea@192.168.1.68:ha-state/

# 3. recompute on the host and COMPARE EXPLICITLY — abort on any mismatch
ssh costea@192.168.1.68 '
  echo "$(tr -d "\r" < ~/mass-resolver/tools/ha_export.py | sha256sum | cut -c1-16)  ha_export.py"
  echo "$(tr -d "\r" < ~/ha-state/MANIFEST.json | sha256sum | cut -c1-16)  MANIFEST.json"
  python3 -m py_compile ~/mass-resolver/tools/ha_export.py && echo COMPILE_OK'
```

Record both digests and the date in `CHANGELOG.md`: until the manifest-based deploy subsumes this,
that entry is the only recorded identity the deployed artefacts have.

**The manifest is the deployed contract, not a scratch file.** Re-copy it whenever it changes in the
repo — a stale host copy silently exports a different surface from the one under review.

**Its scope is the complete HomeBrain operational boundary**, validated against the live instance on
2026-09-06 (HA 2026.6.4): **16 scripts, 7 automations, 5 pipelines, 6 satellite selects**, plus the
two singleton declarations. Not "the resources someone edited recently" — a partial manifest is worse
than an obvious gap, because a clean diff over some resources reads as *"Home Assistant has not
changed"*. One entry is a deliberate exception: **`lidarr_ma_sync` is not runtime behaviour**, it is
an operational / content-pipeline dependency that maintains the music library the runtime consumes,
and the manifest's own `_note` records that reasoning. `ha/MANIFEST.json` is schema-validated offline
by `tests/test_ha_export.py`, so a typo in it fails the suite rather than surfacing as an exit 5 here.

## 4. Run a probe (read-only, writes nothing)

Always the first thing after an HA upgrade.

```bash
python3 ~/mass-resolver/tools/ha_export.py \
  --manifest ~/ha-state/MANIFEST.json --out ~/ha-state/managed --probe-only
```

It fetches and validates **every** managed resource, then stops without writing. A clean run means
every endpoint exists and every response shape is understood.

## 5. Run an export

```bash
python3 ~/mass-resolver/tools/ha_export.py \
  --manifest ~/ha-state/MANIFEST.json --out ~/ha-state/managed
```

Canonical files land in `--out`; the unfiltered forensic/source snapshot lands in
`~/ha-state/raw/<UTC-timestamp>/` at mode `0700`. **Raw never enters Git** — it is the unfiltered
API response, kept so a canonical file's provenance can be checked later.

Then review, and only then copy into the repo:

```bash
scp -r costea@192.168.1.68:ha-state/managed/. <repo>/docs/homebrain/ha/
git -C <repo> add -N docs/homebrain/ha && git -C <repo> diff docs/homebrain/ha
```

**Read the diff before committing.** An export that has not been read should not be committed.

## 6. Exit codes

| Code | Meaning | What to do |
|---|---|---|
| 0 | Success | Review the diff. |
| 1 | Usage / environment | Bad args, or the token file is unreadable. |
| 2 | Transport or auth | HA unreachable. Run the §2 health check in `quick-connect…`. |
| 3 | **Capability probe failed** | An endpoint is gone or changed shape — see §8. |
| 4 | **Schema probe failed** | An unknown envelope key appeared — see §8. |
| 5 | Managed resource missing | A manifest entry no longer exists in HA (or, with `--strict-inventory`, an unmanaged resource exists). |
| 6 | **Secret detected** | Nothing was written. See §9. |
| 7 | Partial failure | Nothing was written. Re-run; if it persists, capture the message. |

Nothing is written before every check has passed. A failure leaves the previous export
**byte-identical** — the tool is safe to re-run.

## 7. How to read a diff

- **A change inside `sequence`, `actions`, `triggers` or `conditions` is BEHAVIOUR.** Review it the
  way you would review code. List order is preserved precisely so these diffs are honest.
- **A `fields.<name>.description` change alters the LLM's tool schema** and can change which tool
  the model picks, or with what arguments. Treat it as a behaviour change, not a doc tweak.
- **A `state` change on a satellite select is a setting change** (`finished_speaking_detection`,
  a wake word, the assigned pipeline).
- **An `exposure/assistants.json` change is security-relevant** — the assistant just gained or
  lost sight of an entity.
- **A file that disappeared** means the resource left the manifest, or was deleted in HA.
- Runtime metadata (`last_changed`, `context`) is stripped and there is no timestamp in the
  canonical files, so **any diff at all is a real change**. That is the whole point.

## 8. When a probe fails after an HA upgrade

Expected eventually. Two of the sources — `/api/config/script/config/<object_id>` and
`/api/config/automation/config/<id>` — are **undocumented frontend routes**, not part of HA's
public REST API. They are version-coupled by nature.

- **Exit 3** — the route is gone or no longer returns an object. Do **not** work around it. Find the
  current route, confirm it by hand, then update the exporter deliberately.
- **Exit 4** — HA added or renamed an envelope key. The message names it. Look at what it is, decide
  whether it belongs under change control, and update the allowlist in `ha_export.py`.

**There is deliberately no runtime override.** An export that omits data while reporting success is
worse than one that refuses to run, so the fix is always a code change a human made on purpose.

## 9. If a secret is detected (exit 6)

The message names the resource and the JSON path — **never the value**. It means a managed script or
automation embeds something secret-shaped. Fix the resource (move the secret to `secrets.yaml` or a
`rest_command` header sourced from it) rather than weakening the scanner. Until then that resource
cannot be tracked.

Detection is path-aware, not entropy-first: pipeline IDs are ULIDs, station IDs are UUIDs, and a
naive entropy rule flags all of them. Identifier paths are exempt from the entropy heuristic **only**
— a literal match against the real on-host tokens is never exempt.

## 10. Recovery: interrupted promotion

Replacing a directory takes two renames, so a crash between them can leave `<out>` missing and
`<out>.prev-<stamp>` present. The next run **detects and restores it automatically** and says so.
Manual equivalent:

```bash
mv ~/ha-state/managed.prev-<stamp> ~/ha-state/managed
```

## 11. Safety

- Read-only against HA. No apply path exists.
- Secrets are read into memory for the literal-match rule and are **never printed, logged or
  written**.
- Raw snapshots are `0700`/`0600`, are pruned to the most recent `--keep-raw` (default 10), and must
  never be committed.
- Running an export claims no live gate and needs no restart.
