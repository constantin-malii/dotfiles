#!/usr/bin/env python3
# Music capability: resolve a query to a local (preferred-provider) item and play it. Python 3.5 safe.
import logging
import capability
import command_result as cr
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


class MusicCapability(capability.Capability):
    name = "music"

    def resolve(self, ctx, params):
        ma = ctx.ma_factory()
        if getattr(ma, "s", None) is None:
            ma.connect()
        try:
            q = params.get("query")
            mt = params.get("media_type") or ""
            if mt in WS_CMD:
                types = [mt] + [t for t in ctx.settings.type_order if t != mt]
            else:
                types = list(ctx.settings.type_order)
            hit = None
            for t in types:
                hit = _resolve_type(ma, q, t, ctx.settings, params.get("_rid", ""))
                if hit:
                    break
            dry_run = params.get("dry_run") or ctx.settings.dry_run
            return {"ma": ma, "query": q, "hit": hit, "dry_run": dry_run}
        except Exception:
            ma.close()
            raise

    def validate(self, ctx, resolved):
        if not resolved.get("hit"):
            q = resolved.get("query") or "that"
            resolved["ma"].close()
            return {"code": "not_found", "reason": "no local match",
                    "chat_text": q + " isn't in your local library yet.",
                    "spoken_text": "Sorry, I couldn't find " + q + " in the local library.",
                    "metadata": {"query": q}}
        return None

    def execute(self, ctx, resolved, rid):
        ma = resolved["ma"]
        hit = resolved["hit"]
        try:
            md = {"uri": hit["uri"], "provider": hit["provider"],
                  "candidate": hit["candidate"], "media_type": hit["media_type"]}
            if resolved["dry_run"]:
                md["played"] = False
                LOG.info("[DRY-RUN] req=%s WOULD PLAY %s (provider=%s)", rid, hit["uri"], hit["provider"])
                return cr.ok(self.name, rid, "Would play " + hit["candidate"] + ".",
                             spoken_text=None, metadata=md)
            pr = ma.play(ctx.settings.queue_id, hit["uri"])
            if pr and "error_code" in pr:
                md["played"] = False
                LOG.error("req=%s PLAY FAILED for %s", rid, hit["uri"])
                return cr.err(self.name, rid, "play_failed", "play failed",
                              "I found " + hit["candidate"] + ", but couldn't start it.",
                              spoken_text="I found " + hit["candidate"] + ", but couldn't start playback.",
                              metadata=md)
            md["played"] = True
            LOG.info("req=%s PLAYING %s (provider=%s)", rid, hit["uri"], hit["provider"])
            return cr.ok(self.name, rid, "Playing " + hit["candidate"] + ".",
                         spoken_text=None, metadata=md)
        finally:
            ma.close()


def resolve_music(ma, query, media_type, settings, rid):
    """Legacy wrapper: runs MusicCapability and maps CommandResult back to the Inc 0/1 dict."""
    class _Ctx(object):
        def __init__(self, _ma, _settings):
            self.settings = _settings
            self._ma = _ma
        def ma_factory(self):
            return self._ma

    res = capability.run(MusicCapability(), _Ctx(ma, settings),
                         {"query": query, "media_type": media_type, "_rid": rid}, rid)
    out = {"ok": res["ok"], "intent": "music", "request_id": rid,
           "spoken": res.get("spoken_text")}
    out.update(res.get("metadata") or {})
    if not res["ok"]:
        out["reason"] = (res.get("error") or {}).get("reason")
    return out
