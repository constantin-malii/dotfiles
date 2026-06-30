#!/usr/bin/env python3
# Capability lifecycle: resolve -> validate -> execute -> CommandResult. Python 3.5 safe.
import logging
import command_result as cr

LOG = logging.getLogger("resolver")


class Capability(object):
    name = "base"
    def resolve(self, ctx, params):
        raise NotImplementedError
    def validate(self, ctx, resolved):
        return None
    def execute(self, ctx, resolved, rid):
        raise NotImplementedError


def run(cap, ctx, params, rid):
    try:
        resolved = cap.resolve(ctx, params)
        v = cap.validate(ctx, resolved)
        if v is not None:
            return cr.err(cap.name, rid, v.get("code", "invalid_input"), v.get("reason", ""),
                          v.get("chat_text", v.get("reason", "")), spoken_text=v.get("spoken_text"),
                          metadata=v.get("metadata"))
        return cap.execute(ctx, resolved, rid)
    except Exception as e:
        LOG.error("req=%s capability=%s error: %r", rid, getattr(cap, "name", "?"), e)
        return cr.err(getattr(cap, "name", "unknown"), rid, "upstream_error", repr(e),
                      "Sorry, something went wrong.")
