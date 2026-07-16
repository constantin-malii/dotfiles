#!/usr/bin/env python3
# Home Assistant WebSocket client + TTS announce (honest failure feedback). Python 3.5 safe.
import logging
import http.client
import json
import threading
import wsutil

LOG = logging.getLogger("resolver")


class HA(object):
    def __init__(self, host, port, token):
        self.host = host; self.port = port; self.token = token
        self.s = None; self.box = None; self.cmd_id = 100
        self._send_lock = threading.Lock()

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
        with self._send_lock:
            self.cmd_id += 1
            wsutil.ws_send(self.s, {"id": self.cmd_id, "type": "call_service",
                                    "domain": domain, "service": service, "service_data": data})

    def get_entity_state(self, entity_id):
        """Read-only HA REST GET /api/states/<entity_id>.

        Uses a FRESH per-call HTTP connection (NOT the shared event WebSocket self.s), so it never
        interleaves with the subscribe_events read loop and is safe to call from the HTTP server
        thread. Returns the parsed state dict on HTTP 200; raises on any failure. Never logs the token.
        """
        conn = http.client.HTTPConnection(self.host, self.port, timeout=10)
        try:
            headers = {"Authorization": "Bearer " + (self.token or ""), "Accept": "application/json"}
            conn.request("GET", "/api/states/" + entity_id, headers=headers)
            resp = conn.getresponse()
            body = resp.read()
            if resp.status != 200:
                raise IOError("HA REST GET states/%s -> HTTP %s" % (entity_id, resp.status))
            return json.loads(body.decode("utf-8"))
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def call_service_rest(self, domain, service, data, timeout=5):
        """Call an HA service over a FRESH REST connection (POST /api/services/<d>/<s>).

        Like get_entity_state: fresh per-call HTTPConnection, safe from any thread, never touches the
        shared event WebSocket self.s, raises on non-2xx so callers confirm the write before discarding
        state. Never logs the token.
        """
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            headers = {"Authorization": "Bearer " + (self.token or ""),
                       "Content-Type": "application/json"}
            conn.request("POST", "/api/services/" + domain + "/" + service,
                         body=json.dumps(data).encode("utf-8"), headers=headers)
            resp = conn.getresponse(); resp.read()
            if resp.status not in (200, 201):
                raise IOError("HA REST POST services/%s/%s -> HTTP %s" % (domain, service, resp.status))
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def announce(self, message, settings):
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
        try:
            self.call_service(domain, service, data)
            LOG.info("ANNOUNCE via %s: %s", svc, message)
        except Exception as e:
            LOG.error("ANNOUNCE send failed (%r): %s", e, message)
            raise

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass
