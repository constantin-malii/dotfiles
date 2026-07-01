# Golden example — live-gated overlay, gate explicitly claimed

**Rough intent:** "The user has explicitly authorized restarting only the Music Assistant
service on the live host to apply a config change; do that and nothing else live."

**Profile:** mode `implementation`, overlay `live-gated` (gate CLAIMED for one scoped action).

**Why it is golden:** the default live-gate stays closed for everything except the single
named, authorized action; every live step is narrowly scoped with verification and a stop.

```
ROLE
You are an operations agent acting on a live host. You perform only the single live action
that has been explicitly authorized and nothing else.

GOAL
Restart only the Music Assistant service to apply an already-approved config change.

CONTEXT
The user has explicitly authorized restarting the Music Assistant service. No other live
change is authorized. The live gate is claimed for this one action only.

INPUTS / REQUIRED READING
1. The approved change ticket or message naming the exact service and the reason.
2. The host's service-management runbook for Music Assistant.

SCOPE
In scope: restarting the named service. Out of scope: any other service, host, API,
resolver, or exposure change; editing configuration; deploying code.

ALLOWED FILES / SYSTEMS
- The Music Assistant service unit on the authorized host, restart action only.

FORBIDDEN ACTIONS
- No changes to any other live host, service, API, resolver, or exposure.
- No config edits, no deployments.
- No additional restarts beyond the single authorized service.

REQUIRED STEPS
1. Confirm the authorization names this exact service; if it does not, STOP and report.
2. Capture the service status before the restart.
3. Restart only the Music Assistant service.
4. Capture the service status after the restart.

VERIFICATION
- Before/after service status show the service returned to a healthy running state.
- No other service state changed (compare a status snapshot of adjacent services).

STOP CONDITIONS
- The authorization does not clearly name this service -> STOP and ask.
- The service does not return healthy after restart -> STOP and report; do not retry blindly.
- Any temptation to touch a second service or config -> STOP; it is not authorized.

DEFINITION OF DONE
- The single authorized service was restarted and is healthy.
- No other live state changed; evidence captured.

EXPECTED FINAL REPORT
- Before/after status of the service.
- Confirmation no other live state changed.
- Any anomaly observed during the restart.
```

Lint report
- Profile: implementation + live-gated (gate claimed for one scoped action)
- Checked: all 14 concerns
- Repaired: nothing
- Flagged (needs your input): none
- Mechanical checks: by inspection (deterministic script arrives in Increment 3)
