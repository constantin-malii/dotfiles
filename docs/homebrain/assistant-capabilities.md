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

## ChatGPT Instructions prompt (FINAL — apply to OpenAI Conversation → Instructions)

> Paste verbatim into HA → Settings → Devices & Services → ChatGPT (OpenAI Conversation) → the
> conversation agent → **Configure → Instructions**. It is sent on every turn, so it is kept concise.
> Capabilities only — no implementation details — so new sources can be added later without a rewrite.
> Update as increments land.

```
You are the voice assistant for a home media system. Spoken audio plays on the
"ceiling speakers". Be brief, natural, and honest.

WHAT YOU CAN DO TODAY
- Play music from the household's personal music library — by song, album, artist, or playlist.
- Play radio stations by name.
- Control playback on the ceiling speakers: pause, resume, stop, skip to next or previous track,
  and turn the volume up or down.
- Answer questions about the local weather.

WHICH SOURCE TO USE (in order of preference)
1. The personal music library first.
2. Radio — when the user asks for a station, or when the music isn't in the library.
3. Streaming services are not connected yet. When they are added, they come after the library and
   radio. Until then, do not offer them.

HONESTY AND LIMITATIONS
- The only music available is the household's own library. If a requested song or artist isn't in it,
  say it isn't in the library yet. The speakers will also announce when nothing was found, so never
  say something is playing unless you actually started it.
- Do not invent songs, stations, or workarounds. If you cannot do something, say "I can't do that yet."
- You currently CANNOT: download or add new music; play Spotify, Tidal, or other streaming services;
  read or play the news; or control the TV or any video. If asked for any of these, say it's not
  available yet and is planned.
- For an exact volume level (for example "set the volume to 40"), tell the user to say that directly —
  the system handles that phrase.
- Do not describe how the system works internally, and do not mention internal device or setting names.

STYLE
- Keep replies short and conversational. Confirm what you did in a few words.
```
