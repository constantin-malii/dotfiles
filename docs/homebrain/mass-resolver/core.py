#!/usr/bin/env python3
# Dispatch registry + CommandResult routing. Python 3.5 safe.
import logging, uuid
import music, radio, capability, command_result as cr

LOG = logging.getLogger("resolver")

# Capability registry (stateless singletons; re-instantiated per capability call via capability.run)
CAPS = {
    "music": music.MusicCapability(),
    "radio": radio.RadioCapability(),
}

# Stub intents: name -> human-friendly label for "not available yet" message
_STUBS = {
    "news": "News",
    "acquire": "Acquire",
    "status": "Status",
}


class Ctx(object):
    def __init__(self, ma_factory, ha, settings, radio_cfg, news_cfg, speaker=None):
        self.ma_factory = ma_factory      # callable -> a fresh MA (already constructed)
        self.ha = ha
        self.settings = settings
        self.radio_cfg = radio_cfg
        self.news_cfg = news_cfg
        self.speaker = speaker            # Speaker instance or None


def sync_library(ctx, rid):
    ma = ctx.ma_factory()
    try:
        ma.connect()
        ma.sync()
        LOG.info("SYNC: req=%s music/sync triggered", rid)
        return cr.ok("sync", rid, "Synced.", spoken_text=None)
    finally:
        ma.close()


def dispatch(ctx, intent, params, rid=None):
    """Route an intent to the appropriate capability and return a CommandResult.
    Speaks spoken_text via ctx.speaker when:
      - ok result with spoken_text set (e.g. radio find list)
      - err result with spoken_text set AND ctx.settings.announce_failures is True
    """
    rid = rid or uuid.uuid4().hex[:8]

    if intent == "sync":
        result = sync_library(ctx, rid)
    elif intent in CAPS:
        p = dict(params or {})
        p["_rid"] = rid
        result = capability.run(CAPS[intent], ctx, p, rid)
    elif intent in _STUBS:
        label = _STUBS[intent]
        msg = label + " isn't available yet."
        result = cr.err(intent, rid, "not_implemented", "stub", msg, spoken_text=msg)
    else:
        LOG.error("req=%s unknown intent %r", rid, intent)
        result = cr.err(intent, rid, "invalid_input", "unknown intent",
                        "Sorry, I can't do that.", spoken_text=None)

    # Single TTS owner: speak via Speaker when spoken_text is present and conditions met
    spk = result.get("spoken_text")
    if spk and ctx.speaker is not None:
        if result.get("ok") or ctx.settings.announce_failures:
            ctx.speaker.speak(spk)

    return result
