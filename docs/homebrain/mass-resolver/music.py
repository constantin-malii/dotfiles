#!/usr/bin/env python3
# Music capability: resolve a query to a local (preferred-provider) item and play it. Python 3.5 safe.
import logging
from match import match_rank
from maconn import WS_CMD

LOG = logging.getLogger("resolver")


def _resolve_type(ma, query, media_type, settings, rid):
    ranked = []
    for it in ma.library(media_type):
        r = match_rank(query, it.get("name"))
        if r is not None:
            ranked.append((r, it))
    ranked.sort(key=lambda t: t[0])
    for _, it in ranked:
        name = it.get("name"); maps = it.get("provider_mappings") or []
        local = None
        for m in maps:
            if m.get("provider_domain") in settings.provider_preference and m.get("available"):
                local = m; break
        if local:
            uri = "%s://%s/%s" % (local.get("provider_instance"), media_type, local.get("item_id"))
            LOG.info("req=%s query=%r media_type=%s candidate=%r provider=%s uri=%s decision=ACCEPTED",
                     rid, query, media_type, name, local.get("provider_domain"), uri)
            return {"uri": uri, "provider": local.get("provider_domain"), "candidate": name, "media_type": media_type}
        LOG.info("req=%s query=%r media_type=%s candidate=%r decision=REJECTED reason=no-preferred-mapping",
                 rid, query, media_type, name)
    return None


def resolve_music(ma, query, media_type, settings, rid):
    if media_type in WS_CMD:
        types = [media_type] + [t for t in settings.type_order if t != media_type]
    else:
        types = list(settings.type_order)
    hit = None
    for mt in types:
        hit = _resolve_type(ma, query, mt, settings, rid)
        if hit:
            break
    if not hit:
        LOG.info("req=%s query=%r decision=REJECTED reason=no-local-match", rid, query)
        return {"ok": False, "intent": "music", "request_id": rid, "reason": "no local match",
                "spoken": "Sorry, I couldn't find " + (query or "that") + " in the local library."}
    res = {"ok": True, "intent": "music", "request_id": rid, "spoken": None, "played": False}
    res.update(hit)
    if settings.dry_run:
        LOG.info("[DRY-RUN] req=%s WOULD PLAY %s (provider=%s)", rid, hit["uri"], hit["provider"])
        return res
    pr = ma.play(settings.queue_id, hit["uri"])
    if pr and "error_code" in pr:
        LOG.error("req=%s PLAY FAILED code=%s details=%s", rid, pr.get("error_code"), pr.get("details"))
        res["ok"] = False; res["reason"] = "play failed"
        res["spoken"] = "I found " + hit["candidate"] + ", but couldn't start playback."
        return res
    LOG.info("req=%s PLAYING %s (provider=%s)", rid, hit["uri"], hit["provider"])
    res["played"] = True
    return res
