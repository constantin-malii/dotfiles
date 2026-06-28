#!/usr/bin/env python3
# Match radio.json favorites by name/country/genre/language. Pure. Python 3.5 safe.
import config
from match import match_rank


def _st(fav):
    return {"name": fav.get("name"), "uri": fav.get("uri"), "source": "favorite"}


def by_name(radio_cfg, query):
    favs = config.favorites(radio_cfg)
    aliases = (radio_cfg or {}).get("aliases", {})
    q = (query or "").strip()
    aliases_lower = {}
    for k, v in aliases.items():
        aliases_lower[k.lower()] = v
    target = aliases_lower.get(q.lower(), q)
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
