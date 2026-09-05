#!/usr/bin/env python3
# Read-only ceiling-speaker state snapshot (HA state/volume/media + MA active queue).
# Ops/validation helper — run ON THE HOST:  python3 snapshot.py [label]
# No audio, no mutation, no secrets printed. Python 3.5 safe.
import json, sys
import urllib.request
sys.path.insert(0, "/home/costea/mass-resolver")
import config, maconn

HERE = "/home/costea/mass-resolver"
s = config.load_settings(HERE)
label = sys.argv[1] if len(sys.argv) > 1 else "snapshot"
print("===== SNAPSHOT: %s =====" % label)

try:
    tok = open(HERE + "/.ha_token").read().strip()
    url = "http://%s:%d/api/states/%s" % (s.ha_host, s.ha_port, s.ceiling_entity)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
    st = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
    attr = st.get("attributes", {})
    vol = attr.get("volume_level")
    print("HA_STATE: %s" % st.get("state"))
    print("HA_VOLUME: %s%s" % (vol, ("  (%d%%)" % round(vol * 100)) if isinstance(vol, (int, float)) else ""))
    print("HA_MEDIA: title=%r artist=%r" % (attr.get("media_title"), attr.get("media_artist")))
except Exception as e:
    print("HA_ERROR: %r" % e)

try:
    ma = maconn.MA(s.ma_host, s.ma_port, open(HERE + "/.ma_token").read().strip())
    ma.connect()
    res = (ma.cmd("player_queues/get", queue_id=s.queue_id) or {}).get("result") or {}
    items = res.get("items")
    items_n = items if isinstance(items, int) else (len(items) if items else 0)
    ci = res.get("current_item") or {}
    print("MA_QUEUE_STATE: %s" % res.get("state"))
    print("MA_QUEUE_ITEMS: %s" % items_n)
    print("MA_CURRENT_ITEM: %r" % (ci.get("name") if ci else None))
    print("MA_SHUFFLE: %s  REPEAT: %s" % (res.get("shuffle_enabled"), res.get("repeat_mode")))
    ma.close()
except Exception as e:
    print("MA_ERROR: %r" % e)
print("===== END: %s =====" % label)
