#!/usr/bin/env python3
# Config + secrets + logging loading for the resolver. Python 3.5 safe.
import os, sys, json, logging


def load_json(here, name, default):
    try:
        with open(os.path.join(here, name)) as f:
            return json.loads(f.read())
    except Exception:
        return default


def read_secret(here, name):
    try:
        with open(os.path.join(here, name)) as f:
            return f.read().strip()
    except Exception:
        return None


class Settings(object):
    def __init__(self, cfg):
        self.ma_host = cfg.get("ma_host", "192.168.122.10")
        self.ma_port = int(cfg.get("ma_port", 8095))
        ha_url = cfg.get("ha_url", "http://192.168.122.10:8123")
        self.ha_host = ha_url.split("://", 1)[-1].split(":")[0]
        self.ha_port = int(ha_url.rsplit(":", 1)[-1].split("/")[0])
        self.provider_preference = cfg.get("provider_preference", ["filesystem_smb"])
        self.type_order = cfg.get("type_order", ["artist", "album", "track", "playlist"])
        self.queue_id = cfg.get("ceiling_player_id", "upf8b156c25101")
        self.ceiling_entity = cfg.get("ceiling_entity", "media_player.ceiling_speakers")
        self.event_type = cfg.get("event_type", "mass_play_request")
        self.sync_event_type = cfg.get("sync_event_type", "mass_sync_request")
        self.radio_event_type = cfg.get("radio_event_type", "mass_radio_request")
        self.dry_run = bool(cfg.get("dry_run", False))
        self.announce_failures = bool(cfg.get("announce_failures", True))
        self.http_host = cfg.get("http_host", "192.168.122.1")
        self.http_port = int(cfg.get("http_port", 8770))
        # TTS announce service: domain.service + a template of data fields.
        # tts_data placeholders {msg}/{entity} are filled by haconn.announce().
        self.tts_service = cfg.get("tts_service", "")          # e.g. "tts.speak"
        self.tts_data = cfg.get("tts_data", {})
        # Engine for interaction mode say_text (text -> /api/tts_get_url -> clip -> play_media).
        # Separate from tts_service above, which drives the (broken on this player) announce path.
        self.tts_engine = cfg.get("tts_engine", "tts.piper")               # e.g. {"entity_id":"tts.x","media_player_entity_id":"{entity}","message":"{msg}"}
        # AU-02/AU-03 interaction duck/restore tunables
        self.interaction_floor = int(cfg.get("interaction_floor", 15))          # % while interacting
        self.fade_ms = int(cfg.get("fade_ms", 0))                               # reserved (no fade v1)
        self.max_duck_timeout = int(cfg.get("max_duck_timeout", 120000))        # ms dead-man auto-restore (>= longest reply)
        self.interaction_ignore_when_idle = bool(cfg.get("interaction_ignore_when_idle", True))
        # S1b-2 say: play_media reply route (play_announcement retired — silent on this player)
        self.reply_volume = float(cfg.get("reply_volume", 0.40))                 # ceiling volume for the reply clip
        self.say_start_timeout_ms = int(cfg.get("say_start_timeout_ms", 5000))   # max wait for the clip to START playing
        # Max wait for the clip to FINISH. Sized for the knowledge agent, which is allowed to give
        # longer answers: at 30s a long reply was truncated mid-sentence by the restore+replay.
        # ~180s covers roughly 400 spoken words. The reply-marker staleness budget and the deferred
        # restore both derive from this value, so they widen with it automatically.
        self.say_reply_timeout_ms = int(cfg.get("say_reply_timeout_ms", 180000))
        self.say_poll_ms = int(cfg.get("say_poll_ms", 500))                      # poll interval
        self.say_internal_base = cfg.get("say_internal_base", "192.168.122.10:8123")  # MA-reachable base for reply URI
        self.say_owns_restore = bool(cfg.get("say_owns_restore", True))          # _say restores pre-duck baseline
        # MA play_media can take well over the 5s default REST timeout; a client-side timeout there
        # aborts the reply turn while the clip still plays server-side (heard, but unsequenced).
        self.say_call_timeout_ms = int(cfg.get("say_call_timeout_ms", 20000))     # play_media REST timeout
        self.say_double_speak_window_ms = int(cfg.get("say_double_speak_window_ms", 8000))  # warn window
        # During a satellite turn the assistant pipeline speaks the reply itself; the resolver's own
        # tts.speak would be a SECOND voice on the same zone for one utterance.
        self.suppress_announce_during_interaction = bool(
            cfg.get("suppress_announce_during_interaction", True))
        self.interaction_turn_window_ms = int(cfg.get("interaction_turn_window_ms", 30000))
        # "MA accepted the play" != "audio is playing": read the zone back this long after a radio
        # play and log what actually happened (0 disables the check).
        self.radio_confirm_after_ms = int(cfg.get("radio_confirm_after_ms", 8000))
        # A media command is confirmed by the action (decision (e)): skip the spoken reply clip when
        # this turn just started playback, since the clip would replace it and leave silence.
        self.say_skip_on_fresh_playback = bool(cfg.get("say_skip_on_fresh_playback", True))
        # The duck half of the same decision: with the reply skipped there is nothing to duck under,
        # so ducking would only attenuate the station this turn just started until the restore lands.
        self.duck_skip_on_fresh_playback = bool(cfg.get("duck_skip_on_fresh_playback", True))
        # The same decision for the opposite direction: when this turn PAUSED the zone, the reply is
        # still spoken but must not replay the source afterwards, or the confirmation restarts the
        # stream the user just stopped.
        self.say_skip_replay_on_stop = bool(cfg.get("say_skip_replay_on_stop", True))
        # How long to tolerate MA reporting an EMPTY media_content_id mid-clip before concluding the
        # reply finished. Too short cuts replies off; unbounded holds the zone at reply volume for the
        # whole say_reply_timeout_ms.
        # A longer reply gives MA more opportunity to report an empty media_content_id mid-clip, so
        # the tolerance is wider than the 4s that sufficed for short replies -- too short and a long
        # answer gets cut at the first sustained blank.
        self.say_blank_cid_grace_ms = int(cfg.get("say_blank_cid_grace_ms", 8000))
        # Silence the outgoing music before raising to reply_volume, so the raise is not heard as a
        # "bump" on the ~1s of music still playing before the clip replaces the stream.
        self.say_pause_before_reply = bool(cfg.get("say_pause_before_reply", True))
        # ---- AN-01 announce mode (design 6.2) -------------------------------------------
        # Louder than reply_volume: an announcement has to carry through the house, where a reply
        # only has to reach the person who asked.
        self.announce_volume = float(cfg.get("announce_volume", 0.80))
        # Empty by default -- the chime is the attention signal, so a spoken prefix would be a
        # second one. Bounded separately below so a misconfiguration cannot defeat the timing model.
        self.announce_prefix = cfg.get("announce_prefix", "")
        self.announce_max_prefix_chars = int(cfg.get("announce_max_prefix_chars", 40))
        # NO "./" IN THIS PATH. A './' segment makes HA sign the un-normalised path while returning
        # a normalised url, so the signature cannot validate against the url it is attached to --
        # the AN-1 root cause, and why this asset was believed unplayable for two days.
        self.announce_chime_uri = cfg.get(
            "announce_chime_uri", "media-source://media_source/local/timer_chime.wav")
        # D1, settled at AN-2. Empty here so a machine with no config.json refuses rather than
        # guessing an entity id; the shipped config.json carries the real one.
        self.announce_mic_mute_entity = cfg.get("announce_mic_mute_entity", "")
        self.announce_require_mic_mute = bool(cfg.get("announce_require_mic_mute", True))
        # A successful switch.turn_on is an ACCEPTED REQUEST, not a muted microphone: AN-2 saw HA
        # answer 200 in 1ms while the state was still "off", so the state is read back before any
        # audio (design 9.3). AN-2 measured 255ms for the switch to report, in both directions, so
        # 2000ms leaves roughly 8x headroom -- too tight a budget refuses every announcement.
        self.announce_mic_confirm_timeout_ms = int(cfg.get("announce_mic_confirm_timeout_ms", 2000))
        self.announce_mic_confirm_poll_ms = int(cfg.get("announce_mic_confirm_poll_ms", 250))
        # Failsafe timers. 0 derives from the turn's own budget (design 6.5). Both are POLICY
        # CUTOFFS based on an engineered budget, not wall-clock bounds -- a pathologically
        # slow-but-live turn can cross one. The trade-off deliberately favours liveness: a stuck
        # mute leaves the satellite deaf, and a stuck volume leaves the ceiling loud.
        self.announce_mic_deadman_ms = int(cfg.get("announce_mic_deadman_ms", 0))
        self.announce_volume_deadman_ms = int(cfg.get("announce_volume_deadman_ms", 0))
        self.announce_volume_deadman_retries = int(cfg.get("announce_volume_deadman_retries", 3))
        # Per-clip finish budgets, NOT say_reply_timeout_ms (180s) -- that is sized for the
        # knowledge agent's long answers, and a 4s chime does not need it.
        self.announce_chime_finish_timeout_ms = int(cfg.get("announce_chime_finish_timeout_ms", 15000))
        self.announce_message_finish_timeout_ms = int(cfg.get("announce_message_finish_timeout_ms", 45000))
        # Bound on the FINAL RENDERED text (prefix + message). Every timeout above is sized from
        # this number, so nothing reaching Piper may escape it. Over-long is REJECTED, never
        # truncated: clipping a household message can invert its meaning.
        self.announce_max_chars = int(cfg.get("announce_max_chars", 300))
        # Floor for a deadline-clipped blocking call: below this, do not start the call at all.
        self.announce_min_call_timeout_ms = int(cfg.get("announce_min_call_timeout_ms", 500))


