#!/usr/bin/env python3
# RadioBrowser/MA radio browse+search client -> normalized station dicts. Python 3.5 safe.
import re


def norm_name(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def station_from_item(item):
    if not item or item.get("media_type") != "radio" or item.get("item_id") == "back":
        return None
    maps = item.get("provider_mappings") or []
    if not any(m.get("available") for m in maps):
        return None
    src = "favorite" if item.get("provider") == "library" else "radiobrowser"
    return {"name": norm_name(item.get("name")), "uri": item.get("uri"), "source": src}


def _items(result):
    res = (result or {}).get("result")
    if isinstance(res, dict):
        return res.get("items") or res.get("radio") or []
    return res or []


def browse(ma, path, limit):
    out = []
    for it in _items(ma.cmd("music/browse", path=path)):
        st = station_from_item(it)
        if st:
            out.append(st)
            if len(out) >= limit:
                break
    return out


def search(ma, query, limit):
    res = (ma.cmd("music/search", search_query=query, media_types=["radio"], limit=limit) or {}).get("result") or {}
    radios = res.get("radio") if isinstance(res, dict) else []
    out = []
    for it in (radios or []):
        st = station_from_item(it)
        if st:
            out.append(st)
            if len(out) >= limit:
                break
    return out


def country_stations(ma, code, limit):
    return browse(ma, "radiobrowser://category/country/" + code, limit)


def genre_stations(ma, tag, limit):
    return browse(ma, "radiobrowser://category/tag/" + tag, limit)


def language_stations(ma, code, limit):
    return browse(ma, "radiobrowser://category/language/" + code, limit)
