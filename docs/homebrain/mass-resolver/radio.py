#!/usr/bin/env python3
# Radio capability: play/find by name/country/genre/language, favorites-first then
# RadioBrowser, with dry-run and honest feedback. Python 3.5 safe.
import logging
import config
import favorites
import radiobrowser as rb

LOG = logging.getLogger("resolver")


def _dedupe(stations, cap):
    seen_uri = set(); seen_name = set(); out = []
    for s in stations:
        u = s.get("uri")
        n = (s.get("name") or "").strip().lower()
        if (not u) or (u in seen_uri) or (n and n in seen_name):
            continue
        seen_uri.add(u)
        if n:
            seen_name.add(n)
        out.append(s)
        if len(out) >= cap:
            break
    return out


def _candidates(ma, radio_cfg, params, cap):
    """Return (ordered stations, target_label)."""
    if params.get("station"):
        q = params["station"]
        return _dedupe(favorites.by_name(radio_cfg, q) + rb.search(ma, q, cap), cap), q
    if params.get("country"):
        word = params["country"]; code = config.resolve_country(radio_cfg, word)
        favs = favorites.by_country(radio_cfg, code) if code else []
        more = rb.country_stations(ma, code, cap) if code else []
        return _dedupe(favs + more, cap), word
    if params.get("language"):
        word = params["language"]; code = config.resolve_language(radio_cfg, word)
        favs = favorites.by_language(radio_cfg, code) if code else []
        more = rb.language_stations(ma, code, cap) if code else []
        return _dedupe(favs + more, cap), word
    if params.get("genre"):
        word = params["genre"]; canonical, synonyms = config.resolve_genre(radio_cfg, word)
        favs = favorites.by_genre(radio_cfg, synonyms)
        more = rb.genre_stations(ma, canonical, cap)
        return _dedupe(favs + more, cap), word
    return [], ""


def resolve_radio(ctx, params, rid):
    mode = params.get("mode") or "play"
    radio_cfg = ctx.radio_cfg or {}
    d = config.radio_defaults(radio_cfg)
    ma = ctx.ma_factory()
    try:
        ma.connect()
        cands, label = _candidates(ma, radio_cfg, params, d["find_internal"])
        LOG.info("req=%s radio mode=%s target=%r candidates=%d", rid, mode, label, len(cands))

        if mode == "find":
            if not cands:
                return {"ok": False, "intent": "radio", "request_id": rid, "reason": "no match",
                        "spoken": "I couldn't find any stations for " + (label or "that") + "."}
            names = [s["name"] for s in cands[:d["find_speak"]]]
            if len(names) == 1:
                spoken = "I found " + names[0] + "."
            else:
                spoken = "I found " + ", ".join(names[:-1]) + " and " + names[-1] + "."
            return {"ok": True, "intent": "radio", "request_id": rid, "spoken": spoken,
                    "speak_success": True, "stations": cands}

        # mode == play
        if not cands:
            return {"ok": False, "intent": "radio", "request_id": rid, "reason": "no match",
                    "spoken": "I couldn't find a station for " + (label or "that") + "."}
        chosen = cands[0]
        res = {"ok": True, "intent": "radio", "request_id": rid, "spoken": None, "played": False,
               "uri": chosen["uri"], "station": chosen["name"], "source": chosen["source"]}
        if params.get("dry_run"):
            LOG.info("[DRY-RUN] req=%s WOULD PLAY radio %r uri=%s source=%s", rid, chosen["name"], chosen["uri"], chosen["source"])
            return res
        pr = ma.play(ctx.settings.queue_id, chosen["uri"])
        if (not pr) or ("error_code" in pr):
            LOG.error("req=%s RADIO PLAY FAILED code=%s", rid, pr.get("error_code") if pr else None)
            res["ok"] = False; res["reason"] = "play failed"
            res["spoken"] = "I found " + chosen["name"] + ", but couldn't start it."
            return res
        LOG.info("req=%s RADIO PLAYING %r uri=%s source=%s", rid, chosen["name"], chosen["uri"], chosen["source"])
        res["played"] = True
        return res
    finally:
        ma.close()
