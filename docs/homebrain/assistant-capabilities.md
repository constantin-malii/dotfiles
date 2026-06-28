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

> Status: the Instructions prompt below (**v4**) is the live OpenAI Conversation prompt (Inc 0
> music/transport/weather + Inc 1 radio). Edit it via the HA UI (paste) — not the config API.

---

## Currently exposed to ChatGPT (verified 2026-06-27)

12 entities are exposed to the conversation assistant:

| Tool (entity) | What it does |
|---|---|
| `script.play_music` | Play LOCAL music by song/album/artist/playlist (fires `mass_play_request` → resolver) |
| `script.play_radio` | Play radio by **name / country / genre / language** (resolver: favorites-first → RadioBrowser) |
| `script.find_stations` | **Find/list** stations by genre/country; speaks the top 3 |
| `script.ceiling_play_radio` | Legacy: play a station by name (kept as fallback, not retired) |
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
| **News** headlines (spoken) and news stations | Inc 2 |
| **Search & acquire** a song/artist (Lidarr) | Inc 3 |
| **"What's playing"/status**, sleep timer, shuffle favorites | Inc 4 |
| Streaming services (Tidal/Qobuz/Spotify), YouTube Music | later / disabled |

Music is **local-only** today. If asked for something not in the library, say it isn't available
locally yet and that acquisition is on the roadmap.

## Routing rules (encoded in tool descriptions + the prompt below)

- **Music:** call `play_music` with the user's phrase as the query; leave `media_type` empty unless the
  user explicitly says "album"/"artist"/"playlist".
- **Radio:** call `play_radio` (station for a name; country/genre/language for those); call `find_stations` for "find/list stations". `ceiling_play_radio` is a legacy fallback.
- **Transport / volume:** use the `ceiling_*` tools; never use a raw media_player service.
- **Don't invent content.** If nothing matches, the speaker announces the miss — don't report success.
- **Capability questions:** answer from the "currently exposed" + "not available yet" lists above.

## Validation log

**2026-06-27, round 1** (prompt v1 applied). Ran 6 conversational tests against
`conversation.openai_conversation`:

| Test | Reply | Verdict |
|---|---|---|
| What can you do? | Lists library music, radio, playback control, weather | ✅ accurate |
| Play Rammstein | "Rammstein isn't in the music library yet." | ❌ **wrong** — Rammstein IS local; tool never called (no `mass_play_request` in the log) |
| Play My Way | "That song isn't in the library yet." | ⚠️ true by coincidence, but guessed (tool not called) |
| Download this album | "I can't do that yet." | ✅ |
| Play Spotify | "I can't do that yet. I can only play … library or radio." | ✅ |
| Turn on the TV | "I can only control the ceiling speakers." | ✅ |

**Gap:** the v1 line *"if a song or artist isn't in it, say it isn't in the library yet"* made the
model **judge availability itself** and decline **without calling the play tool**. **Fix:** added the
`PLAYING MUSIC` block (always use the tool, never pre-judge) and removed the denial-inducing line
(prompt v2).

**Known Inc-0 limitation (documented, fix later):** the play tool is fire-and-forget — ChatGPT does
not receive a found/not-found result, so for a *genuinely missing* item its text may optimistically
say "Playing X" while the **speaker** announces "couldn't find X". The speaker is the honest channel.
A future increment can make play return a result so ChatGPT's text is also exact.

**2026-06-27, round 2** (prompt v2 applied). Re-ran the 6 tests with resolver-log capture:

| Test | Reply | Log evidence | Verdict |
|---|---|---|---|
| What can you do? | library music, radio, playback, weather | — | ✅ |
| Play Rammstein | "Playing Rammstein." | `event→music` → `PLAYING …/artist/Rammstein` | ✅ tool fired + played |
| Play My Way | "Playing My Way." | `event→music` → `REJECTED no-local-match` → Piper "couldn't find My Way" | ✅ system honest; text optimistic (known limitation above) |
| Download this album | "I can't do that yet." | no event | ✅ |
| Play Spotify | "I can't do that yet." | no event | ✅ |
| Turn on the TV | "I can only control the ceiling speakers." | no event | ✅ |

**Result: PASS.** The play tool now fires for play requests (no more preemptive denial). Remaining
caveat is only the documented fire-and-forget text optimism for missing items.

**2026-06-28 — Inc 1 radio exposed** (`script.play_radio` + `script.find_stations`), prompt v3 (added
the two radio capability lines). Conversational tests vs `conversation.openai_conversation`:

