#!/usr/bin/env python3
# Music capability: resolve a query to a local (preferred-provider) item and play it. Python 3.5 safe.
import logging
import capability
import command_result as cr
import favorites
from match import match_rank, clean, compact
from maconn import WS_CMD

LOG = logging.getLogger("resolver")

# A curated playlist is played as its local-track list, capped. The cap bounds the PLAY (one
# play_media call), not the fetch: playlist_tracks takes no limit, so MA sends the whole list first.
PLAYLIST_TRACK_CAP = 500


def _local_mapping(it, settings):
    for m in it.get("provider_mappings") or []:
        if m.get("provider_domain") in settings.provider_preference and m.get("available"):
            return m
    return None


def _has_builtin(it):
    for m in it.get("provider_mappings") or []:
        if m.get("provider_domain") == "builtin":
            return True
    return False


def _is_curated(it):
    """A playlist the operator made in Music Assistant: a `builtin` mapping, is_editable exactly
    True and is_dynamic exactly False. MA's automatic lists (random_tracks, infinite_mix, ...) are
    non-editable (8/8 observed, 2026-09-27) and the infinite_mix family is also dynamic. Both flags
    must be present: a missing or non-boolean one fails closed (identity checks, not truthiness).
    The builtin mapping's item_id is NOT used: for a user playlist it is the playlist's name."""
    return (_has_builtin(it) and it.get("is_editable") is True
            and it.get("is_dynamic") is False)


def _library(ma, media_type, lib):
    """Each type's library is fetched once per resolve (lib is the per-request cache)."""
    if media_type not in lib:
        lib[media_type] = ma.library(media_type)
    return lib[media_type]


def _curated_tracks(ma, it, settings):
    """(local track uris in playlist order, total track count). Local = an available
    preferred-provider mapping; the list is always used, even when every track is local, so MA
    never picks a non-local source for a library track (spec 3.1-4).
    Fetched by the LIBRARY item_id with provider "library" -- not the builtin mapping's id, which
    MA need not keep equal to it; the mapping only decides whether the playlist is curated.
    Fetched uncapped: MA's playlist_tracks command takes no limit of its own, so the whole list
    arrives regardless -- "total" must reflect that full count, not the played slice. The cap
    below bounds only the PLAY (one play_media call), not the fetch."""
    all_tracks = ma.playlist_tracks(it.get("item_id"), limit=None)
    total = len(all_tracks)
    uris = []
    for t in all_tracks[:PLAYLIST_TRACK_CAP]:
        m = _local_mapping(t, settings)
        if m:
            uris.append("%s://track/%s" % (m.get("provider_instance"), m.get("item_id")))
    return uris, total


def _resolve_type(ma, query, media_type, settings, rid, lib, exact=False):
    """-> (hit or None, name of a curated playlist rejected for having no local tracks, or None).
    exact=True accepts only an exact clean()/compact() match (alias targets must never
    fuzzy-match; match_rank itself is not used here, since it treats "<title> by <artist>"
    specially and can rank an exact target string below 0)."""
    ranked = []
    if exact:
        cq, qc = clean(query), compact(query)
        for it in _library(ma, media_type, lib):
            name = it.get("name")
            if name and (clean(name) == cq or compact(name) == qc):
                ranked.append((0, it))
    else:
        for it in _library(ma, media_type, lib):
            r = match_rank(query, it.get("name"))
            if r is not None:
                ranked.append((r, it))
    ranked.sort(key=lambda t: t[0])
    curated_tried = False
    no_local = None
    for _, it in ranked:
        name = it.get("name")
        local = _local_mapping(it, settings)
        if local:
            uri = "%s://%s/%s" % (local.get("provider_instance"), media_type, local.get("item_id"))
            LOG.info("req=%s query=%r media_type=%s candidate=%r provider=%s uri=%s decision=ACCEPTED",
                     rid, query, media_type, name, local.get("provider_domain"), uri)
            return {"uri": uri, "provider": local.get("provider_domain"), "candidate": name,
                    "media_type": media_type}, None
        if media_type == "playlist" and _has_builtin(it) and not _is_curated(it):
            # Distinct reason, so a future MA field rename shows in the log instead of a playlist
            # silently vanishing.
            LOG.info("req=%s query=%r media_type=playlist candidate=%r is_editable=%r is_dynamic=%r "
                     "decision=REJECTED reason=not-curated", rid, query, name,
                     it.get("is_editable"), it.get("is_dynamic"))
            continue
        if media_type == "playlist" and not curated_tried and _is_curated(it):
            curated_tried = True                # tracks are fetched for the top curated candidate only
            uris, total = _curated_tracks(ma, it, settings)
            if uris:
                puri = it.get("uri") or ("library://playlist/%s" % it.get("item_id"))
                LOG.info("req=%s query=%r media_type=playlist candidate=%r provider=builtin uri=%s "
                         "local=%d/%d decision=ACCEPTED", rid, query, name, puri, len(uris), total)
                return {"uri": puri, "uris": uris, "provider": "builtin", "candidate": name,
                        "media_type": "playlist", "local": len(uris), "total": total}, None
            no_local = name
            LOG.info("req=%s query=%r media_type=playlist candidate=%r local=0/%d decision=REJECTED "
                     "reason=no-local-tracks", rid, query, name, total)
            continue
        LOG.info("req=%s query=%r media_type=%s candidate=%r decision=REJECTED reason=no-preferred-mapping",
                 rid, query, media_type, name)
    return None, no_local


