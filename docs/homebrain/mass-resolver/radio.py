#!/usr/bin/env python3
# Radio capability: play/find by name/country/genre/language, favorites-first then
# RadioBrowser, with dry-run and honest feedback. Python 3.5 safe.
import logging, threading
import capability
import command_result as cr
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
        # Search MA with the alias-resolved name too: STT mangles station names ("norok" for
        # "Radio Noroc Moldova"), and MA's search is exact enough to return 0 hits for the variant
        # while returning the station for its real name.
        sq = favorites.resolve_alias(radio_cfg, q)
        if sq != q:
            LOG.info("radio alias %r -> %r", q, sq)
        return _dedupe(favorites.by_name(radio_cfg, q) + rb.search(ma, sq, cap), cap), q
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


class RadioCapability(capability.Capability):
    name = "radio"

    def __init__(self, timer_factory=None):
        self._timer_factory = timer_factory or threading.Timer

    def _confirm_play_later(self, ctx, rid, station, uri):
        """`RADIO PLAYING` only ever meant "MA accepted the request" -- it was logged straight off
        the play call's return, so a station that resolved fine and produced NO AUDIO still logged
        as a success. Read the player back a few seconds later and log what actually happened.

        Runs on a timer thread so the synchronous tool call pays no extra latency; diagnostic only,
        it never changes the result already returned to the caller."""
        secs = int(getattr(ctx.settings, "radio_confirm_after_ms", 8000)) / 1000.0
        if secs <= 0:
            return
        zone = getattr(ctx.settings, "ceiling_entity", "") or ""
        if not zone:
            return

        def check():
            try:
                st = ctx.ha.get_entity_state(zone) or {}
                cid = (st.get("attributes") or {}).get("media_content_id") or ""
                state = st.get("state")
                match = bool(cid) and (uri in cid or cid in uri)
                if state == "playing" and match:
                    LOG.info("RADIO CONFIRM req=%s %r is playing (cid=%s)", rid, station, cid)
                else:
                    LOG.warning("RADIO CONFIRM req=%s %r NOT confirmed after %.0fs: state=%s cid=%s "
                                "requested=%s -- MA accepted the play but the zone is not playing it",
                                rid, station, secs, state, cid, uri)
            except Exception as e:
                LOG.warning("RADIO CONFIRM req=%s read failed (%r)", rid, e)

        try:
            t = self._timer_factory(secs, check)
            t.daemon = True                      # never hold up a resolver shutdown
            t.start()
        except Exception as e:
            LOG.warning("RADIO CONFIRM req=%s could not arm check (%r)", rid, e)

    def resolve(self, ctx, params):
        radio_cfg = ctx.radio_cfg or {}
        d = config.radio_defaults(radio_cfg)
        ma = ctx.ma_factory()
        rid = params.get("_rid", "")
        try:
            if getattr(ma, "s", None) is None:
                ma.connect()
            cands, label = _candidates(ma, radio_cfg, params, d["find_internal"])
            mode = params.get("mode") or "play"
            dry_run = bool(params.get("dry_run"))
            LOG.info("req=%s radio mode=%s target=%r candidates=%d", rid, mode, label, len(cands))
            return {"ma": ma, "mode": mode, "candidates": cands, "label": label,
                    "dry_run": dry_run, "find_speak": d["find_speak"]}
        except Exception:
            ma.close()
            raise

    def validate(self, ctx, resolved):
        if not resolved.get("candidates"):
            label = resolved.get("label") or "that"
            resolved["ma"].close()
            return {"code": "not_found", "reason": "no match",
                    "chat_text": "I couldn't find a station for " + label + ".",
                    "spoken_text": "I couldn't find a station for " + label + ".",
                    "metadata": {"label": label}}
        return None

    def execute(self, ctx, resolved, rid):
        ma = resolved["ma"]
        mode = resolved["mode"]
        cands = resolved["candidates"]
        label = resolved.get("label") or "that"
        find_speak = resolved.get("find_speak") or 3
        try:
            if mode == "find":
                names = [s["name"] for s in cands[:find_speak]]
                if len(names) == 1:
                    spoken = "I found " + names[0] + "."
                    chat = "Here are some stations: " + names[0] + "."
                else:
                    spoken = "I found " + ", ".join(names[:-1]) + " and " + names[-1] + "."
                    chat = "Here are some stations: " + ", ".join(names[:-1]) + " and " + names[-1] + "."
                return cr.ok(self.name, rid, chat, spoken_text=spoken,
                             metadata={"stations": cands, "mode": "find", "label": label})

            # mode == play
            chosen = cands[0]
            md = {"uri": chosen["uri"], "station": chosen["name"], "source": chosen["source"], "mode": "play"}
            if resolved["dry_run"]:
                LOG.info("[DRY-RUN] req=%s WOULD PLAY radio %r uri=%s source=%s",
                         rid, chosen["name"], chosen["uri"], chosen["source"])
                md["played"] = False
                return cr.ok(self.name, rid, "Would play " + chosen["name"] + ".",
                             spoken_text=None, metadata=md)
            pr = ma.play(ctx.settings.queue_id, chosen["uri"])
            if (not pr) or ("error_code" in pr):
                LOG.error("req=%s RADIO PLAY FAILED code=%s", rid,
                          pr.get("error_code") if pr else None)
                md["played"] = False
                return cr.err(self.name, rid, "play_failed", "play failed",
                              "I found " + chosen["name"] + ", but couldn't start it.",
                              spoken_text="I found " + chosen["name"] + ", but couldn't start it.",
                              metadata=md)
            # "accepted", not "playing" -- MA returning without an error_code says nothing about audio.
            LOG.info("req=%s RADIO PLAY ACCEPTED by MA %r uri=%s source=%s (confirming shortly)",
                     rid, chosen["name"], chosen["uri"], chosen["source"])
            self._confirm_play_later(ctx, rid, chosen["name"], chosen["uri"])
            md["played"] = True
            return cr.ok(self.name, rid, "Playing " + chosen["name"] + ".",
                         spoken_text=None, metadata=md)
        finally:
            ma.close()


def resolve_radio(ctx, params, rid):
    """Legacy wrapper: runs RadioCapability and maps CommandResult back to the Inc 1 dict."""
    res = capability.run(RadioCapability(), ctx, params, rid)
    md = res.get("metadata") or {}
    out = {"ok": res["ok"], "intent": "radio", "request_id": rid,
           "spoken": res.get("spoken_text")}
    # play fields
    for k in ("uri", "station", "source", "played"):
        if k in md:
            out[k] = md[k]
    # find fields
    if "stations" in md:
        out["stations"] = md["stations"]
    # speak_success: True when ok and spoken_text is not None (find-list case)
    out["speak_success"] = bool(res["ok"] and res.get("spoken_text") is not None)
    if not res["ok"]:
        out["reason"] = (res.get("error") or {}).get("reason")
    return out
