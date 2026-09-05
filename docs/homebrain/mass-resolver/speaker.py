#!/usr/bin/env python3
# Single owner of speaker TTS. Lock-protected; shared by event + HTTP paths. Python 3.5 safe.
import logging, threading, time

LOG = logging.getLogger("resolver")


class Speaker(object):
    def __init__(self, settings, ha_factory, clock=None):
        self.settings = settings; self.ha_factory = ha_factory
        self.ha = None; self.lock = threading.Lock()
        self._clock = clock or time.time
        # When this speaker last put a voice on the zone. Read by interaction._say to detect a
        # second voice arriving for the same turn (resolver announce + satellite pipeline reply)
        # -- the double-speak the operator hears. Advisory/diagnostic only.
        self.last_announce_ts = None
        self.last_announce_text = None

    def _mark_announced(self, text):
        self.last_announce_ts = self._clock()
        self.last_announce_text = text

    def speak(self, text):
        if not text:
            return
        with self.lock:
            try:
                if self.ha is None:
                    self.ha = self.ha_factory(); self.ha.connect()
                self.ha.announce(text, self.settings)
                self._mark_announced(text)
                return
            except Exception as e:
                LOG.error("speak: retrying after error %r", e)
            try:
                self.ha = self.ha_factory(); self.ha.connect()
                self.ha.announce(text, self.settings)
                self._mark_announced(text)
            except Exception as e:
                LOG.error("speak failed: %r", e); self.ha = None
