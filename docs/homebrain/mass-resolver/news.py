#!/usr/bin/env python3
# News capability: spoken headlines from curated RSS feeds. Python 3.5 safe.
import logging
import capability
import command_result as cr
import newsfeed

LOG = logging.getLogger("resolver")

_DEFAULTS = {"headline_count": 3, "feed_timeout": 4.0, "max_items_per_feed": 10}


def _defaults(news_cfg):
    d = dict(_DEFAULTS)
    d.update((news_cfg or {}).get("defaults", {}))
    return d


class NewsCapability(capability.Capability):
    name = "news"

    def resolve(self, ctx, params):
        news_cfg = ctx.news_cfg or {}
        feeds_cfg = news_cfg.get("feeds", {}) or {}
        d = _defaults(news_cfg)
        label = params.get("topic") or params.get("country")
        if label is not None:
            label = str(label).strip()
        if not label:
            bucket_key = "world"
            requested_label = None
        else:
            key = label.lower()
            if key in feeds_cfg:
                bucket_key = key
                requested_label = None
            else:
                bucket_key = None
                requested_label = label
        if bucket_key:
            feeds = feeds_cfg.get(bucket_key) or []
        else:
            feeds = []
        return {"bucket_key": bucket_key, "requested_label": requested_label,
                "feeds": feeds, "headline_count": d["headline_count"],
                "feed_timeout": d["feed_timeout"], "max_items": d["max_items_per_feed"]}

    def validate(self, ctx, resolved):
        if resolved.get("bucket_key") is None:
            lbl = resolved.get("requested_label") or "that"
            return {"code": "not_found", "reason": "bucket not configured",
                    "chat_text": "I don't have " + lbl + " news set up yet.",
                    "spoken_text": None, "metadata": {"requested": lbl.lower()}}
        if not resolved.get("feeds"):
            return {"code": "not_found", "reason": "bucket not configured",
                    "chat_text": "I don't have that news set up yet.",
                    "spoken_text": None, "metadata": {"requested": resolved.get("bucket_key")}}
        return None

    def execute(self, ctx, resolved, rid):
        raise NotImplementedError("execute lands in Task 5")
