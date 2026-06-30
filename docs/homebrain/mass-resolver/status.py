#!/usr/bin/env python3
# Status / Now-Playing capability (Inc 4A). HA-state-primary, summary-only. Python 3.5 safe.
#
# Design: docs/homebrain/2026-06-29-inc4a-status-now-playing-design.md
# Plan:   docs/homebrain/plans/2026-06-29-inc4a-status-now-playing.md
#
# Rules (from the Phase-2 empirical HA capture):
#   - `state` is the primary gate. Now-playing is reported only while state == "playing".
#   - Radio vs track is decided from the media_content_id prefix ONLY while playing:
#       library://radio/... -> content_kind "radio";  library://track/... -> content_kind "track".
#     media_content_type is "music" for BOTH and is NOT used as the discriminator.
#   - Radio: media_album_name is the station; media_title/media_artist are optional stream metadata.
#   - Track: media_title is the title; media_artist is the artist when usable.
#   - media_artist that is missing/empty/"[unknown]" normalizes to None.
#   - idle/off/unavailable retain stale media_* fields -> ignored (gated on state).
#   - We avoid HA's colliding `source` attribute; the normalized discriminator is `content_kind`.

import logging
from decimal import Decimal, ROUND_HALF_UP

import capability
import command_result as cr

LOG = logging.getLogger("resolver")

_RADIO_PREFIX = "library://radio/"
_TRACK_PREFIX = "library://track/"


def _clean(x):
    if x is None:
        return None
    s = str(x).strip()
    return s or None


def _norm_artist(x):
    # Missing, empty, or the literal "[unknown]" -> None (never render "by [unknown]").
    if x is None:
        return None
    s = str(x).strip()
    if not s or s.lower() == "[unknown]":
        return None
    return s


def _percent(level):
    # Round-half-up to an integer percent. None-safe. Decimal(str(level)) so 0.355 -> 36.
    if not isinstance(level, (int, float)) or isinstance(level, bool):
        return None
    return int((Decimal(str(level)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def normalize_status(ha_state):
    """Pure: an HA entity-state dict -> normalized status metadata.

    Now-playing fields are populated only when state == "playing" (paused gets title/artist for the
    "paused" line; idle/off/unavailable ignore retained stale fields). content_kind comes from the
    media_content_id prefix, evaluated only while playing.
    """
    state = (ha_state or {}).get("state")
    attrs = (ha_state or {}).get("attributes") or {}
    level = attrs.get("volume_level")
    has_level = isinstance(level, (int, float)) and not isinstance(level, bool)
    meta = {
        "player_state": state,
        "content_kind": "none",
        "title": None, "artist": None, "station": None, "album": None,
        "media_content_id": attrs.get("media_content_id"),
        "volume_level": level if has_level else None,
        "volume_percent": _percent(level),
        "available": state != "unavailable",
    }

    if state == "playing":
        cid = attrs.get("media_content_id") or ""
        if cid.startswith(_RADIO_PREFIX):
            meta["content_kind"] = "radio"
            meta["station"] = _clean(attrs.get("media_album_name"))    # station name (radio)
            meta["title"] = _clean(attrs.get("media_title"))           # optional current-stream track
            meta["artist"] = _norm_artist(attrs.get("media_artist"))   # optional, often absent
        elif cid.startswith(_TRACK_PREFIX):
            meta["content_kind"] = "track"
            meta["title"] = _clean(attrs.get("media_title"))
            meta["artist"] = _norm_artist(attrs.get("media_artist"))
            meta["album"] = _clean(attrs.get("media_album_name"))
        else:
            # Playing but no/unrecognized content_id: do NOT fabricate a radio/track classification.
            meta["content_kind"] = "unknown"
            meta["title"] = _clean(attrs.get("media_title"))
            meta["artist"] = _norm_artist(attrs.get("media_artist"))
            meta["album"] = _clean(attrs.get("media_album_name"))
    elif state == "paused":
        # Reports paused (not playing). Detail from title/artist only; no discriminator, no station.
        meta["title"] = _clean(attrs.get("media_title"))
        meta["artist"] = _norm_artist(attrs.get("media_artist"))
    # idle / off / unavailable / other: leave now-playing fields None (ignore retained stale fields).

    return meta


def _named(meta):
    t = meta.get("title")
    a = meta.get("artist")
    if t and a:
        return '"%s" by %s' % (t, a)
    if t:
        return '"%s"' % t
    if a:
        return "by %s" % a
    return ""


def _vol_suffix(meta):
    vp = meta.get("volume_percent")
    return " at %d%% volume" % vp if vp is not None else ""


def build_chat_text(meta):
    """Pure: normalized metadata -> a single self-sufficient summary line (no aspect param)."""
    ps = meta.get("player_state")
    if ps == "playing":
        vol = _vol_suffix(meta)
        if meta.get("content_kind") == "radio":
            station = meta.get("station")
            if station:
                return "Playing %s%s." % (station, vol)
            return "Playing the radio%s." % vol
        named = _named(meta)
        if named:
            return "Playing %s%s." % (named, vol)
        return "Something is playing%s." % vol
    if ps == "paused":
        named = _named(meta)
        if named:
            return "Playback is paused (%s)." % named
        return "Playback is paused."
    if ps == "unavailable":
        return "The ceiling speakers are unavailable right now."
    return "Nothing is playing right now."


class StatusCapability(capability.Capability):
    name = "status"

    def resolve(self, ctx, params):
        # No params in v1. Identify the target entity; the read happens in execute (read-only).
        return {"entity": getattr(ctx.settings, "ceiling_entity", "") or ""}

    def validate(self, ctx, resolved):
        return None

    def execute(self, ctx, resolved, rid):
        entity = resolved.get("entity") or ""
        # Isolated, read-only HA state read (Phase 4 wires this to an HA REST GET in haconn).
        try:
            ha_state = ctx.ha.get_entity_state(entity)
        except Exception as e:
            LOG.error("req=%s status: HA state read failed: %r", rid, e)
            return cr.err("status", rid, "unavailable", "HA state read failed: %r" % e,
                          "Sorry, I couldn't check what's playing right now.",
                          spoken_text=None, metadata={"available": False})
        if ha_state is None:
            return cr.err("status", rid, "unavailable", "no state for %s" % entity,
                          "Sorry, I couldn't check what's playing right now.",
                          spoken_text=None, metadata={"available": False})
        meta = normalize_status(ha_state)
        chat = build_chat_text(meta)
        # Unconditionally silent: spoken_text=None on success (and on error above).
        return cr.ok("status", rid, chat, spoken_text=None, metadata=meta)
