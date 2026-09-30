#!/usr/bin/env python3
"""HA-08: push repo-authored Home Assistant scripts/automations (canonical JSON under docs/homebrain/ha/)
to the live instance, backing up whatever is overwritten and reading the result back.

Runs from the operator workstation, not the host. Python 3.5-safe (no f-strings).

  python tools/ha_apply.py --token-file PATH --backup-dir DIR [--dry-run | --delete] FILE [FILE ...]

Exit codes: 0 ok, 1 usage or file error, 2 transport or HTTP error, 3 read-back mismatch.
The token is never printed.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "http://192.168.1.104:8123"


class ApplyError(Exception):
    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code


def load_resource(path):
    """-> (kind, rid, body): kind 'script' or 'automation'; body is what HA's config API stores."""
    with open(path, encoding="utf-8") as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ApplyError(1, "%s: not a JSON object" % path)
    is_script = "object_id" in obj
    is_auto = "automation_id" in obj
    if is_script == is_auto:
        raise ApplyError(1, "%s: needs exactly one of object_id / automation_id" % path)
    if is_script:
        kind, rid = "script", obj["object_id"]
    else:
        kind, rid = "automation", obj["automation_id"]
        if obj.get("id") != rid:
            raise ApplyError(1, "%s: id %r does not match automation_id %r" % (path, obj.get("id"), rid))
    if not isinstance(rid, str) or not rid or "/" in rid:
        raise ApplyError(1, "%s: invalid id %r" % (path, rid))
    body = dict((k, v) for k, v in obj.items() if k not in ("object_id", "automation_id"))
    return kind, rid, body


class HttpClient(object):
    def __init__(self, base, token, timeout=20):
        self.base = base.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, method, path, obj=None):
        data = None if obj is None else json.dumps(obj).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Authorization": "Bearer " + self.token,
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw.decode("utf-8")) if raw else None)
        except urllib.error.HTTPError as err:
            # HA's config API explains a rejection in the body ({"message": ...}); keep it for the error text.
            detail = err.read().decode("utf-8", "replace")[:500]
            return err.code, {"_error_body": detail}
        except (urllib.error.URLError, OSError) as err:
            raise ApplyError(2, "transport error on %s %s: %s" % (method, path, err))


def config_path(kind, rid):
    return "/api/config/%s/config/%s" % (kind, rid)


def why(resp):
    """The server's explanation of an error response, if it sent one."""
    if isinstance(resp, dict) and resp.get("_error_body"):
        return ": %s" % resp["_error_body"]
    return ""


def backup(client, kind, rid, backup_dir, stamp):
    """Save the live config before touching it. -> backup path, or None if the resource does not exist."""
    status, current = client.request("GET", config_path(kind, rid))
    if status == 404:
        return None
    if status != 200:
        raise ApplyError(2, "GET %s -> HTTP %s%s" % (config_path(kind, rid), status, why(current)))
    if not os.path.isdir(backup_dir):
        os.makedirs(backup_dir)
    path = os.path.join(backup_dir, "%s-%s-%s.json" % (kind, rid, stamp))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(current, fh, sort_keys=True, indent=2, ensure_ascii=False)
        fh.write("\n")
    return path


def apply_one(client, path, backup_dir, stamp, dry_run=False, delete=False, out=print):
    kind, rid, body = load_resource(path)
    saved = backup(client, kind, rid, backup_dir, stamp)
    out("%s %s.%s backup=%s" % ("DELETE" if delete else "APPLY", kind, rid, saved or "none (not present)"))
    if dry_run:
        out("  dry-run: nothing sent")
        return
    if delete:
        if saved is None:
            out("  not present: nothing to delete")
            return
        status, resp = client.request("DELETE", config_path(kind, rid))
        if status != 200:
            raise ApplyError(2, "DELETE %s -> HTTP %s%s" % (config_path(kind, rid), status, why(resp)))
        status, _ = client.request("GET", config_path(kind, rid))
        if status != 404:
            raise ApplyError(3, "%s.%s still present after DELETE (HTTP %s)" % (kind, rid, status))
        out("  deleted")
        return
    status, resp = client.request("POST", config_path(kind, rid), body)
    if status != 200:
        raise ApplyError(2, "POST %s -> HTTP %s%s" % (config_path(kind, rid), status, why(resp)))
    status, back = client.request("GET", config_path(kind, rid))
    if status != 200 or back != body:
        raise ApplyError(3, "%s.%s read-back differs from %s" % (kind, rid, path))
    out("  applied; read-back matches the file")


def read_token(path):
    with open(path, encoding="utf-8-sig") as fh:
        raw = fh.read().strip()
    token = raw.split(":", 1)[1].strip() if raw.lower().startswith("token:") else raw
    if not token:
        raise ApplyError(1, "token file is empty")
    return token


def main(argv=None, client=None, out=print):
    ap = argparse.ArgumentParser(description="Push repo-authored HA scripts/automations with backup + read-back.")
    ap.add_argument("--token-file")
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--backup-dir", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args(argv)
    if args.dry_run and args.delete:
        out("ERROR: --dry-run and --delete are exclusive")
        return 1
    stamp = time.strftime("%Y%m%d-%H%M%S")
    try:
        # One timestamp per run: the same resource twice would overwrite its first backup with the
        # already-pushed state and lose the true original. Refuse before touching HA.
        seen = set()
        for path in args.files:
            key = load_resource(path)[:2]
            if key in seen:
                raise ApplyError(1, "%s.%s is given more than once in one run" % key)
            seen.add(key)
        if client is None:
            if not args.token_file:
                raise ApplyError(1, "--token-file is required")
            client = HttpClient(args.base, read_token(args.token_file))
        for path in args.files:
            apply_one(client, path, args.backup_dir, stamp, args.dry_run, args.delete, out)
    except ApplyError as err:
        out("ERROR: %s" % err)
        return err.code
    return 0


if __name__ == "__main__":
    sys.exit(main())
