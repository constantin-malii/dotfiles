#!/usr/bin/env python3
# Status capability — STUB (full implementation lands in Inc 4). Python 3.5 safe.
def status(ctx, params, rid):
    return {"ok": False, "intent": "status", "request_id": rid, "not_implemented": True,
            "reason": "stub", "spoken": "Now-playing status isn't available yet."}
