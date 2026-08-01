#!/usr/bin/env python3
# Dispatch registry + CommandResult routing. Python 3.5 safe.
import logging, uuid
import music, radio, status, news, interaction, capability, command_result as cr

LOG = logging.getLogger("resolver")

# Capability registry (singletons; dispatch reuses one instance per intent — InteractionCapability keeps state)
CAPS = {
    "music": music.MusicCapability(),
    "radio": radio.RadioCapability(),
    "status": status.StatusCapability(),
    "news": news.NewsCapability(),
    "interaction": interaction.InteractionCapability(),
}

# Stub intents: name -> human-friendly label for "not available yet" message
_STUBS = {
    "acquire": "Acquire",
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


def _satellite_turn_in_flight(ctx):
    """True when a satellite turn is live on the ceiling zone, i.e. the assistant pipeline is going
    to speak this result itself (Piper -> reply URI -> interaction say). Announcing here as well
    puts two voices on the zone for one utterance. Non-satellite callers (phone, ChatGPT text path)
    never duck, so they are unaffected and keep their announce."""
    if not bool(getattr(ctx.settings, "suppress_announce_during_interaction", True)):
        return False
    cap = CAPS.get("interaction")
    zone = getattr(ctx.settings, "ceiling_entity", "") or ""
    if cap is None or not zone or not hasattr(cap, "interaction_in_flight"):
        return False
    try:
        return bool(cap.interaction_in_flight(ctx, zone))
    except Exception as e:                     # never let a diagnostic check break a capability result
        LOG.warning("interaction_in_flight check failed (%r); announcing normally", e)
        return False


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

    # Single TTS owner: speak via Speaker when spoken_text is present and conditions met.
    # Exception: during a satellite turn the pipeline speaks the reply, so stand down (no double-speak).
    spk = result.get("spoken_text")
    if spk and ctx.speaker is not None:
        if _satellite_turn_in_flight(ctx):
            LOG.info("req=%s ANNOUNCE suppressed: satellite turn in flight; the pipeline speaks the reply", rid)
        elif result.get("ok") or ctx.settings.announce_failures:
            ctx.speaker.speak(spk)

    return result
