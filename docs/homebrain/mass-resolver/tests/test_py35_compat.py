#!/usr/bin/env python3
"""AN-01 Task 20: the Python 3.5 compatibility sweep, as a test rather than a grep.

The host runs Python 3.5.2; this dev machine runs 3.12. A local test run therefore proves nothing
about the target, and a 3.6-only construct reaches the host as a SyntaxError that takes the whole
resolver down on restart.

The plan specified this sweep as greps. They are not trustworthy here: the pattern for f-strings is
`f"`, which also matches the `f` at the end of an ordinary word followed by a quote -- it fired on
`{"entity_id": entity})` after `"turn_off",` and on a comment containing `"off",`, three separate
times during G2. A parser cannot make that mistake, so these checks walk the AST instead.

This file is deliberately 3.5-safe itself: it is picked up by `unittest discover` on the host, so it
looks post-3.5 AST node types up with getattr and skips the ones that interpreter has never heard of.
On 3.5 the stronger check happens anyway -- ast.parse raises SyntaxError on an f-string, and the test
fails loudly with the file and line.

Run: python tests/test_py35_compat.py
"""
import ast
import io
import os
import sys
import tokenize
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# Everything the announce work touches, plus the test modules -- those are deployed too, for the
# on-host parity run, so they run under 3.5 as well.
MODULES = ["interaction.py", "haconn.py", "config.py", "wsutil.py"]
TEST_MODULES = ["tests/test_interaction.py", "tests/test_haconn.py",
                "tests/test_config.py", "tests/test_wsutil.py",
                "tests/test_py35_compat.py"]


def _node(name):
    """A post-3.5 AST node class, or None where this interpreter has never heard of it."""
    return getattr(ast, name, None)


# name -> (node class or None, what it is and when it arrived)
FORBIDDEN_NODES = [
    ("JoinedStr", _node("JoinedStr"), "an f-string (3.6)"),
    ("FormattedValue", _node("FormattedValue"), "an f-string field (3.6)"),
    ("AnnAssign", _node("AnnAssign"), "a variable annotation (3.6)"),
    ("NamedExpr", _node("NamedExpr"), "a walrus assignment (3.8)"),
    ("AsyncFunctionDef", _node("AsyncFunctionDef"), "an async def"),
    ("Await", _node("Await"), "an await"),
    ("AsyncFor", _node("AsyncFor"), "an async for"),
    ("AsyncWith", _node("AsyncWith"), "an async with"),
]


def _read(rel):
    with io.open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _parse(rel):
    return ast.parse(_read(rel), filename=rel)


def _string_constants(tree):
    """Every string literal in the tree, as (lineno, value)."""
    out = []
    for node in ast.walk(tree):
        # ast.Str is gone in 3.12 and ast.Constant does not exist in 3.5, so handle both.
        if node.__class__.__name__ == "Constant" and isinstance(getattr(node, "value", None), str):
            out.append((getattr(node, "lineno", 0), node.value))
        elif node.__class__.__name__ == "Str":
            out.append((getattr(node, "lineno", 0), getattr(node, "s", "")))
    return out


class SyntaxIsPython35Test(unittest.TestCase):
    """No construct that a 3.5 interpreter cannot parse."""

    def test_no_post_35_syntax_in_the_resolver_modules(self):
        for rel in MODULES + TEST_MODULES:
            tree = _parse(rel)
            for node in ast.walk(tree):
                for name, cls, what in FORBIDDEN_NODES:
                    if cls is not None and isinstance(node, cls):
                        self.fail("%s:%s uses %s, which the host's Python 3.5 cannot parse"
                                  % (rel, getattr(node, "lineno", "?"), what))

    def test_no_numeric_literal_underscores(self):
        # 1_000 is 3.6. The value is invisible in the AST, so this reads the tokens.
        for rel in MODULES + TEST_MODULES:
            path = os.path.join(ROOT, rel)
            with io.open(path, "rb") as fh:
                for tok in tokenize.tokenize(fh.readline):
                    if tok.type == tokenize.NUMBER and "_" in tok.string:
                        self.fail("%s:%d has the numeric literal %s; underscores in numbers are 3.6"
                                  % (rel, tok.start[0], tok.string))

    def test_every_module_parses(self):
        # The same thing py_compile proves, kept here so one command covers the whole sweep.
        for rel in MODULES + TEST_MODULES:
            _parse(rel)


class ConsoleSafeTextTest(unittest.TestCase):
    """No non-ASCII in anything that can reach a log or a console.

    ONBOARDING section 3 records UnicodeEncodeError on non-ASCII console output on this operator's
    machine, so a stray en dash in a log line is a crash rather than a cosmetic problem.

    Scoped to STRING LITERALS on purpose. Comments cannot reach a log, and source is decoded as
    UTF-8 either way (PEP 3120), so a comment's punctuation is harmless -- config.py carries an em
    dash in one from 2026-07-19, long before this work, and it is left alone rather than swept up
    into an unrelated change.
    """

    def test_no_non_ascii_string_literals(self):
        for rel in MODULES + TEST_MODULES:
            for lineno, value in _string_constants(_parse(rel)):
                try:
                    value.encode("ascii")
                except UnicodeEncodeError:
                    self.fail("%s:%d has a non-ASCII string literal (%r); the console cannot print "
                              "it" % (rel, lineno, value[:40]))

    def test_the_shipped_config_json_is_ascii(self):
        raw = _read("config.json")
        try:
            raw.encode("ascii")
        except UnicodeEncodeError:
            self.fail("config.json contains non-ASCII")


class NoSecretsInSourceTest(unittest.TestCase):
    """No credential material in the tree.

    A signed media URL is a bearer credential. Fixtures must build one from an obvious placeholder,
    never from anything resembling a real signature.

    The rule is a heuristic and says so: the text after `authSig=` inside a literal must be empty
    (the placeholder is concatenated on) or upper-case-and-dashes only. A real signature is long and
    mixed-case, so it cannot satisfy that.
    """

    PLACEHOLDER_OK = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")

    def test_no_literal_looks_like_a_real_signature(self):
        for rel in MODULES + TEST_MODULES:
            for lineno, value in _string_constants(_parse(rel)):
                # Only literals that are actually URLs or rooted paths. A credential is only
                # dangerous embedded in something fetchable, and prose that merely NAMES the
                # parameter is not a leak -- this docstring being the first example.
                if "://" not in value and not value.startswith("/"):
                    continue
                low = value.lower()
                for param in ("authsig=", "signature=", "access_token=", "token="):
                    idx = low.find(param)
                    if idx < 0:
                        continue
                    tail = value[idx + len(param):]
                    tail = tail.split("&")[0]
                    if tail and not set(tail).issubset(self.PLACEHOLDER_OK):
                        self.fail("%s:%d has %s%s in a literal, which does not look like a "
                                  "placeholder" % (rel, lineno, param, tail[:24]))

    def test_no_bearer_token_literal(self):
        for rel in MODULES + TEST_MODULES:
            for lineno, value in _string_constants(_parse(rel)):
                low = value.lower()
                if low.startswith("bearer ") and len(value) > 15:
                    self.fail("%s:%d has what looks like a bearer token literal" % (rel, lineno))


if __name__ == "__main__":
    unittest.main(verbosity=2)
