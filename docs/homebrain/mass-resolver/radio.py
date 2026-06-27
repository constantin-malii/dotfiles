#!/usr/bin/env python3
# Radio capability — STUB (full implementation lands in Inc 1). Python 3.5 safe.
def resolve_radio(ctx, params, rid):
    return {"ok": False, "intent": "radio", "request_id": rid, "not_implemented": True,
            "reason": "stub", "spoken": "Radio control through the assistant isn't available yet."}
