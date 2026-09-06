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
> **Read-only.** The exporter never writes to Home Assistant — no apply, import or restore exists
> in this increment. It is safe to run at any time; it does not claim the live gate.

## 1. What is captured

Everything named in `docs/homebrain/ha/MANIFEST.json`, and nothing else:

| Resource | Why it matters |
|---|---|
| Scripts, incl. each field's `description` | **These field descriptions are the LLM's tool schema.** Editing that text changes model behaviour — it happened twice on 2026-09-06. |
| Automations, incl. conversation sentence triggers | The `play_favorite` handles, the pause/stop routing, volume phrasings. |
| Assist pipelines | Which agent, STT, TTS and wake word each pipeline uses. |
| Satellite `select.*` settings | `finished_speaking_detection`, wake words, sensitivity, pipeline assignment. |
| Conversation exposure | Which entities the assistant can see. Security-relevant. |
| HA version | Recorded in `meta.json`; the version the export was valid for. |

## 2. What is NOT captured

Helper entities, dashboards, integrations and config entries, `.storage` internals, secrets, the
recorder database, add-ons, and **the instance itself**. Anything outside `MANIFEST.json` is
**unmanaged** — the run summary lists unmanaged scripts and automations so the manifest can be
extended deliberately, but it is never exported silently.

Increment 1 handles satellite **`select`** entities only. The `switch.*` settings (wake sound,
mute sound) have a different attribute shape and are not yet modelled.

## 3. Run a probe (read-only, writes nothing)

Always the first thing after an HA upgrade.

```bash
python3 ~/mass-resolver/tools/ha_export.py \
  --manifest ~/ha-state/MANIFEST.json --out ~/ha-state/managed --probe-only
```

It fetches and validates **every** managed resource, then stops without writing. A clean run means
every endpoint exists and every response shape is understood.

## 4. Run an export

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

## 5. Exit codes

| Code | Meaning | What to do |
|---|---|---|
| 0 | Success | Review the diff. |
| 1 | Usage / environment | Bad args, or the token file is unreadable. |
| 2 | Transport or auth | HA unreachable. Run the §2 health check in `quick-connect…`. |
| 3 | **Capability probe failed** | An endpoint is gone or changed shape — see §7. |
| 4 | **Schema probe failed** | An unknown envelope key appeared — see §7. |
| 5 | Managed resource missing | A manifest entry no longer exists in HA (or, with `--strict-inventory`, an unmanaged resource exists). |
| 6 | **Secret detected** | Nothing was written. See §8. |
| 7 | Partial failure | Nothing was written. Re-run; if it persists, capture the message. |

Nothing is written before every check has passed. A failure leaves the previous export
**byte-identical** — the tool is safe to re-run.

## 6. How to read a diff

- **A change inside `sequence`, `actions`, `triggers` or `conditions` is BEHAVIOUR.** Review it the
  way you would review code. List order is preserved precisely so these diffs are honest.
- **A `fields.<name>.description` change alters the LLM's tool schema** and can change which tool
  the model picks, or with what arguments. Treat it as a behaviour change, not a doc tweak.
- **A `state` change on a satellite select is a setting change** (`finished_speaking_detection`,
  a wake word, the assigned pipeline).
- **An `exposure/conversation.json` change is security-relevant** — the assistant just gained or
  lost sight of an entity.
- **A file that disappeared** means the resource left the manifest, or was deleted in HA.
- Runtime metadata (`last_changed`, `context`) is stripped and there is no timestamp in the
  canonical files, so **any diff at all is a real change**. That is the whole point.

## 7. When a probe fails after an HA upgrade

Expected eventually. Two of the sources — `/api/config/script/config/<object_id>` and
`/api/config/automation/config/<id>` — are **undocumented frontend routes**, not part of HA's
public REST API. They are version-coupled by nature.

- **Exit 3** — the route is gone or no longer returns an object. Do **not** work around it. Find the
  current route, confirm it by hand, then update the exporter deliberately.
- **Exit 4** — HA added or renamed an envelope key. The message names it. Look at what it is, decide
  whether it belongs under change control, and update the allowlist in `ha_export.py`.

**There is deliberately no runtime override.** An export that omits data while reporting success is
worse than one that refuses to run, so the fix is always a code change a human made on purpose.

## 8. If a secret is detected (exit 6)

The message names the resource and the JSON path — **never the value**. It means a managed script or
automation embeds something secret-shaped. Fix the resource (move the secret to `secrets.yaml` or a
`rest_command` header sourced from it) rather than weakening the scanner. Until then that resource
cannot be tracked.

Detection is path-aware, not entropy-first: pipeline IDs are ULIDs, station IDs are UUIDs, and a
naive entropy rule flags all of them. Identifier paths are exempt from the entropy heuristic **only**
— a literal match against the real on-host tokens is never exempt.

## 9. Recovery: interrupted promotion

Replacing a directory takes two renames, so a crash between them can leave `<out>` missing and
`<out>.prev-<stamp>` present. The next run **detects and restores it automatically** and says so.
Manual equivalent:

```bash
mv ~/ha-state/managed.prev-<stamp> ~/ha-state/managed
```

## 10. Safety

- Read-only against HA. No apply path exists.
- Secrets are read into memory for the literal-match rule and are **never printed, logged or
  written**.
- Raw snapshots are `0700`/`0600`, are pruned to the most recent `--keep-raw` (default 10), and must
  never be committed.
- Running an export claims no live gate and needs no restart.
