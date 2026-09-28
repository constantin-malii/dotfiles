# DRAFT upstream issue — Music Assistant (`music-assistant/server`) — FOR REVIEW, NOT SUBMITTED

> Prepared 2026-09-27. No matching upstream issue found (searched `music-assistant/server`,
> `music-assistant/support`, `home-assistant/core`, the HA community forum and Reddit). Adjacent
> issues are listed at the bottom; none describes this. Submit only after review.

---

**Title:** TTS announcement silently skipped — queue flow requests a `.flac` variant of an HA
`tts_proxy` URL, which 404s

### Environment

- Music Assistant server **2.9.3** (HA add-on), Home Assistant Core **2026.6.4** (HAOS VM).
- Player: **Squeezelite** (via `aioslimproto`) wrapped by the **Universal Player**.
- TTS: **Piper** (`tts.piper`), served by HA's `tts_proxy`.
- Caller: a service that resolves a URL via HA's `/api/tts_get_url` and then calls
  `music_assistant.play_media` with it. The same failure appears on HA's own `tts.speak`
  announcement path (see "It is not specific to one caller").

### Summary

An announcement produces **no audio at all** while the player continues to report `state: playing`
indefinitely. MA decides the item is unplayable **91 ms after starting the stream** and skips it.

The queue item MA skipped is a **`.flac`** URL, and HA's `tts_proxy` returns **404** for it.

> ⚠️ **What we can and cannot show.** We did **not** capture the URL our caller passed on the
> failing turn — our own log truncated it just short of the extension, which is why this took a
> day to spot. Two readings therefore remain open and we are not claiming to have separated
> them: **(a)** HA returned a `.flac` for that call and MA simply wrapped it, or **(b)** HA
> returned an `.mp3`, as it has for every probe we have made since, and the `.flac` was derived
> downstream. What points at (b) is that three earlier `.flac` 404s sit beside
> `Playback announcement … <id>.mp3` lines (below) — but that is adjacency in a log, not proof
> of the same request. Our caller now logs the URL it passes, so the next occurrence settles it
> and we will follow up here.

This happens only when MA **does not** break out of queue flow into a single-item stream. When it
does break out, the `.mp3` is played as given and everything works.

### Reproduction

1. Resolve a Piper TTS URL through HA: `POST /api/tts_get_url` → `http://<ha>/api/tts_proxy/<id>.mp3`.
2. Call `music_assistant.play_media` on a Squeezelite player with that URL as `media_id`.
3. Most of the time it plays. Intermittently — **once in 8** queue-flow starts across our logs,
   and once in 7 announcements on the day we measured it — it produces silence, and the log
   shows the sequence below.

### Expected behavior

Either MA plays the `.mp3` it was given, or — if the queue flow needs a different container — it
fails loudly: an error back to the caller, and a player state that does not claim to be `playing`.

### Actual behavior

The item is skipped as unplayable, nothing is audible, **and the player still reports `playing`**,
so a caller polling player state cannot tell the announcement failed. Here that left a satellite
microphone muted for 52 s while the code waited for a clip that was never going to play.

### Relevant logs

The failing turn. The item is judged unplayable **91 ms** after the stream starts and the
stream is finished at **176 ms**. The extension is `.flac`
(see the caveat above about what the caller supplied):

```
16:01:50.897 INFO  [music_assistant.streams.audio] Start Queue Flow stream for Queue Ceiling Speakers - crossfade: disabled
16:01:50.988 WARN  [music_assistant.player_queues] Skipping unplayable item -x6odQg9FAYNmkJ6x-4KTw
                   (builtin://radio/http://<ha>:8123/api/tts_proxy/-x6odQg9FAYNmkJ6x-4KTw.flac)
                   ... repeated 20x over 85 ms ...
16:01:51.073 INFO  [music_assistant.streams.audio] Finished Queue Flow stream for Queue Ceiling Speakers
```

The underlying fetch failure, from an earlier occurrence where ffmpeg's output was captured:

