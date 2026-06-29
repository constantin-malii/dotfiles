#!/usr/bin/env python3
# Music Assistant provider-aware resolver -- thin entrypoint + HA event adapter.
# Runs on the homebrain HOST. Python 3.5 compatible (no f-strings).
#
# Capability modules: music/radio/status (live), news/acquire (stubs). Dispatch + honest
# failure feedback in core. Transport in wsutil; MA in maconn; HA in haconn; config in config.
#
# Secrets (0600, NEVER logged): ~/mass-resolver/.ma_token  ~/mass-resolver/.ha_token
#
# Modes:
#   python3 resolver.py --dry-run --query "Du Hast" --media-type track
#   python3 resolver.py --query "Rammstein" --media-type artist
#   python3 resolver.py --serve
import os, sys, json, argparse, logging, uuid, time, threading
import config
from maconn import MA
from haconn import HA
import core
import speaker
import http_server

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = logging.getLogger("resolver")


def make_ctx(settings, ma_token, ha_token, radio_cfg, news_cfg):
    """Testable seam: wire all dependencies into a Ctx given resolved values."""
    def ma_factory():
        return MA(settings.ma_host, settings.ma_port, ma_token)

    def ha_factory():
        return HA(settings.ha_host, settings.ha_port, ha_token)

    ha = ha_factory()  # event-read connection (used only by serve's read loop)
    sp = speaker.Speaker(settings, ha_factory)  # SINGLE TTS owner (its own HA connection)
    return core.Ctx(ma_factory=ma_factory, ha=ha, settings=settings,
                    radio_cfg=radio_cfg, news_cfg=news_cfg, speaker=sp)


def build_ctx(here):
    settings = config.load_settings(here)
    ma_token = config.read_secret(here, ".ma_token")
    ha_token = config.read_secret(here, ".ha_token")
    radio_cfg = config.load_json(here, "radio.json", {})
    news_cfg = config.load_json(here, "news.json", {})
    return make_ctx(settings, ma_token, ha_token, radio_cfg, news_cfg)


def event_to_call(settings, event):
    """Pure mapping: HA event dict -> (intent, params) or None."""
    et = event.get("event_type"); data = event.get("data") or {}
    if et == settings.event_type:
        q = data.get("query")
        if not q:
            return None
        return ("music", {"query": q, "media_type": data.get("media_type") or ""})
    if et == settings.sync_event_type:
        return ("sync", {"source": data.get("source")})
    if et == getattr(settings, "radio_event_type", "mass_radio_request"):
        params = {"mode": data.get("mode") or "play"}
        for k in ("station", "country", "language", "genre"):
            if data.get(k):
                params[k] = data.get(k)
        if data.get("dry_run"):
            params["dry_run"] = True
        return ("radio", params)
    return None


def serve(here):
    ctx = build_ctx(here)
    if not ctx.ha.token:
        LOG.error("no HA token (~/mass-resolver/.ha_token)"); sys.exit(2)
    if not config.read_secret(here, ".ma_token"):
        LOG.error("WARNING: no MA token (~/mass-resolver/.ma_token); play events will fail until it is present")
    s = ctx.settings

    # Start HTTP server in a daemon thread before the event loop.
    http_secret = config.read_secret(here, ".http_secret")  # optional; None if absent
    if not http_secret:
        LOG.warning("SERVICE: /command has no shared secret (.http_secret); access limited to the %s bind only", s.http_host)

    def dispatch_fn(intent, params):
        return core.dispatch(ctx, intent, params)

    try:
        srv = http_server.serve_http(s.http_host, s.http_port, dispatch_fn, http_secret)
        t = threading.Thread(target=srv.serve_forever)
        t.daemon = True
        t.start()
        LOG.info("SERVICE: /command HTTP server on %s:%s", s.http_host, s.http_port)
    except Exception as e:
        LOG.error("SERVICE: HTTP server failed to start (%r); continuing event-only", e)

    backoff = 2
    while True:
        try:
            ctx.ha.connect()
            ctx.ha.subscribe(s.event_type, 1)
            ctx.ha.subscribe(s.sync_event_type, 2)
            ctx.ha.subscribe(s.radio_event_type, 3)
            LOG.info("SERVICE: connected; subscribed to %r (play) + %r (sync) + %r (radio); provider_preference=%s",
                     s.event_type, s.sync_event_type, s.radio_event_type, s.provider_preference)
            backoff = 2
            while True:
                m = ctx.ha.read()
                if m is None:
                    raise RuntimeError("HA connection closed")
                if m.get("type") != "event":
                    continue
                ev = m.get("event") or {}
                call = event_to_call(s, ev)
                if not call:
                    continue
                intent, params = call
                LOG.info("SERVICE: event=%s -> intent=%s params=%r", ev.get("event_type"), intent, params)
                try:
                    # NOTE: dispatch speaks via the Speaker's OWN HA connection (see make_ctx);
                    # ctx.ha here is read-only for event subscription — do not announce on it.
                    core.dispatch(ctx, intent, params)
                except Exception as e:
                    LOG.error("SERVICE: dispatch error: %r", e)
        except Exception as e:
            LOG.error("SERVICE: connection error: %r; reconnecting in %ss", e, backoff)
            try:
                ctx.ha.close()
            except Exception:
                pass
            time.sleep(backoff); backoff = min(backoff * 2, 60)


def main():
    config.setup_logging(HERE)
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--radio", action="store_true")
    ap.add_argument("--mode", default="play", choices=["play", "find"])
    ap.add_argument("--station"); ap.add_argument("--country")
    ap.add_argument("--genre"); ap.add_argument("--language")
    ap.add_argument("--query")
    ap.add_argument("--media-type", default="", choices=["", "artist", "album", "track", "playlist"])
    a = ap.parse_args()

    if a.serve:
        serve(HERE); return

    if a.radio:
        import radio as radiomod
        ctx = build_ctx(HERE)
        params = {"mode": a.mode}
        for k in ("station", "country", "genre", "language"):
            v = getattr(a, k)
            if v:
                params[k] = v
        if a.dry_run:
            params["dry_run"] = True
        rid = uuid.uuid4().hex[:8]
        res = radiomod.resolve_radio(ctx, params, rid)
        if res.get("spoken") and (res.get("speak_success") or not res.get("ok")) and not a.dry_run:
            try:
                ctx.ha.connect(); ctx.ha.announce(res["spoken"], ctx.settings); ctx.ha.close()
            except Exception as e:
                LOG.error("radio announce failed: %r", e)
        print(json.dumps(res)); return

    ctx = build_ctx(HERE)
    ma_token = config.read_secret(HERE, ".ma_token")
    if not ma_token:
        LOG.error("no MA token (~/mass-resolver/.ma_token)"); sys.exit(2)
    if not a.query:
        LOG.error("--query required (or use --serve)"); sys.exit(2)
    if a.dry_run:
        ctx.settings.dry_run = True
    rid = uuid.uuid4().hex[:8]
    ma = ctx.ma_factory()
    try:
        ma.connect()
        import music
        res = music.resolve_music(ma, a.query, a.media_type, ctx.settings, rid)
    finally:
        ma.close()
    # honest feedback also on the one-shot path (when announce configured)
    if (not res.get("ok")) and res.get("spoken") and ctx.settings.announce_failures:
        try:
            ctx.ha.connect(); ctx.ha.announce(res["spoken"], ctx.settings); ctx.ha.close()
        except Exception as e:
            LOG.error("one-shot announce failed: %r", e)
    print(json.dumps(res))


if __name__ == "__main__":
    main()
