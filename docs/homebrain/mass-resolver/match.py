#!/usr/bin/env python3
# Pure text matcher for the resolver. No I/O, no deps beyond stdlib. Python 3.5 safe.
import re, difflib


def clean(x):
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-z ]+", " ", (x or "").lower())).strip()


def compact(x):
    return re.sub(r"[^0-9a-z]+", "", (x or "").lower())


def match_rank(query, name):
    """Return 0(exact)..4(close typo) or None. Lower is a better match."""
    if not name:
        return None
    q = clean(query)
    qcore = q.split(" by ")[0].strip() if " by " in q else q   # "<title> by <artist>" -> title
    if not qcore:
        return None
    n = clean(name); nc = compact(name); qc = compact(qcore)
    if n == qcore or (qc and nc == qc):
        return 0
    if n.startswith(qcore) or (qc and nc.startswith(qc)):
        return 1
    if qcore in n or (qc and qc in nc):
        return 2
    if qcore.split() and all(w in n.split() for w in qcore.split()):
        return 3
    if qc and len(qc) >= 4 and difflib.SequenceMatcher(None, qc, nc).ratio() >= 0.86:
        return 4
    return None
