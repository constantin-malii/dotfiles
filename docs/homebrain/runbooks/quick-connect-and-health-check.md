# HomeBrain Runbook — Quick Connect & Stack Health Check

> **Purpose:** let a fresh session connect to the HomeBrain host and triage
> *"ChatGPT can't reach music/radio"* fast, without re-deriving the SSH and `/command`
> diagnostics. Read [`../ONBOARDING.md`](../ONBOARDING.md) first for the architecture.
>
> **Live system.** Everything in §1–§2 is **read-only**. Recovery steps (§3) **restart/modify** and
> require **explicit user approval** — see the root [`CLAUDE.md`](../../../CLAUDE.md) operating rules.

## 1. Connect to the host (SSH)

- **Key file:** `~/.ssh/id_homebrain` (on your machine). **Host:** `costea@192.168.1.68`.
- **Must go through ssh-agent.** A direct `ssh -i ~/.ssh/id_homebrain …` fails
  ("we did not send a packet"). The agent also **drops the key between calls**, so re-run the
  preamble **each session / each call**.
- **Host SSH hangs intermittently** — always bound every call with `timeout` + `ConnectTimeout` +
  `ServerAliveInterval`/`ServerAliveCountMax`. **Never let an SSH call hang indefinitely**; on a hang,
  cancel and retry (re-adding the key).

```bash
# Preamble — run each session/call (starts the agent if needed, loads the key):
eval "$(ssh-agent -s)"; ssh-add ~/.ssh/id_homebrain
SSH='ssh -o ConnectTimeout=15 -o ServerAliveInterval=8 -o ServerAliveCountMax=3 costea@192.168.1.68'

# Always wrap remote commands in a timeout so they can't hang the session:
timeout 60 $SSH 'echo ALIVE'      # prints ALIVE => host reachable + SSH OK
```

- **sudo** needs a TTY **and** user approval: `ssh -t costea@192.168.1.68 'sudo …'`. Read-only checks
  run fine over plain agent SSH.

## 2. First-pass stack health check (read-only)

Uses the resolver's **own on-host secret** (`~/mass-resolver/.http_secret`), so **no token is needed
from the user** and **no secret is printed**.

```bash
timeout 60 $SSH '
echo "host:     $(hostname)"                                   # SSH OK if this prints
echo "VM:       $(virsh -c qemu:///system domstate haos)"      # expect: running
echo "resolver: $(systemctl is-active mass-resolver)"          # expect: active
ss -ltn | grep -q "192.168.122.1:8770" && echo "/command: bound" || echo "/command: NOT bound"
SEK=$(cat ~/mass-resolver/.http_secret)
curl -s -m6 -o /dev/null -w "cmd good_key=%{http_code} " -H "X-Resolver-Key: $SEK" -H "Content-Type: application/json" -d "{\"intent\":\"status\"}" http://192.168.122.1:8770/command   # expect 200
curl -s -m6 -o /dev/null -w "no_key=%{http_code}\n" -H "Content-Type: application/json" -d "{\"intent\":\"status\"}" http://192.168.122.1:8770/command                                    # expect 401
curl -s -m6 -o /dev/null -w "MA=%{http_code} " http://192.168.122.10:8095/info      # expect 200
curl -s -m6 -o /dev/null -w "HA=%{http_code}\n" http://192.168.122.10:8123/          # expect 200
echo "--- resolver log tail ---"; tail -n 8 ~/mass-resolver/resolver.log
'
```

**Healthy signature (all true):**

| Check | Healthy value |
|---|---|
| host line prints | SSH reachable |
| VM | `running` |
| `mass-resolver` | `active` |
| `/command` | `bound` (LISTEN on `192.168.122.1:8770`) |
| `/command` auth | `good_key=200`, `no_key=401` |
| MA | `MA=200` |
| HA | `HA=200` |
| event path (log) | `SERVICE: /command HTTP server on 192.168.122.1:8770` **and** `SERVICE: connected; subscribed to 'mass_play_request' … 'mass_sync_request' … 'mass_radio_request' …` |