def load_settings(here):
    return Settings(load_json(here, "config.json", {}))


def country_code(radio_cfg, name):
    codes = (radio_cfg or {}).get("country_codes", {})
    return codes.get((name or "").strip().lower())


def resolve_country(radio_cfg, word):
    return (radio_cfg or {}).get("country_codes", {}).get((word or "").strip().lower())


def resolve_language(radio_cfg, word):
    return (radio_cfg or {}).get("languages", {}).get((word or "").strip().lower())


def resolve_genre(radio_cfg, word):
    w = (word or "").strip().lower()
    syn = (radio_cfg or {}).get("genre_synonyms", {})
    if w in syn:
        return (w, syn[w])
    for key, words in syn.items():
        if w in [str(x).lower() for x in words]:
            return (key, words)
    return (w, [w])


def radio_defaults(radio_cfg):
    d = {"find_internal": 5, "find_speak": 3, "fallback_browse_limit": 10}
    d.update((radio_cfg or {}).get("defaults", {}))
    return d


def favorites(radio_cfg):
    return (radio_cfg or {}).get("favorites", [])


def setup_logging(here):
    log = logging.getLogger("resolver")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt); log.addHandler(sh)
    try:
        fh = logging.FileHandler(os.path.join(here, "resolver.log")); fh.setFormatter(fmt); log.addHandler(fh)
    except Exception:
        pass
    return log
