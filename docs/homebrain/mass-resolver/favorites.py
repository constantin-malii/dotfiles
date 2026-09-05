#!/usr/bin/env python3
# Match radio.json favorites by name/country/genre/language. Pure. Python 3.5 safe.
import logging
import config
from match import match_rank, compact

LOG = logging.getLogger("resolver")


def _st(fav):
    return {"name": fav.get("name"), "uri": fav.get("uri"), "source": "favorite",
            "say_as": fav.get("say_as")}


def all_favorites(radio_cfg):
    """Every favorite, in radio.json order -- the order the listing reads them out in."""
    return [_st(f) for f in config.favorites(radio_cfg)]


def spoken_name(station):
    """What to SAY for a station: its short handle when it has one, else its real name.
    Cyrillic names are unusable aloud (Piper mangles them and the user cannot say them back),
    so a handle is the only useful thing to read out for those."""
    # Never return None: this feeds ", ".join() on the live media path, where a None would raise
    # a TypeError mid-turn instead of merely reading badly.
    st = station or {}
    return st.get("say_as") or st.get("name") or ""


def _alias_map(radio_cfg):
    """Explicit `aliases` plus each favorite's `say_as`, so one handle both gets read out and
    gets understood. Explicit aliases win: they are the hand-tuned STT-mangling repairs."""
    out = {}
    for f in config.favorites(radio_cfg):
        h = f.get("say_as")
        if h and f.get("name"):
            out[h] = f.get("name")
    out.update((radio_cfg or {}).get("aliases", {}))
    return out


_MIN_ALIAS_KEY = 4          # shorter keys would collide with ordinary words inside a long query


def resolve_alias(radio_cfg, query):
    """Map a spoken/STT-mangled station name onto its canonical name via radio.json `aliases`
    (returns the query unchanged when there is no alias). Exposed so the MA/RadioBrowser search
    can use the SAME canonical name as the local favorites match -- otherwise an alias only ever
    helps stations that happen to be listed in radio.json.

    Matching is deliberately NOT whole-string equality. The assistant relays the transcription
    verbatim, so the station argument arrives noisy and over-long -- spelled-out letters and all,
    e.g. "Radio Norok N O R O C". An alias key is therefore looked for INSIDE the query, longest
    key first so the most specific alias wins, and also against a compacted form so a spelled-out
    "N O R O C" collapses to "noroc". Keys shorter than 4 chars are skipped: they would fire on
    ordinary words."""
    aliases = _alias_map(radio_cfg)
    q = (query or "").strip()
    if not q or not aliases:
        return q
    ql = q.lower()
    lowered = {}
    for k, v in aliases.items():
        lowered[k.lower()] = v
    if ql in lowered:                       # exact alias, the cheap and unambiguous case
        return lowered[ql]
    qc = compact(ql)
    # Longest key first so the most specific alias wins; then alphabetical, so equal-length keys
    # (e.g. "russian radio" / "russian songs") resolve the same way on every run rather than
    # inheriting dict order.
    for k in sorted(lowered.keys(), key=lambda x: (-len(x), x)):
        kc = compact(k)
        if len(kc) < _MIN_ALIAS_KEY:
            continue
        if k in ql or (kc and kc in qc):
            LOG.info("radio alias matched %r inside %r -> %r", k, q, lowered[k])
            return lowered[k]
    return q


def by_name(radio_cfg, query):
    favs = config.favorites(radio_cfg)
    q = (query or "").strip()
    target = resolve_alias(radio_cfg, q)
    tl = target.strip().lower()
    out = []
    seen = set()
    # 1) exact case-insensitive raw-name match (works for non-ASCII/Cyrillic names)
    for f in favs:
        if (f.get("name") or "").strip().lower() == tl and f.get("uri") not in seen:
            seen.add(f.get("uri")); out.append(_st(f))
    # 2) ASCII fuzzy fallback via match_rank
    ranked = []
    for f in favs:
        if f.get("uri") in seen:
            continue
        r = match_rank(target, f.get("name"))
        if r is not None:
            ranked.append((r, f))
    ranked.sort(key=lambda t: t[0])
    for _, f in ranked:
        if f.get("uri") not in seen:
            seen.add(f.get("uri")); out.append(_st(f))
    return out


def by_country(radio_cfg, code):
    return [_st(f) for f in config.favorites(radio_cfg) if f.get("country") == code]


def by_genre(radio_cfg, synonyms):
    want = set(str(x).lower() for x in (synonyms or []))
    out = []
    for f in config.favorites(radio_cfg):
        genres = set(str(g).lower() for g in (f.get("genres") or []))
        if genres & want:
            out.append(_st(f))
    return out


def by_language(radio_cfg, code):
    return [_st(f) for f in config.favorites(radio_cfg) if f.get("language") == code]
