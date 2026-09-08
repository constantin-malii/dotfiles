#!/usr/bin/env python3
# Home Assistant WebSocket client + TTS announce (honest failure feedback). Python 3.5 safe.
import logging
import hashlib
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

    def get_entity_state(self, entity_id, timeout=10):
        """Read-only HA REST GET /api/states/<entity_id>.

        Uses a FRESH per-call HTTP connection (NOT the shared event WebSocket self.s), so it never
        interleaves with the subscribe_events read loop and is safe to call from the HTTP server
        thread. Returns the parsed state dict on HTTP 200; raises on any failure. Never logs the token.

        `timeout` is a PER-OPERATION socket inactivity timeout, not a deadline for the whole
        request -- connect, send, headers and body each get their own allowance. Callers that
        hold a phase deadline clip it to what is left rather than blocking on the default
        (AN-01 design 6.5). The default of 10s is unchanged, so every existing caller --
        _duck, _restore, _resume, _pause, _volume and _say's captures and polls -- behaves
        exactly as before.
        """
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
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

    def _post_json(self, path, data, timeout=10):
        """POST JSON and return the parsed JSON body (unlike call_service_rest, which discards it).
        Fresh per-call connection, safe from any thread. Never logs the token."""
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            headers = {"Authorization": "Bearer " + (self.token or ""),
                       "Content-Type": "application/json"}
            conn.request("POST", path, body=json.dumps(data).encode("utf-8"), headers=headers)
            resp = conn.getresponse()
            body = resp.read()
            if resp.status not in (200, 201):
                raise IOError("HA REST POST %s -> HTTP %s" % (path, resp.status))
            return json.loads(body.decode("utf-8"))
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def tts_get_url(self, engine_id, message, timeout=10):
        """Turn TEXT into a playable clip URL via HA's /api/tts_get_url.

        Why this exists: the ceiling cannot be handed a sentence. The obvious route
        (tts.speak -> MA play_announcement) is broken on this Universal->Squeezelite player -- MA's
        own docs require the player to report state and elapsed time correctly, which it does not,
        and the call fails with 'Failed to stream audio'. So we resolve the text to a clip and play
        it through the same play_media route every reply already uses."""
        d = self._post_json("/api/tts_get_url",
                            {"engine_id": engine_id, "message": message}, timeout) or {}
        url = d.get("url")
        if not url:
            raise IOError("HA tts_get_url returned no url")
        # Must be absolute: _say only swaps the netloc, so a scheme-less url becomes "//host/..."
        # which MA cannot fetch -- and that failure would surface only as a start-poll timeout,
        # far from its cause.
        if not str(url).startswith("http"):
            raise IOError("HA tts_get_url returned a non-absolute url")
        return url

    def resolve_media_source(self, uri, timeout=10):
        """Turn a media-source:// URI into an absolute, MA-fetchable URL.

        Why this exists: MA rejects media-source:// URIs outright and cannot fetch HA's
        authenticated /media/local/... paths. HA's own resolver hands back a SIGNED path, which is
        the only form MA can fetch -- proven at AN-1, where the corrected URI played on the ceiling.

        Transport: a FRESH, short-lived WebSocket per call. media_source/resolve_media has no REST
        equivalent, and self.s is the shared subscribe_events socket -- reusing it would interleave
        with that read loop, the same rule get_entity_state follows. Resolved per use and never
        cached: the signature expires.

        SECURITY: the returned URL is a BEARER CREDENTIAL. It is never logged, and neither is any
        state that embeds it. Log lines carry only an 8-char fingerprint, the same algorithm as
        interaction._clip_id, so a resolve can be correlated with the play it feeds.

        `timeout` is a PER-OPERATION socket inactivity timeout, not a deadline for the whole
        exchange; callers holding a phase deadline clip it (AN-01 design 6.5).
        """
        # AN-1 root cause: a './' segment makes HA sign the UN-normalised path while returning a
        # NORMALISED url, so the signature cannot validate against the url it is attached to.
        # Normalise here as well as in the config default, so a caller pasting the media-browser
        # form still gets a working url instead of a silent 401 two layers away.
        clean = uri
        while "/./" in clean:
            clean = clean.replace("/./", "/")
        if clean != uri:
            LOG.warning("MEDIA_SOURCE %r contained a './' segment; resolving %r instead "
                        "(a './' yields a signature HA cannot validate)", uri, clean)

        s = None
        try:
            s, box = wsutil.ws_connect(self.host, self.port, "/api/websocket", timeout=timeout)
            hello = wsutil.ws_read(s, box)
            if (hello or {}).get("type") != "auth_required":
                raise IOError("unexpected HA hello resolving a media source")
            wsutil.ws_send(s, {"type": "auth", "access_token": self.token})
            if (wsutil.ws_read(s, box) or {}).get("type") != "auth_ok":
                raise IOError("HA auth failed resolving a media source")
            wsutil.ws_send(s, {"id": 1, "type": "media_source/resolve_media",
                               "media_content_id": clean})
            msg = wsutil.ws_read(s, box) or {}
            if not msg.get("success"):
                code = ((msg.get("error") or {}).get("code")) or "unknown"
                raise IOError("HA resolve_media failed: %s" % code)
            url = (msg.get("result") or {}).get("url")
            if not url:
                raise IOError("HA resolve_media returned no url")
            # Three cases, and they must be told apart. Blindly prepending a base to anything
            # that merely lacks an "http" prefix turns "ftp://x" into
            # "http://host:port/ftp://x" -- which then LOOKS absolute and gets returned. A caught
            # test found exactly that.
            u = str(url)
            if u.startswith("http://") or u.startswith("https://"):
                pass                                    # already absolute
            elif u.startswith("/"):
                # HA returns a RELATIVE signed path. Absolutise against our own host:port, which is
                # already the MA-reachable base taken from ha_url. A scheme-less url would become
                # "//host/..." downstream, which MA cannot fetch -- and that failure would surface
                # only as a start-poll timeout, far from its cause.
                u = "http://%s:%s%s" % (self.host, self.port, u)
            else:
                raise IOError("HA resolve_media returned a url that is neither absolute http(s) "
                              "nor a rooted path")
            url = u
            LOG.info("MEDIA_SOURCE resolved %s -> clip=%s (%s)",
                     clean, self._fingerprint(url), (msg.get("result") or {}).get("mime_type"))
            return url
        finally:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass

    @staticmethod
    def _fingerprint(url):
        """8-char digest of a URL, for logs that must not contain the URL itself.
        Same algorithm as interaction._clip_id so the two log families correlate."""
        try:
            return hashlib.sha1((url or "").encode("utf-8")).hexdigest()[:8]
        except Exception:
            return "????????"

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