| Test | Reply / log | Verdict |
|---|---|---|
| What can you do? | lists library, radio, playback, weather | ✅ |
| play Romanian radio | play country=Romania → Deep House Bucharest (fav) | ✅ |
| play jazz | play genre=jazz → 101 Smooth Jazz (fav) | ✅ |
| play country radio | play genre=country → .977 Country (RadioBrowser) | ✅ "country"=genre |
| play Hit FM | **misrouted** → `find(genre=pop, country=Ukraine)` (spoke 3 incl. Hit FM); text wrongly said "can't play" | ❌ routing |
| find jazz stations | speaker correctly said "I found 101 SMOOTH JAZZ, Classic Vinyl HD and Jazz Radio Blues"; **ChatGPT text said "couldn't find any"** | ⚠️ fire-and-forget text on find |
| play Wackadoodle FM | ChatGPT declined, **no tool call** | ⚠️ didn't try |
| Inc 0 regression: play Rammstein / volume up / pause / resume / stop / what-can-you-do | all correct (Rammstein played; 0.35→0.44; paused/playing/idle) | ✅ no regression |

**Gaps (all ChatGPT routing — resolver behaved correctly each time):** (1) play-by-name went to `find`
instead of `play_radio`; (2) `find` text contradicts the (correct) spoken list; (3) unknown station →
no attempt. **Fix:** prompt **v4** adds explicit `PLAYING RADIO` (named station → always use play-radio,
don't search/pre-judge) and `FINDING STATIONS` (speaker reads results; don't assert found/not-found)
blocks. Re-validation of Hit FM / find jazz / unknown-station pending after v4 is pasted.

**2026-06-28 — prompt v4 + legacy `ceiling_play_radio` un-exposed from ChatGPT.** With v4 alone, `find`
text became honest ("I'm finding some jazz stations") and unknown stations now call the tool (Piper
"couldn't find a station for X"); but "play Hit FM" had been grabbing the **legacy** `ceiling_play_radio`.
After un-exposing it (only `play_radio`/`find_stations` remain for ChatGPT; the script stays for the
local sentence-trigger layer), **"play Hit FM" routes to `play_radio` and plays the favorite** —
named-station routing fixed. Residual: **gpt-4o-mini nondeterminism** — it occasionally declines a
genre-play or says "couldn't find" for a station it actually played. Decision (user): **keep 4o-mini**;
this residual maps to two tracked backlog items — synchronous play-result (fixes the text;
model-agnostic) and a gpt-4o evaluation **gated** behind that work and only if tool-selection failures
persist. Inc 1 closed on these terms.

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

> Merges the good parts of the prior prompt (ceiling-speakers-only; no other devices; non-home
> questions answered from general knowledge; plain-text/concise) with the local-music capability and
> honest source-preference/limitations. Model settings unchanged: `top_p=1`, `temperature=0.3`.

```
You are the voice assistant for this home. Spoken replies play on the "ceiling
speakers". Answer in plain text, briefly and naturally.

WHAT YOU CAN DO
- Play music from the household's personal music library — by song, album, artist, or playlist.
- Play radio stations — by name, by country or nationality, by genre, or by language.
- Find and list radio stations by genre or country (the speakers read out the top few options).
- Control playback on the ceiling speakers: pause, resume, stop, skip to next or previous track,
  and turn the volume up or down.
- Tell the local weather.
- For other, non-home questions, answer briefly from general knowledge.

PLAYING MUSIC
- When the user asks to play a song, album, artist, or playlist, ALWAYS use the music-play tool with
  exactly what they asked for. Do NOT decide for yourself whether it exists — the system looks it up,
  and if it isn't found the speakers announce that out loud. After using the tool, confirm briefly
  (for example, "Playing Rammstein."). Never refuse a play request, and never say something isn't in
  the library, without first using the tool to try.

PLAYING RADIO
- To play a specific station by name, ALWAYS use the play-radio tool with that exact station name — do
  NOT search for it, list alternatives, or judge yourself whether it exists. For "Romanian/Russian
  radio" pass the country; for a genre like jazz, news, or country pass the genre; for a language pass
  the language. The speakers announce if nothing was found. After using the tool, confirm briefly
  (for example, "Playing Hit FM.").

FINDING STATIONS
- When the user asks to find or list stations, use the find-stations tool. The speakers read the
  results aloud, so just say you're finding them (for example, "Here are some jazz stations.") — do
  NOT state whether any were or weren't found.

WHICH SOURCE TO USE (in order of preference)
1. The household's personal music library first.
2. Radio — for a station by name, or a country, genre, or language request.
3. Streaming services aren't connected yet; when added, they come after the library and radio.
   Don't offer them until then.

WHAT YOU CANNOT DO
- You control ONLY the ceiling speakers. You have no access to TVs, video, soundbars, thermostats,
  phones, or any other device. If asked to control anything else, say you can only control the
  ceiling speakers.
- You cannot download or add new music; play Spotify, Tidal, or other streaming services; or read or
  play the news. If asked for any of these, say it's not available yet and is planned.
- For an exact volume level (e.g. "set the volume to 40"), tell the user to say that directly — the
  system handles that phrase.

RULES
- Don't invent stations or workarounds. For things you truly cannot do (listed above), say "I can't
  do that yet."
- Don't claim a song is playing unless you actually used the play tool.
- Don't describe how the system works internally, and don't mention device or setting names.
```
