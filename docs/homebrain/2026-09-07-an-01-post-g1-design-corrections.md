# AN-01 — Post-G1 Design Corrections

> **Status:** Accepted 2026-09-07. **Amends** the G0-approved design
> [`2026-09-06-phone-assist-ceiling-announcement-design.md`](./2026-09-06-phone-assist-ceiling-announcement-design.md)
> (commit `259c730`) in light of what G1's spikes actually measured.
>
> **Read this alongside §8.2 and §6.1 of that design — those sections are now partly wrong.** They
> are deliberately left as written: they are an accurate record of what was believed at G0, and the
> project's convention is to append corrections rather than rewrite history (design §3.6 sets that
> precedent for `BACKLOG.md`).
>
> **Scope:** three implementation-significant corrections plus one fixture correction. Nothing else
> in the design changes. G2's code worktree must be based on the commit containing this document.

---

## Why these are design-level, not plan-level

Two of the three alter **security behaviour**, and one alters an **interface contract** (§6.4's
`match_keys`). A plan may refine *how* a design is built; it may not silently change what the design
guarantees. Recording them here keeps the design the authority and stops a future reader from
implementing §8.2 as written.

---

## Correction 1 — the match-key contract: use the full normalised URI

**Design §8.2 says** MA may strip the query string from the `media_content_id` it echoes, and
therefore specifies a **path-only** `match_key` for the chime while TTS clips keep the full URI.

**Measured at AN-1 (2026-09-07):** the query is **preserved**. MA echoed

```
builtin://track/http://192.168.122.10:8123/media/local/timer_chime.wav?authSig=<REDACTED>
```

**Correction.** Every clip's `match_key` is its **full normalised URI**. There is no per-clip
divergence, and §8.2's path-only special case is withdrawn as unnecessary.

**What is kept and why.** §6.4's `match_keys` list stays in the interface. It costs nothing, it keeps
per-clip matching explicit rather than implied, and it leaves a seam if MA's wrapping ever changes.
What is withdrawn is only the *rule* that the chime needs a different key from a TTS clip.

**Second finding, previously undocumented anywhere.** MA wraps by **media type**:
`interaction.py`'s existing comment documents TTS clips arriving as `builtin://radio/<url>`, while
the chime arrives as `builtin://track/<url>`. Nothing in the code anticipated `track`. See
correction 3, which depends on this.

---

## Correction 2 — signed URLs must never reach a log

**Design §6.1 says** the resolved URL is a bearer credential and must never be logged, and that
logging uses `_clip_id`'s SHA1 fingerprint.

**That instruction was correct but incompletely applied.** The signature also travels inside the
**`media_content_id` that HA reports back**, which `_say` reads on every poll — a path §6.1 did not
consider. And `_say`'s finish-poll logs `cid[:60]`:

```python
LOG.info("SAY req=%s zone=%s clip=%s finish-poll exit after %.1fs: state=%s cid=%s",
         rid, zone, clip, elapsed, state.get("state"), cid[:60])
```

For the measured URL those 60 characters stop just short of `authSig`. **That is luck, not a
guarantee** — a shorter host, a shorter path, or a differently-wrapped URI puts a live credential
into `resolver.log`, which is world-readable on the host and quoted freely in `CHANGELOG.md`.

**Correction.** A truncation is not a redaction. Introduce an explicit helper — strip `authSig=…`
and any `sig`, `signature`, `token` or `access_token` parameter — and apply it to **every** log line
that emits a `media_content_id`, a resolved URL, or any state blob that may contain one. Add a test
that asserts no log record produced by a chime turn contains `authSig`.

**Rationale for strictness:** the credential grants read access to HA's media, the log outlives the
signature's validity as a written record, and this project's own operating rules already say *never
print, log, stage, or commit secrets*. A rule that holds only because a string happened to be long
enough is not a rule.

---

## Correction 3 — a chime is an ephemeral clip, not a durable source

**The design never classified the chime.** `interaction.py`'s `_is_reply_uri` decides what may be
remembered as a resumable source, and excludes exactly two forms:

```python
return ("tts_proxy" in u) or u.startswith("builtin://radio/http")
```

Per correction 1, the chime arrives as **`builtin://track/http://…`** — matching neither. So nothing
prevents `remember_source` from recording a chime as the zone's *last real source*.

**Consequence if left.** `resume` would replay a spent chime instead of the operator's music — and
worse, replay it by a **URL whose signature has expired**, producing a silent failure whose cause is
two layers from its symptom. This is the same class of defect as the stop/replay bug in
`CHANGELOG.md` 2026-09-05, where a reply clip was resurrected as though it were music.

**Correction.** Extend the reply/source classification so a chime can never be captured or replayed
as a durable source: treat a `builtin://track/` URI pointing at `/media/local/` as an ephemeral
clip, alongside the existing `tts_proxy` and `builtin://radio/http` forms. Add a regression test
naming **this exact wrapper**, so a future change to MA's wrapping fails loudly rather than silently
re-enabling the bug.

---

## Fixture correction — no `./` anywhere

**Every** default, fixture, test and config value must use:

```
media-source://media_source/local/timer_chime.wav
```

**Never** `media-source://media_source/local/./timer_chime.wav`.

A `./` segment makes HA sign the **un-normalised** path while returning a **normalised** URL, so the
signature cannot validate against the URL it is attached to. Proven both ways at AN-1: with `./` the
returned URL 401s but the *same signature* succeeds when `./` is re-inserted into the request path;
without `./` the returned URL fetches 200 and re-inserting `./` 401s.

This is the blocker that stood from 2026-09-05 to 2026-09-07. `CHANGELOG.md:246-252` recorded the
observed 401 and concluded *"MA cannot fetch HA's media files, which need auth"* — a conclusion
downstream of the malformed identifier, since a correctly-signed URL fetches unauthenticated and
returns `audio/vnd.wave`. That entry gets a dated correction at G5; it is not rewritten.

**Design §3.2 and §12 quote the `./` form** and are corrected at G5 for the same reason.

---

## What does not change

- §8.2's **containment** matching (`match_key in media_content_id`) — still correct, and still
  necessary, because MA wraps rather than echoing the raw URL.
- §6.1's `resolve_media_source` design — fresh per-call WebSocket, absolutisation, per-turn
  resolution with no caching. All confirmed by measurement.
- The clip-sequence state machine, mic leasing, generation adoption, timing budgets, and every
  failure-behaviour row. G1 exercised the mic and chime paths and contradicted none of it.
- §12's fallback ranking. It was never invoked; the chime works.

---

> **Rollback:** `git revert` the commit adding this file, and revert the plan's references to it. No
> code depends on it yet — this document is the precondition for G2, not a product of it.
