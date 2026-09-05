#!/usr/bin/env python3
# Acquisition capability — STUB (full implementation lands in Inc 3). Python 3.5 safe.
def acquire(ctx, params, rid):
    return {"ok": False, "intent": "acquire", "request_id": rid, "not_implemented": True,
            "reason": "stub", "spoken": "Music acquisition isn't available yet."}