```
WARN  [music_assistant.streams.audio.media_stream] [http @ ...] HTTP error 404 Not Found
      [in#0 @ ...] Error opening input: Server returned 404 Not Found
      Error opening input file http://<ha>:8123/api/tts_proxy/<id>.flac.
      Error opening input files: Server returned 404 Not Found
ERROR [music_assistant.player_queues] Failed to stream audio
WARN  [music_assistant.webserver] players/cmd/play_announcement: Failed to stream audio
```

A successful turn, 19 minutes later, same caller, same code path — it **breaks out**:

```
16:20:36.010 INFO  [music_assistant.streams.audio] Start Queue Flow stream for Queue Ceiling Speakers
16:20:36.161 INFO  [music_assistant.streams.audio] Live media item d1430e63... (radio) encountered
                   in flow stream - breaking out to single item stream
16:20:36.161 INFO  [music_assistant.streams.audio] Finished Queue Flow stream for Queue Ceiling Speakers
```

### Evidence from ten weeks of logs

Every `Start Queue Flow stream` in the period where this caller was active:

| what followed | count | result |
|---|---|---|
| `breaking out to single item stream` | **7** | played correctly |
| no break-out | **1** | `Skipping unplayable item`, `ext=flac`, silence |

Every log line mentioning `.flac`:

| | count |
|---|---|
| lines mentioning `.flac` | 36 |
| of those, a 404 / "unplayable" / "Error opening input" | **23** |
| unrelated (library music files that really are FLAC) | 13 |
| **`.flac` `tts_proxy` URLs that played successfully** | **0** |

Every `tts_proxy` URL MA logged, by extension:

| extension | distinct clips | failed |
|---|---|---|
| `.mp3` | 28 | 0 |
| `.flac` | 4 | **4** |

### Home Assistant returns `.mp3` for every call we have tested

`/api/tts_get_url` was probed 8 times against `tts.piper` — the exact text that failed, three texts
that succeeded, two never-before-spoken sentences, and the failing text repeated. **All 8 returned
`.mp3`.** Within those probes the extension does not depend on the text, on caching, or on
anything the caller controls. All 8 were taken after the failure, so they bound HA's behaviour
now — not its behaviour on the failing call.

### It is not specific to one caller

Three of the four `.flac` failures sit directly beside HA's own announcement path:

```
INFO [music_assistant.players] Playback announcement to player Ceiling Speakers
     (with pre-announce: True): http://<ha>:8123/api/tts_proxy/<id>.mp3
```

That is `tts.speak` with `media_player_entity_id`, i.e. `play_announcement`. It also receives an
`.mp3` and also ends up failing on a `.flac`, so this is not an artifact of using
`music_assistant.play_media` for TTS.

### The two questions for maintainers

1. **What decides whether a TTS item breaks out to a single-item stream?** Seven of eight did, and
   those all worked. If that is deterministic, understanding it is likely the whole fix.
2. **Why is a `.flac` variant of a `tts_proxy` URL requested at all**, given HA minted only the
   `.mp3` and will 404 anything else? If MA needs a specific container for flow mode, transcoding
   the fetched `.mp3` would avoid asking HA for a file that cannot exist.

Separately, and regardless of the above: **an item skipped as unplayable leaves the player reporting
`playing`.** A caller has no way to distinguish that from a clip in progress. Surfacing it in player
state, or returning an error from `play_media`, would let callers fail fast instead of waiting out a
timeout.

### Adjacent issues — checked, none is this

- `music-assistant/support#6415` — MA cannot ffprobe a `tts_proxy` URL (http/https mismatch). Same
  code path, different cause.
- `music-assistant/support#6320` — `play_media` with a plain audio URL plays a random library track.
  Same URL-resolution area; open regression since 2.10.
- `home-assistant/core#151757` — `tts.speak` to MA: bell then silence, attributed by the reporter to
  a cached URL handed over while still loading. Closest analogue; closed as not planned.
- `music-assistant/support#6359` — Squeezelite `STMu`/`STMd` race. Different symptom.
