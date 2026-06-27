#!/usr/bin/env python3
# News capability — STUB (full implementation lands in Inc 2). Python 3.5 safe.
def get_news(ctx, params, rid):
    return {"ok": False, "intent": "news", "request_id": rid, "not_implemented": True,
            "reason": "stub", "spoken": "News isn't available yet."}
