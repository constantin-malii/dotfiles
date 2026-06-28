#!/usr/bin/env python3
# Match radio.json favorites by name/country/genre/language. Pure. Python 3.5 safe.
import config
from match import match_rank


def _st(fav):
    return {"name": fav.get("name"), "uri": fav.get("uri"), "source": "favorite"}


def by_name(radio_cfg, query):
    favs = config.favorites(radio_cfg)
    aliases = (radio_cfg or {}).get("aliases", {})
    target = aliases.get((query or "").strip().lower(), query)
    ranked = []
    for f in favs:
        r = match_rank(target, f.get("name"))
        if r is not None:
            ranked.append((r, f))
    ranked.sort(key=lambda t: t[0])
    return [_st(f) for _, f in ranked]


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
