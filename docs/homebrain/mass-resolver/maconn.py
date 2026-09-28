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

    def playlist_tracks(self, item_id, provider="library", limit=500):
        """Tracks of a library playlist (MR-08). Capped: a huge playlist must not make the
        synchronous tool path slow."""
        r = self.cmd("music/playlists/playlist_tracks", item_id=str(item_id),
                     provider_instance_id_or_domain=provider)
        res = (r or {}).get("result")
        items = res.get("items") if isinstance(res, dict) else (res or [])
        return list(items)[:limit]

    # MR-08c queue helpers (design 4.2). Raw replies: callers check "error_code".
    def queue_state(self, queue_id):
        return self.cmd("player_queues/get", queue_id=queue_id)

    def queue_items(self, queue_id, offset=0, limit=50):
        return self.cmd("player_queues/items", queue_id=queue_id, offset=offset, limit=limit)

    def play_index(self, queue_id, queue_item_id, seek_position=0):
        # One call resumes at a position (spike 3, design 3.2-3): no play-from-0-then-seek blip.
        return self.cmd("player_queues/play_index", queue_id=queue_id, index=queue_item_id,
                        seek_position=int(seek_position))

    def delete_item(self, queue_id, queue_item_id):
        return self.cmd("player_queues/delete_item", queue_id=queue_id, item_id_or_index=queue_item_id)

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