def _resolve_all(ma, query, types, settings, rid, lib):
    no_local = None
    for t in types:
        hit, nl = _resolve_type(ma, query, t, settings, rid, lib)
        if hit:
            return hit, None
        no_local = no_local or nl
    return None, no_local


def _types(settings, first):
    order = list(settings.type_order)
    if first in WS_CMD:
        return [first] + [t for t in order if t != first]
    return order


def _strip_edges(phrase):
    """(stripped, had_playlist_suffix). Leading 'the ' and trailing ' playlist' removed, whole words,
    on the clean() form. Used ONLY for the alias lookup and when the phrase ends in 'playlist' --
    ordinary queries resolve unstripped so today's ranking is unchanged ("the wall")."""
    c = clean(phrase)
    had = False
    if c == "playlist" or c.endswith(" playlist"):
        c = c[:-len("playlist")].strip()
        had = True
    if c.startswith("the "):
        c = c[len("the "):].strip()
    return c, had


_PLAYLIST_STOPWORDS = ("the", "my", "a", "our")


def _lookup(ma, phrase, media_type, settings, rid, lib):
    """One attempt for a phrase -> (hit, no_local_name, alias_key or None).
    1) exact alias -> playlist only, exact target; 2) trailing 'playlist' -> stripped form, playlist
    first; 3) otherwise today's resolution of the unstripped phrase."""
    stripped, had_playlist = _strip_edges(phrase)
    aliases = getattr(settings, "playlist_aliases", None)
    if not isinstance(aliases, dict):
        aliases = {}
    # Alias keys are matched on their OWN stripped form ("the costea mix" / "costea mix playlist"
    # must match a spoken "costea mix"), but the ORIGINAL key is kept for the reported alias name
    # (the chat text says "Playing <original key>").
    norm = {}
    orig_of = {}
    for k, v in aliases.items():
        sk, _ = _strip_edges(k)
        if sk:
            norm[sk] = v
            orig_of[sk] = k
    a = favorites.match_alias(norm, stripped) if (norm and stripped) else None
    if a:
        skey, target = a
        key = orig_of.get(skey, skey)
        hit, nl = _resolve_type(ma, target, "playlist", settings, rid, lib, exact=True)
        if hit or nl:
            LOG.info("req=%s alias=%r -> %r", rid, key, target)
        else:
            LOG.info("req=%s alias=%r target=%r decision=REJECTED reason=alias-target-missing", rid, key, target)
        return hit, nl, key
    if had_playlist:
        if not stripped or stripped in _PLAYLIST_STOPWORDS:
            return None, None, None
        hit, nl = _resolve_all(ma, stripped, _types(settings, "playlist"), settings, rid, lib)
        return hit, nl, None
    hit, nl = _resolve_all(ma, phrase, _types(settings, media_type), settings, rid, lib)
    return hit, nl, None


class MusicCapability(capability.Capability):
    name = "music"

    def resolve(self, ctx, params):
        ma = ctx.ma_factory()
        if getattr(ma, "s", None) is None:
            ma.connect()
        try:
            q = params.get("query") or ""
            mt = params.get("media_type") or ""
            rid = params.get("_rid", "")
            lib = {}
            note = None
            hit, nl, alias = _lookup(ma, q, mt, ctx.settings, rid, lib)
            if not hit and not nl and alias is None:
                c = clean(q)
                if c.startswith("shuffle "):        # shuffle is MR-08b; tolerate the word meanwhile
                    hit, nl, alias = _lookup(ma, c[len("shuffle "):], mt, ctx.settings, rid, lib)
                    if hit:
                        note = "shuffle"
            dry_run = params.get("dry_run") or ctx.settings.dry_run
            return {"ma": ma, "query": q, "hit": hit, "no_local": nl, "alias": alias, "note": note,
                    "dry_run": dry_run, "rid": rid, "media_type": mt}
        except Exception:
            ma.close()
            raise

    def validate(self, ctx, resolved):
        if resolved.get("hit"):
            return None
        resolved["ma"].close()
        if resolved.get("no_local"):
            name = resolved.get("alias") or resolved.get("query") or resolved["no_local"]
            msg = name + " has no songs in the local library yet."
            return {"code": "not_found", "reason": "no local tracks", "chat_text": msg, "spoken_text": msg,
                    "metadata": {"query": resolved.get("query")}}
        LOG.info("req=%s MISS query=%r media_type=%r alias=%r", resolved.get("rid", ""),
                 resolved.get("query"), resolved.get("media_type") or "", resolved.get("alias"))
        q = resolved.get("alias") or resolved.get("query") or "that"
        return {"code": "not_found", "reason": "no local match",
                "chat_text": q + " isn't in your local library yet.",
                "spoken_text": "Sorry, I couldn't find " + q + " in the local library.",
                "metadata": {"query": q}}

    def execute(self, ctx, resolved, rid):
        ma = resolved["ma"]
        hit = resolved["hit"]
        display = resolved.get("alias") or hit["candidate"]
        try:
            md = {"uri": hit["uri"], "provider": hit["provider"],
                  "candidate": hit["candidate"], "media_type": hit["media_type"]}
            if "uris" in hit:
                md["uris"] = hit["uris"]; md["local"] = hit["local"]; md["total"] = hit["total"]
            if resolved["dry_run"]:
                md["played"] = False
                LOG.info("[DRY-RUN] req=%s WOULD PLAY %s (provider=%s)", rid, hit["uri"], hit["provider"])
                return cr.ok(self.name, rid, "Would play " + display + ".", spoken_text=None, metadata=md)
            pr = ma.play(ctx.settings.queue_id, hit.get("uris") or hit["uri"])
            if pr and "error_code" in pr:
                md["played"] = False
                LOG.error("req=%s PLAY FAILED for %s code=%s details=%r (MA refused the play; "
                          "resolution was fine)", rid, hit["uri"], pr.get("error_code"),
                          pr.get("details") or pr.get("error") or pr.get("message"))
                return cr.err(self.name, rid, "play_failed", "play failed",
                              "I found " + display + ", but couldn't start it.",
                              spoken_text="I found " + display + ", but couldn't start playback.",
                              metadata=md)
            md["played"] = True
            LOG.info("req=%s PLAYING %s (provider=%s)", rid, hit["uri"], hit["provider"])
            text = "Playing " + display
            if "uris" in hit and hit["local"] < hit["total"]:
                text += " \u2014 %d of %d tracks; %d aren't in your local library yet" % (
                    hit["local"], hit["total"], hit["total"] - hit["local"])
            if resolved.get("note") == "shuffle":
                text += " (shuffle isn't supported yet)"
            return cr.ok(self.name, rid, text + ".", spoken_text=None, metadata=md)
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
