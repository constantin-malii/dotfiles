"""Stub test for arr.py `movies` filter + UTF-8 output. Replaces arr.get with fake data (no network)."""
import io, sys, contextlib
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arr

FAKE = [
    {"title": "Interstellar", "year": 2014, "genres": ["Adventure", "Science Fiction"], "hasFile": True,
     "ratings": {"imdb": {"value": 8.7}}, "movieFile": {"quality": {"quality": {"name": "Bluray-1080p"}}}},
    {"title": "Dune: Part Two", "year": 2024, "genres": ["Science Fiction"], "hasFile": False, "ratings": {"imdb": {"value": 8.4}}},
    {"title": "Source Code", "year": 2011, "genres": ["Thriller", "Science Fiction"], "hasFile": True,
     "ratings": {"imdb": {"value": 7.5}}, "movieFile": {"quality": {"quality": {"name": "WEBDL-1080p"}}}},
    {"title": "Léon: The Professional", "year": 1994, "genres": ["Crime"], "hasFile": True, "ratings": {"imdb": {"value": 8.5}}},
    {"title": "Иван Васильевич меняет профессию", "year": 1973, "genres": ["Comedy", "Science Fiction"], "hasFile": True, "ratings": {}},
]
arr.get = lambda app, endpoint="", **p: FAKE if (app, endpoint) == ("radarr", "movie") else sys.exit("unexpected call")


def run(args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        arr.cmd_movies(args)
    return buf.getvalue()


checks = []
o = run(["--genre", "science fiction", "--min-imdb", "7.5", "--have"])
checks.append(("sci-fi >=7.5 have -> Interstellar, Source Code only",
               "Interstellar" in o and "Source Code" in o and "Dune" not in o and "Иван" not in o and "2 match" in o))
o = run(["--genre", "science fiction", "--missing"])
checks.append(("missing -> Dune only", "Dune: Part Two" in o and "Interstellar" not in o and "1 match" in o))
o = run(["--title", "Иван"])
checks.append(("Cyrillic title search + output intact", "Иван Васильевич" in o and "?" not in o.split("|")[1]))
o = run(["--title", "Léon"])
checks.append(("accented title intact", "Léon: The Professional" in o))
try:
    run(["--bogus"])
    checks.append(("unknown option rejected", False))
except SystemExit as e:
    checks.append(("unknown option rejected", "unknown option" in str(e)))
for name, ok in checks:
    print(("PASS " if ok else "FAIL ") + name)
sys.exit(0 if all(ok for _, ok in checks) else 1)
