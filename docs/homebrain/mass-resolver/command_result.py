#!/usr/bin/env python3
# Synchronous CommandResult contract: builders + legacy mapping. Python 3.5 safe.
ERROR_CODES = set(["not_found", "invalid_input", "play_failed", "upstream_error",
                   "not_implemented", "unauthorized", "unavailable"])

# legacy reason text -> error code
_REASON_CODE = {"no local match": "not_found", "no match": "not_found", "stub": "not_implemented",
                "play failed": "play_failed", "unknown intent": "invalid_input", "error": "upstream_error"}


def ok(intent, rid, chat_text, spoken_text=None, metadata=None):
    return {"ok": True, "intent": intent, "request_id": rid, "spoken_text": spoken_text,
            "chat_text": chat_text, "error": None, "metadata": metadata or {}, "actions": []}


def err(intent, rid, code, reason, chat_text, spoken_text=None, metadata=None):
    if code not in ERROR_CODES:
        raise ValueError("unknown error code: %s" % code)
    return {"ok": False, "intent": intent, "request_id": rid, "spoken_text": spoken_text,
            "chat_text": chat_text, "error": {"code": code, "reason": reason},
            "metadata": metadata or {}, "actions": []}


def from_legacy(d):
    d = d or {}
    intent = d.get("intent", "unknown"); rid = d.get("request_id", "")
    spoken = d.get("spoken")
    meta = {}
    for k in ("uri", "provider", "candidate", "media_type", "played", "station", "source", "stations", "query"):
        if k in d:
            meta[k] = d[k]
    if d.get("ok"):
        chat = spoken or "Done."
        return ok(intent, rid, chat, spoken_text=spoken, metadata=meta)
    reason = d.get("reason") or "error"
    code = "not_implemented" if d.get("not_implemented") else _REASON_CODE.get(reason, "upstream_error")
    chat = spoken or reason
    return err(intent, rid, code, reason, chat, spoken_text=spoken, metadata=meta)
