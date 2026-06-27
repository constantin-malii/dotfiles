#!/usr/bin/env python3
# Home Assistant WebSocket client + TTS announce (honest failure feedback). Python 3.5 safe.
import logging
import wsutil

LOG = logging.getLogger("resolver")


class HA(object):
    def __init__(self, host, port, token):
        self.host = host; self.port = port; self.token = token
        self.s = None; self.box = None; self.cmd_id = 100

    def connect(self):
        self.s, self.box = wsutil.ws_connect(self.host, self.port, "/api/websocket"); self.s.settimeout(None)
        hello = wsutil.ws_read(self.s, self.box)
        if (hello or {}).get("type") != "auth_required":
            raise RuntimeError("unexpected HA hello: %r" % hello)
        wsutil.ws_send(self.s, {"type": "auth", "access_token": self.token})
        if (wsutil.ws_read(self.s, self.box) or {}).get("type") != "auth_ok":
            raise RuntimeError("HA auth failed")

    def subscribe(self, event_type, sub_id):
        wsutil.ws_send(self.s, {"id": sub_id, "type": "subscribe_events", "event_type": event_type})
        self.read()

    def read(self):
        return wsutil.ws_read(self.s, self.box)

    def call_service(self, domain, service, data):
        self.cmd_id += 1
        wsutil.ws_send(self.s, {"id": self.cmd_id, "type": "call_service",
                                "domain": domain, "service": service, "service_data": data})

    def announce(self, message, settings):
        try:
            svc = (getattr(settings, "tts_service", "") or "").strip()
            parts = svc.split(".", 1)
            if len(parts) != 2 or not parts[0] or not parts[1]:
                LOG.info("ANNOUNCE (no tts_service configured): %s", message)
                return
            domain, service = parts
            entity = getattr(settings, "ceiling_entity", "") or ""
            data = {}
            for k, v in (getattr(settings, "tts_data", {}) or {}).items():
                if isinstance(v, str):
                    data[k] = v.replace("{msg}", message).replace("{entity}", entity)
                else:
                    data[k] = v
            self.call_service(domain, service, data)
            LOG.info("ANNOUNCE via %s: %s", svc, message)
        except Exception as e:
            LOG.error("ANNOUNCE failed (%r): %s", e, message)

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass
