#!/usr/bin/env python3
# Music Assistant WebSocket client. Python 3.5 safe.
import wsutil

WS_CMD = {"artist": "music/artists/library_items", "album": "music/albums/library_items",
          "track": "music/tracks/library_items", "playlist": "music/playlists/library_items"}


class MA(object):
    def __init__(self, host, port, token):
        self.host = host; self.port = port; self.token = token
        self.s = None; self.box = None; self.mid = 0

    def connect(self):
        self.s, self.box = wsutil.ws_connect(self.host, self.port, "/ws"); self.s.settimeout(60)
        wsutil.ws_read(self.s, self.box)                 # server-info
        self.cmd("auth", token=self.token)

    def cmd(self, command, **args):
        self.mid += 1; mid = str(self.mid)
        wsutil.ws_send(self.s, {"command": command, "message_id": mid, "args": args})
        for _ in range(800):
            m = wsutil.ws_read(self.s, self.box)
            if m is None:
                return None
            if m.get("message_id") == mid:
                return m

    def library(self, media_type):
        r = self.cmd(WS_CMD[media_type], limit=1000)
        res = (r or {}).get("result")
        return res.get("items") if isinstance(res, dict) else (res or [])

    def play(self, queue_id, uri, option="replace"):
        # "replace" => fresh queue each time (immune to stale/contaminated queue state)
        return self.cmd("player_queues/play_media", queue_id=queue_id, media=uri, option=option)

    def sync(self):
        self.cmd("music/sync")

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass
