#!/usr/bin/env python3
# Single owner of speaker TTS. Lock-protected; shared by event + HTTP paths. Python 3.5 safe.
import logging, threading

LOG = logging.getLogger("resolver")


class Speaker(object):
    def __init__(self, settings, ha_factory):
        self.settings = settings; self.ha_factory = ha_factory
        self.ha = None; self.lock = threading.Lock()

    def speak(self, text):
        if not text:
            return
        with self.lock:
            try:
                if self.ha is None:
                    self.ha = self.ha_factory(); self.ha.connect()
                self.ha.announce(text, self.settings)
                return
            except Exception as e:
                LOG.error("speak: retrying after error %r", e)
            try:
                self.ha = self.ha_factory(); self.ha.connect()
                self.ha.announce(text, self.settings)
            except Exception as e:
                LOG.error("speak failed: %r", e); self.ha = None