## 3. Triage — "ChatGPT can't play music/radio"

**First, localize the fault** from the health check (all three ChatGPT tools go through `/command`):

- `/command` **NOT bound**, or `good_key ≠ 200` → **`/command` is down** (most common after a reboot) → §3a.
- `MA ≠ 200` or `HA ≠ 200` → **backend down / still loading** (resolver can't reach MA/HA) → §3b.
- `/command` bound + MA/HA `200`, but the log has **no** `connected; subscribed` (loops `connection
  error … reconnecting`) → **event path not connected** (usually self-heals; see §3b).

### 3a. Cold-boot `/command` bind race (the common one)

Signature in `~/mass-resolver/resolver.log` at startup:

```
SERVICE: HTTP server failed to start (OSError(99, 'Cannot assign requested address')); continuing event-only
```

**Meaning:** the resolver started **before** the libvirt bridge `192.168.122.1` existed, so the
`/command` bind failed and the service ran **event-only**. The event path may later show
`connected; subscribed`, but `/command` stays down → the three ChatGPT tools return the fallback
("can't reach music/radio").

**Confirm it's safe to fix (both should be true now):**
```bash
timeout 45 $SSH 'ip -4 addr show virbr0 | grep -w 192.168.122.1 && (ss -ltn | grep -q 192.168.122.1:8770 && echo "8770 BOUND" || echo "8770 free")'
```
- bridge IP `192.168.122.1` **present**, and port **8770 free** (nothing bound) → a restart will bind cleanly.

**Recovery (requires user approval — sudo + restart):**
```bash
sudo systemctl restart mass-resolver      # user runs (needs TTY: ssh -t … 'sudo …')
```
Then re-run the §2 health check → expect `/command: bound`, `good_key=200 / no_key=401`, and the log
line `SERVICE: /command HTTP server on 192.168.122.1:8770`.

**Durable self-heal** (retry the bind so no manual restart is needed after a reboot) is a planned fix:
[`../plans/2026-07-01-command-bind-retry-bugfix.md`](../plans/2026-07-01-command-bind-retry-bugfix.md).

### 3b. Other cases

| Health-check symptom | Cause | Recovery (needs approval) |
|---|---|---|
| VM ≠ `running` | HAOS VM down | `virsh -c qemu:///system start haos` |
| `mass-resolver` ≠ `active` | resolver crashed / didn't start | `sudo systemctl restart mass-resolver` |
| `MA ≠ 200` shortly after an MA restart | add-on still loading | **wait ~130 s**, re-check (early plays fail) |
| HA↔MA drop (log loops `connection error`, or MA silently dead) | internal Docker DNS drop | reload the MA config entry: `POST /api/config/config_entries/entry/01KVPNW1JFHJG30NANAPVARHY8/reload` (A1/A2a usually auto-heal) |
| `good_key ≠ 200` / `no_key ≠ 401` | endpoint / auth mismatch | check `~/mass-resolver/.http_secret` vs the HA `rest_command.resolver_command` header; restart resolver |
| log shows a play but there's no sound | host Squeezelite | check `squeezelite-ceiling.service` on the host |

## 4. Safety

- **No host / VM / service restart without explicit user approval.**
- **No live HA / host / API / resolver / exposure changes unless authorized.**
- Diagnostics in §1–§2 are **read-only**; every recovery step in §3 (restart / reload / start) needs
  approval.
- **Never print, log, stage, or commit secrets.** The health check reads `.http_secret` on-host into a
  shell variable and prints nothing.
- Authoritative context: [`../ONBOARDING.md`](../ONBOARDING.md) · latest changes in
  [`../CHANGELOG.md`](../CHANGELOG.md) · operating rules in the root [`CLAUDE.md`](../../../CLAUDE.md).
