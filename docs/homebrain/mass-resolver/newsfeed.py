#!/usr/bin/env python3
# RSS/Atom news feed fetch + parse -> normalized items. Python 3.5 safe. Stdlib only.
import logging, re, html
from urllib.request import urlopen
import xml.etree.ElementTree as ET

LOG = logging.getLogger("resolver")

_ATOM = "{http://www.w3.org/2005/Atom}"


def _clean(text):
    if not text:
        return ""
    t = html.unescape(text)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def parse(xml_bytes):
    """Parse RSS or Atom bytes -> list of {title, link}. [] on any parse error.

    XML safety (stdlib-only; defusedxml is a disallowed 3rd-party dep): reject any DOCTYPE/ENTITY
    declaration before parsing. Entity-expansion (billion-laughs) and XXE both require one, and
    well-formed RSS/Atom never has one. XML keywords are case-sensitive + uppercase -> exact byte match.
    """
    raw = xml_bytes or b""
    if (b"<!DOCTYPE" in raw) or (b"<!ENTITY" in raw):
        LOG.error("newsfeed parse: rejected feed with DOCTYPE/ENTITY declaration")
        return []
    try:
        root = ET.fromstring(raw)
    except Exception as e:
        LOG.error("newsfeed parse error: %r", e)
        return []
    items = []
    # RSS 2.0: <item><title/><link/>
    for it in root.iter("item"):
        title = _clean(it.findtext("title"))
        if title:
            items.append({"title": title, "link": (it.findtext("link") or "").strip()})
    if items:
        return items
    # Atom: <entry><title/><link href=.../>
    for it in root.iter(_ATOM + "entry"):
        title = _clean(it.findtext(_ATOM + "title"))
        if not title:
            continue
        link = ""
        le = it.find(_ATOM + "link")
        if le is not None:
            link = le.get("href") or ""
        items.append({"title": title, "link": link.strip()})
    return items
