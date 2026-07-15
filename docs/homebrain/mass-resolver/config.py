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
        self.tts_data = cfg.get("tts_data", {})               # e.g. {"entity_id":"tts.x","media_player_entity_id":"{entity}","message":"{msg}"}
        # AU-02/AU-03 interaction duck/restore tunables
        self.interaction_floor = int(cfg.get("interaction_floor", 15))          # % while interacting
        self.fade_ms = int(cfg.get("fade_ms", 0))                               # reserved (no fade v1)
        self.max_duck_timeout = int(cfg.get("max_duck_timeout", 120000))        # ms dead-man auto-restore (>= longest reply)
        self.interaction_ignore_when_idle = bool(cfg.get("interaction_ignore_when_idle", True))
        # S1b-1 say (ceiling reply) tunables
        self.say_hold_default_ms = int(cfg.get("say_hold_default_ms", 8000))   # duration-hold when clip length unknown
        self.say_margin_ms = int(cfg.get("say_margin_ms", 1500))               # added to the hold before restore


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
