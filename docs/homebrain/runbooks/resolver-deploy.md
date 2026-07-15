# HomeBrain Runbook — Resolver Deploy (`~/mass-resolver`)

> **Purpose:** deploy a resolver code change to the live host safely and reversibly. Read
> [`../ONBOARDING.md`](../ONBOARDING.md) and
> [`quick-connect-and-health-check.md`](quick-connect-and-health-check.md) first.
>
> **Live system.** Staging (backup / copy / compile / test) is agent-safe over SSH; the **restart is a
> user-run `sudo` step** (host sudo needs a password) and requires **explicit approval** + claims the
> single live gate (BACKLOG §10). Never print, log, or commit secrets.

## Connect
Per `quick-connect-and-health-check.md` §1: key `~/.ssh/id_homebrain`, host `costea@192.168.1.68`, via
ssh-agent (re-add the key each call), every call bounded with `timeout` + `ConnectTimeout`. Host Python
is **3.5.2** — the deploy's real compatibility target.

```bash
eval "$(ssh-agent -s)"; ssh-add ~/.ssh/id_homebrain
SSH='ssh -o ConnectTimeout=15 -o ServerAliveInterval=8 -o ServerAliveCountMax=3 costea@192.168.1.68'
OPTS='-o ConnectTimeout=15 -o ServerAliveInterval=8 -o ServerAliveCountMax=3'   # for scp
```

## 0. Preflight (read-only)
- Run the §2 health check (`quick-connect…`): resolver `active`, VM `running`, `/command` bound, `200/401`.
- **Deploy only when no interaction is active** (`assist_satellite` idle) — a restart mid-duck loses the
  in-memory duck snapshot + dead-man timer and strands the ceiling at the floor.
- Claim the live gate in BACKLOG §10 (record track + branch).

## 1. Backup (agent SSH)
```bash
timeout 45 $SSH 'ts=$(date +%Y%m%d-%H%M%S); cd ~/mass-resolver && mkdir -p .bak/$ts && \
  cp <changed-existing-files> .bak/$ts/ && echo "BACKUP_TS=$ts" && ls .bak/$ts'
```
Record the timestamp — it is the rollback pointer. (New files have no backup; rollback deletes them.)

## 2. Copy changed files (scp — POSIX local paths)
`scp` treats `D:` as a hostname, so use `/d/repos/...`, not `D:/repos/...`:
```bash
LOCAL=/d/repos/dotfiles/docs/homebrain/mass-resolver
timeout 90 scp $OPTS "$LOCAL/<file>" ... costea@192.168.1.68:~/mass-resolver/
timeout 90 scp $OPTS "$LOCAL/tests/<test_*.py>" costea@192.168.1.68:~/mass-resolver/tests/   # optional (on-host parity run)
```
Then verify content landed — `grep` for a distinctive marker in each changed file (don't trust `scp`'s
exit alone; the PQ-warning banner can mask output).

## 3. Compile + test on host Python 3.5.2
```bash
timeout 90 $SSH 'cd ~/mass-resolver && python3 -m py_compile <changed .py> && echo "COMPILE OK" && \
  python3 tests/test_<changed>.py 2>&1 | tail -2'
```
The 3.5.2 run is the real parity check (dev-machine Python is newer; catches f-strings / type-hints /
numeric-separator slips the local run misses).

## 4. Restart — USER-RUN (sudo needs a password + approval)
```bash
ssh -t costea@192.168.1.68 'sudo systemctl restart mass-resolver'
```
Agent SSH cannot do this: there is no passwordless sudo, and the interactive prompt hangs a
non-interactive shell. This is the single disruptive/gated step — hand it to the operator.

## 5. Validate (read-only, agent SSH)
- Re-run the §2 health check → `active`, `/command` bound, `200/401`, log shows a fresh
  `SERVICE: /command HTTP server on 192.168.122.1:8770` + `connected; subscribed …`, no tracebacks.
- Exercise the changed capability via `/command` (secret from on-host `~/mass-resolver/.http_secret`). For
  volume/media effects, read `media_player.<zone>` state **before/after** via HA REST (token from on-host
  `~/mass-resolver/.ha_token`, read into a shell var, **never printed**) to confirm the real-world effect,
  not just the resolver's self-report.

## 6. Close out
- Release the live gate (BACKLOG §10 → FREE); flip the item to `done`.
- Add a `CHANGELOG.md` entry: files deployed, validation evidence, backup/rollback pointer.

## Rollback
```bash
ssh -t costea@192.168.1.68 'cp ~/mass-resolver/.bak/<ts>/* ~/mass-resolver/ && \
  rm -f ~/mass-resolver/<any-newly-added-file> && sudo systemctl restart mass-resolver'
```

## Safety
- **No restart / live change without explicit approval**; one live gate at a time (BACKLOG §10).
- **Never print/log/commit secrets** (`.http_secret`, `.ha_token`) — read them into on-host shell vars only.
- Resolver changes are the media path (single gate); keep the timestamped backup and validate before
  releasing the gate.

---

## Worked example — AU-02/AU-03 interaction duck/restore (2026-07-15)
Files: `haconn.py`, `config.py`, `config.json`, `interaction.py`, `core.py` (+ 3 changed tests). Backup
`~/mass-resolver/.bak/20260715-130644/`. Host `py_compile` + changed tests passed on 3.5.2. Post-restart
validation with music playing: `duck` took the ceiling `0.43 → 0.15`, `restore` returned it to exactly
`0.43` (confirmed against HA state), silently, music never stopped. See `CHANGELOG.md` 2026-07-15.
