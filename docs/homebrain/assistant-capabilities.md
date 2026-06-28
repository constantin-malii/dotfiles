# Homebrain Assistant — Capabilities & ChatGPT Knowledge

**Purpose:** the source of truth for what the ChatGPT voice assistant can do on the ceiling-speaker
media system, how it should route requests, and what it should tell users about capabilities.
Keep this in sync with the live system as each increment lands.

**Last verified:** 2026-06-27 (Inc 0 complete; exposed surface probed live).

---

## How ChatGPT actually "knows" the system

There is **no separate file ChatGPT reads at runtime.** Its knowledge comes from exactly two places,
and this repo doc is the human source of truth we keep them in sync with:

1. **Exposed entities + their names/aliases/descriptions.** Home Assistant presents every entity
   exposed to the *conversation* assistant to ChatGPT as a callable tool. The entity's friendly name,
   aliases, and (for scripts) the **`description` field** are what ChatGPT uses to decide when/how to
   call it. Good descriptions ⇒ good behavior. *(Improving a script's description is the cheapest way
   to improve routing.)*
2. **The OpenAI Conversation "Instructions" (system prompt).** A free-text field in the integration's
   config (HA → Settings → Devices & Services → ChatGPT/OpenAI Conversation → Configure → Instructions).
   This is where to put system/setup knowledge, scope, routing rules, and limits so ChatGPT can answer
   *"what can you do?"* accurately. A paste-ready draft is at the bottom of this doc.

> Status: the curated Instructions prompt below is **drafted but NOT yet applied** to the live config
> (applying it is a deliberate "expose to ChatGPT" step, done as its own validated change).

---

## Currently exposed to ChatGPT (verified 2026-06-27)

10 entities are exposed to the conversation assistant:

| Tool (entity) | What it does |
|---|---|
| `script.play_music` | Play LOCAL music by song/album/artist/playlist (fires `mass_play_request` → resolver) |
| `script.ceiling_play_radio` | Play a radio station **by name** |
| `script.ceiling_pause` / `ceiling_resume` / `ceiling_stop` | Transport |
| `script.ceiling_next` / `ceiling_previous` | Skip within a local queue |
| `script.ceiling_volume_up` / `ceiling_volume_down` | **Relative** volume change (±%, default 10) |
| `weather.forecast_home` | Home weather (ChatGPT can answer weather questions) |

**Two-layer voice:** bare phrases ("pause", "volume up", "set volume to 40", "play X radio") are first
handled by a fast **local sentence-trigger automation** (no LLM) for low latency and determinism;
ChatGPT is the fallback for everything else and for natural-language requests.

**Deliberately NOT exposed:** `ceiling_set_volume` (absolute set) — removed from ChatGPT to stop the
"volume up 10%" → "sets to 10%" confusion; absolute set still works via the local phrase
"set volume to N". The raw `media_player.ceiling_speakers` is also not exposed (keeps ChatGPT on the
guarded resolver surface).

## Honest failure feedback (Inc 0)

When `play_music` can't find a match in the **local** library, the resolver speaks the truth on the
ceiling speakers ("Sorry, I couldn't find X in the local library") via local Piper TTS. So ChatGPT must
**not** claim success it can't verify — the speaker itself reports misses.

## Not available yet (roadmap — tell users "coming soon", don't pretend)

| Capability | Increment |
|---|---|
| Radio by **country / genre**, list/discover stations | Inc 1 |
| **News** headlines (spoken) and news stations | Inc 2 |
| **Search & acquire** a song/artist (Lidarr) | Inc 3 |
| **"What's playing"/status**, sleep timer, shuffle favorites | Inc 4 |
| Streaming services (Tidal/Qobuz/Spotify), YouTube Music | later / disabled |

Music is **local-only** today. If asked for something not in the library, say it isn't available
locally yet and that acquisition is on the roadmap.

## Routing rules (encoded in tool descriptions + the prompt below)

- **Music:** call `play_music` with the user's phrase as the query; leave `media_type` empty unless the
  user explicitly says "album"/"artist"/"playlist".
- **Radio:** call `ceiling_play_radio` with the station name.
- **Transport / volume:** use the `ceiling_*` tools; never use a raw media_player service.
- **Don't invent content.** If nothing matches, the speaker announces the miss — don't report success.
- **Capability questions:** answer from the "currently exposed" + "not available yet" lists above.

## Maintenance

When each increment lands: (1) update this doc, (2) update the affected script **descriptions**, and
(3) re-sync the Instructions prompt below. Verify the live exposed set anytime with
`mass-resolver/tools/snapshot.py`-style probes or the `homeassistant/expose_entity/list` WS command.

---

## Paste-ready ChatGPT Instructions prompt (DRAFT — not yet applied)

> Paste into HA → OpenAI Conversation → Configure → Instructions. Keep it short (it is sent on every
> turn). Update as increments land.

```
You are the voice assistant for a home media system. Audio plays on the "ceiling speakers".

What you can do today:
- Play LOCAL music (songs, albums, artists, playlists) with the play_music tool. Pass the user's
  words as the query; leave media_type empty unless they explicitly say album, artist, or playlist.
- Play a radio station BY NAME with the ceiling_play_radio tool.
- Control playback: pause, resume, stop, next, previous, and raise/lower volume (relative) with the
  ceiling_* tools.
- Answer home weather questions.

Rules:
- The music library is LOCAL only. If a requested song/artist isn't found, the speaker will announce
  it itself — do not claim something is playing unless you used a tool to start it.
- Do not invent songs or stations you can't play.
- You cannot (yet): search/download new music, play news, filter radio by country or genre, list
  stations, report what's currently playing, set sleep timers, or use streaming services like Spotify
  or YouTube Music. If asked, say it's not available yet and is planned.
- For absolute volume (e.g. "set volume to 40"), tell the user to say it directly — the device handles
  that phrase locally.
- Keep answers brief and natural. Don't mention internal tool names, IDs, or tokens.
```
