#!/usr/bin/env python3
# Dispatch registry + honest failure feedback. Python 3.5 safe.
import logging, uuid
import music, radio, news, acquire, status

LOG = logging.getLogger("resolver")


class Ctx(object):
    def __init__(self, ma_factory, ha, settings, radio_cfg, news_cfg):
        self.ma_factory = ma_factory      # callable -> a fresh MA (already constructed)
        self.ha = ha
        self.settings = settings
        self.radio_cfg = radio_cfg
        self.news_cfg = news_cfg


def _run_music(ctx, params, rid):
    ma = ctx.ma_factory()
    try:
        ma.connect()
        return music.resolve_music(ma, params.get("query"), params.get("media_type") or "",
                                   ctx.settings, rid)
    finally:
        ma.close()


def sync_library(ctx, rid):
    ma = ctx.ma_factory()
    try:
        ma.connect()
        ma.sync()
        LOG.info("SYNC: req=%s music/sync triggered", rid)
        return {"ok": True, "intent": "sync", "request_id": rid, "spoken": None}
    finally:
        ma.close()


# intent -> callable(ctx, params, rid). Stubs share the (ctx, params, rid) signature.
INTENTS = {
    "music": _run_music,
    "radio": radio.resolve_radio,
    "news": news.get_news,
    "acquire": acquire.acquire,
    "status": status.status,
}


def dispatch(ctx, intent, params, rid=None):
    rid = rid or uuid.uuid4().hex[:8]
    if intent == "sync":
        return sync_library(ctx, rid)
    fn = INTENTS.get(intent)
    if fn is None:
        LOG.error("req=%s unknown intent %r", rid, intent)
        return {"ok": False, "intent": intent, "request_id": rid, "reason": "unknown intent",
                "spoken": None}
    try:
        result = fn(ctx, params, rid)
    except Exception as e:
        LOG.error("req=%s intent=%s error: %r", rid, intent, e)
        result = {"ok": False, "intent": intent, "request_id": rid, "reason": "error",
                  "spoken": "Sorry, something went wrong."}
    spk = result.get("spoken")
    if spk and result.get("speak_success"):
        ctx.ha.announce(spk, ctx.settings)
    elif spk and (not result.get("ok")) and ctx.settings.announce_failures:
        ctx.ha.announce(spk, ctx.settings)
    return result
