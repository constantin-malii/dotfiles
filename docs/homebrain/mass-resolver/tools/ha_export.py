#!/usr/bin/env python3
# INF-09 read-only Home Assistant managed-state exporter.
# Run ON THE HOST:  python3 tools/ha_export.py --manifest <m> --out <dir> [--probe-only]
# Read-only: never writes to Home Assistant. No secrets printed. Python 3.5 safe, stdlib only.
#
# Two of the sources are UNDOCUMENTED frontend routes (script/automation config). They are
# version-coupled: probes fail closed rather than guessing, and every export records the HA
# version that produced it.
#
# This is change control, NOT disaster recovery. It captures a hand-picked app-layer surface;
# it does not replace encrypted off-host Home Assistant backups.
import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wsutil

EXPORTER_VERSION = "1"

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_TRANSPORT = 2
EXIT_CAPABILITY = 3
EXIT_SCHEMA = 4
EXIT_MISSING = 5
EXIT_SECRET = 6
EXIT_PARTIAL = 7


class ExportError(Exception):
    def __init__(self, code, message, detail=None):
        Exception.__init__(self, message)
        self.code = code
        self.message = message
        self.detail = detail or []


# --------------------------------------------------------------------------- allowlists
#
# TIER 1 (envelope): strict. An unknown key is a fail-closed error -- a human inspects it and
#   updates this list. There is deliberately no --allow-unknown-fields escape hatch: an export
#   that silently omits data while reporting success is worse than one that refuses to run.
# TIER 2 (subtree): lossless. HA's action grammar is open-ended and extends every release, so a
#   fixed allowlist over `sequence`/`selector` would either reject valid automations or discard
#   behaviour. These are preserved structurally intact; only mapping-key ORDER is normalized.

SCRIPT_ENVELOPE = frozenset((
    "alias", "description", "mode", "icon", "max", "max_exceeded",
    "fields", "sequence", "variables",
))
SCRIPT_SCALARS = ("alias", "description", "mode", "icon", "max", "max_exceeded")
SCRIPT_SUBTREES = ("sequence", "variables")

FIELD_ENVELOPE = frozenset((
    "name", "description", "required", "example", "default", "advanced", "filter", "selector",
))
FIELD_SCALARS = ("name", "description", "required", "example", "default", "advanced", "filter")

AUTOMATION_ENVELOPE = frozenset((
    "id", "alias", "description", "mode", "max", "max_exceeded", "initial_state",
    "triggers", "trigger", "conditions", "condition", "actions", "action", "variables",
))
AUTOMATION_SCALARS = ("id", "alias", "description", "mode", "max", "max_exceeded", "initial_state")
AUTOMATION_SUBTREES = ("triggers", "trigger", "conditions", "condition",
                       "actions", "action", "variables")

PIPELINE_ENVELOPE = frozenset((
    "id", "name", "conversation_engine", "conversation_language",
    "stt_engine", "stt_language", "tts_engine", "tts_voice", "tts_language",
    "wake_word_entity", "wake_word_id", "prefer_local_intents",
))

STATE_ENVELOPE = frozenset((
    "entity_id", "state", "attributes",
    "last_changed", "last_updated", "last_reported", "context",
))
# Dropped by design: pure runtime churn that would produce a diff on every single export.
RUNTIME_STATE_KEYS = ("last_changed", "last_updated", "last_reported", "context")
SELECT_ATTRS = frozenset(("options", "friendly_name", "icon", "device_class", "editable"))

EXPOSURE_ENTRY = frozenset(("should_expose",))


# --------------------------------------------------------------------------- secret detection
#
# Path-aware, NOT entropy-first. A blanket ">=20 chars of base64 is a secret" rule is unusable
# here: Assist pipeline ids are ULIDs (01kxygpr39jas5hgsf28cph108), RadioBrowser station ids are
# UUIDs, device ids are 32-char hex. An exporter that cannot capture a pipeline id is useless.

SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|token|api_?key|secret|cookie|authorization|credential|private_key)",
    re.IGNORECASE)

VALUE_RULES = (
    ("bearer-token", re.compile(r"Bearer\s+\S+", re.IGNORECASE)),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}")),
    ("pem-private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("url-credentials", re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]+:[^/\s@]+@")),
)

# Exempt from the ENTROPY heuristic only. Rules 1-3 (literal / sensitive key / value shape)
# always apply, so an exemption can never suppress a real secret we know the value of.
IDENTIFIER_PATHS = frozenset((
    "id", "unique_id", "entity_id", "device_id", "pipeline_id", "preferred_pipeline",
    "wake_word_id", "wake_word_entity", "agent_id", "conversation_engine",
    "stt_engine", "tts_engine", "tts_voice", "uri", "media_id", "item_id", "media_content_id",
))

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                     r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
ULID_RE = re.compile(r"^[0-9a-hjkmnp-tv-z]{26}$", re.IGNORECASE)
HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")
ENTROPY_CHARSET_RE = re.compile(r"^[A-Za-z0-9+/=_-]+$")
ENTROPY_MIN_LEN = 20


def is_identifier_shaped(value):
    """UUID / ULID / 32-hex digest -- the id shapes this system actually uses."""
    return bool(UUID_RE.match(value) or ULID_RE.match(value) or HEX32_RE.match(value))


def looks_high_entropy(value):
    if len(value) < ENTROPY_MIN_LEN or not ENTROPY_CHARSET_RE.match(value):
        return False
    has_alpha = any(c.isalpha() for c in value)
    has_digit = any(c.isdigit() for c in value)
    return has_alpha and has_digit


def walk_scalars(obj, path=()):
    """Yield (path_tuple, value) for every scalar. Deterministic order."""
    if isinstance(obj, dict):
        for key in sorted(obj.keys(), key=lambda k: str(k)):
            for item in walk_scalars(obj[key], path + (str(key),)):
                yield item
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            for item in walk_scalars(value, path + ("[%d]" % index,)):
                yield item
    else:
        yield (path, obj)


def scan_secrets(obj, literals=()):
    """Return [(json_path, rule_name)] -- NEVER the value. Traverses the complete payload,
    envelope and preserved subtrees alike, so losslessness cannot become a leak path."""
    findings = []
    for path, value in walk_scalars(obj):
        if not isinstance(value, str) or not value.strip():
            continue
        dotted = ".".join(path)
        key = path[-1] if path else ""

        # Rule 1: literal match against real on-host secrets. Never exempt.
        hit_literal = False
        for literal in literals:
            if literal and literal in value:
                findings.append((dotted, "literal-secret"))
                hit_literal = True
                break
        if hit_literal:
            continue

        # Rule 2: a sensitive key name carrying a non-empty scalar.
        if SENSITIVE_KEY_RE.search(key):
            findings.append((dotted, "sensitive-key"))
            continue

        # Rule 3: values that are secrets whatever the key is.
        matched = None
        for name, rx in VALUE_RULES:
            if rx.search(value):
                matched = name
                break
        if matched:
            findings.append((dotted, matched))
            continue

        # Rule 4: entropy -- narrowed to non-identifier paths and non-identifier shapes.
        if key in IDENTIFIER_PATHS or is_identifier_shaped(value):
            continue
        if looks_high_entropy(value):
            findings.append((dotted, "high-entropy"))
    return findings


# --------------------------------------------------------------------------- normalization

def check_envelope(label, payload, allowed):
    if not isinstance(payload, dict):
        raise ExportError(EXIT_SCHEMA, "%s: expected an object, got %s"
                          % (label, type(payload).__name__))
    unknown = sorted(k for k in payload.keys() if k not in allowed)
    if unknown:
        raise ExportError(
            EXIT_SCHEMA,
            "%s: unknown envelope key(s): %s -- inspect them and update the allowlist in "
            "ha_export.py (there is no runtime override by design)" % (label, ", ".join(unknown)))


def _carry(out, payload, keys):
    for key in keys:
        if key in payload:
            out[key] = payload[key]


def normalize_script(object_id, payload):
    check_envelope("script[%s]" % object_id, payload, SCRIPT_ENVELOPE)
    out = {"object_id": object_id}
    _carry(out, payload, SCRIPT_SCALARS)
    _carry(out, payload, SCRIPT_SUBTREES)          # lossless
    if "fields" in payload:
        fields = {}
        for name, spec in (payload["fields"] or {}).items():
            check_envelope("script[%s].fields[%s]" % (object_id, name), spec, FIELD_ENVELOPE)
            one = {}
            _carry(one, spec, FIELD_SCALARS)
            if "selector" in spec:
                one["selector"] = spec["selector"]  # lossless
            fields[name] = one
        out["fields"] = fields
    return out


def normalize_automation(automation_id, payload):
    check_envelope("automation[%s]" % automation_id, payload, AUTOMATION_ENVELOPE)
    out = {"automation_id": automation_id}
    _carry(out, payload, AUTOMATION_SCALARS)
    _carry(out, payload, AUTOMATION_SUBTREES)      # lossless
    return out


def normalize_pipeline(payload):
    check_envelope("pipeline[%s]" % payload.get("id"), payload, PIPELINE_ENVELOPE)
    return dict(payload)


def normalize_select_state(payload):
    entity_id = (payload or {}).get("entity_id")
    check_envelope("satellite[%s]" % entity_id, payload, STATE_ENVELOPE)
    attrs = payload.get("attributes") or {}
    check_envelope("satellite[%s].attributes" % entity_id, attrs, SELECT_ATTRS)
    out = {"entity_id": entity_id, "state": payload.get("state")}
    if "friendly_name" in attrs:
        out["friendly_name"] = attrs["friendly_name"]
    if "options" in attrs:
        out["options"] = sorted(attrs["options"])   # inventory-like: order carries no meaning
    return out


def normalize_exposure(payload):
    """{entity_id: {assistant: {"should_expose": bool}}} -> sorted, flags only."""
    out = {}
    for entity_id in sorted((payload or {}).keys()):
        assistants = payload[entity_id] or {}
        row = {}
        for assistant in sorted(assistants.keys()):
            entry = assistants[assistant] or {}
            check_envelope("exposure[%s][%s]" % (entity_id, assistant), entry, EXPOSURE_ENTRY)
            row[assistant] = bool(entry.get("should_expose"))
        out[entity_id] = row
    return {"exposed_entities": out}


def render(obj):
    """Canonical bytes. sort_keys recursively orders MAPPING keys (safe: object key order is not
    semantic in HA) and leaves LIST order untouched (it is semantic -- a reordered `sequence` is a
    behaviour change wearing a clean diff). ensure_ascii=False keeps Cyrillic names readable."""
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2)
    return (text + "\n").encode("utf-8")


# --------------------------------------------------------------------------- transaction
#
# "Atomic" means: the canonical tree is never PARTIALLY replaced. It does NOT mean one
# transaction spanning the raw and canonical roots -- they are promoted independently, raw
# first (raw is additive and harmless; canonical output with no source snapshot is the worse
# state to be left in).

def set_mode(path, mode):
    """POSIX only. On Windows chmod merely toggles the read-only bit, and applying it to a
    directory we are about to rename produced a WinError 5 on the dev machine -- so the mode is
    simply not set there. The host is Linux; it is the run that has to enforce this."""
    if mode is not None and os.name == "posix":
        os.chmod(path, mode)


def write_tree(root, files, dir_mode=None, file_mode=None):
    for rel in sorted(files.keys()):
        target = os.path.join(root, rel.replace("/", os.sep))
        parent = os.path.dirname(target)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
            set_mode(parent, dir_mode)
        with open(target, "wb") as handle:
            handle.write(files[rel])
        set_mode(target, file_mode)


def rename_retry(src, dst, attempts=5, delay=0.05):
    """A directory rename can fail transiently when another process holds a brief handle on a
    freshly created directory -- observed as WinError 5 on the Windows dev machine during test
    runs. Retry a few times, then let the error surface: a genuine failure must still fail."""
    last = None
    for attempt in range(attempts):
        try:
            os.rename(src, dst)
            return
        except OSError as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(delay)
    raise last


def prev_dir_for(out_dir, stamp):
    parent = os.path.dirname(os.path.abspath(out_dir)) or "."
    return os.path.join(parent, os.path.basename(os.path.abspath(out_dir)) + ".prev-" + stamp)


def recover_orphan(out_dir):
    """A crash between the two renames of promote_canonical leaves <out>.prev-* with no <out>.
    Detectable and recoverable, not corrupting. Returns a message, or None."""
    abs_out = os.path.abspath(out_dir)
    if os.path.exists(abs_out):
        return None
    parent = os.path.dirname(abs_out) or "."
    if not os.path.isdir(parent):
        return None
    prefix = os.path.basename(abs_out) + ".prev-"
    orphans = sorted(n for n in os.listdir(parent) if n.startswith(prefix))
    if not orphans:
        return None
    newest = orphans[-1]
    os.rename(os.path.join(parent, newest), abs_out)
    return ("recovered interrupted promotion: restored %s -> %s"
            % (newest, os.path.basename(abs_out)))


def promote_canonical(tmp_dir, out_dir, stamp):
    """Two renames -- a directory cannot be replaced in one. On a NORMAL exception the previous
    tree is restored immediately; recover_orphan() covers an actual process crash."""
    abs_out = os.path.abspath(out_dir)
    prev = prev_dir_for(abs_out, stamp)
    had_prev = os.path.exists(abs_out)
    if had_prev:
        rename_retry(abs_out, prev)
    try:
        rename_retry(tmp_dir, abs_out)
    except Exception:
        if had_prev:
            rename_retry(prev, abs_out)
        raise
    if had_prev:
        shutil.rmtree(prev, ignore_errors=True)


def prune_raw(raw_dir, keep):
    if keep is None or keep <= 0 or not os.path.isdir(raw_dir):
        return []
    entries = sorted(n for n in os.listdir(raw_dir)
                     if not n.startswith(".") and os.path.isdir(os.path.join(raw_dir, n)))
    removed = []
    for name in entries[:-keep] if len(entries) > keep else []:
        shutil.rmtree(os.path.join(raw_dir, name), ignore_errors=True)
        removed.append(name)
    return removed


# --------------------------------------------------------------------------- HA access

class HAClient(object):
    """Thin IO shell. Every function above is pure, so the tests never touch a network."""

    def __init__(self, host, port, token, timeout=20):
        self.host = host
        self.port = port
        self.token = token
        self.timeout = timeout
        self._sock = None
        self._box = None
        self._mid = 0

    def rest_get(self, path):
        url = "http://%s:%d%s" % (self.host, self.port, path)
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + self.token})
        try:
            raw = urllib.request.urlopen(req, timeout=self.timeout).read().decode("utf-8")
        except Exception as exc:
            return (0, None, repr(exc))
        try:
            return (200, json.loads(raw), None)
        except Exception:
            return (200, None, "non-JSON body")

    def ws_call(self, message):
        if self._sock is None:
            try:
                self._sock, self._box = wsutil.ws_connect(self.host, self.port, "/api/websocket")
                self._sock.settimeout(self.timeout)
                wsutil.ws_read(self._sock, self._box)                 # auth_required
                wsutil.ws_send(self._sock, {"type": "auth", "access_token": self.token})
                hello = wsutil.ws_read(self._sock, self._box)
                if (hello or {}).get("type") != "auth_ok":
                    raise ExportError(EXIT_TRANSPORT, "websocket auth failed")
            except ExportError:
                raise
            except Exception as exc:
                raise ExportError(EXIT_TRANSPORT, "websocket connect failed: %r" % (exc,))
        self._mid += 1
        payload = dict(message)
        payload["id"] = self._mid
        wsutil.ws_send(self._sock, payload)
        for _ in range(400):
            reply = wsutil.ws_read(self._sock, self._box)
            if reply is None:
                raise ExportError(EXIT_TRANSPORT, "websocket closed mid-call")
            if reply.get("id") == self._mid:
                return reply
        raise ExportError(EXIT_TRANSPORT, "websocket reply never arrived")

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None


def _ws_result(client, msg_type):
    reply = client.ws_call({"type": msg_type})
    if not reply.get("success"):
        raise ExportError(EXIT_CAPABILITY,
                          "websocket '%s' unsupported or failed: %s"
                          % (msg_type, (reply.get("error") or {}).get("message")))
    return reply.get("result")


def collect(client, manifest):
    """Fetch everything INTO MEMORY. Writes nothing anywhere."""
    status, config, err = client.rest_get("/api/config")
    if status != 200 or not isinstance(config, dict):
        raise ExportError(EXIT_TRANSPORT, "GET /api/config failed: %s" % (err or status))
    ha_version = config.get("version")

    status, states, err = client.rest_get("/api/states")
    if status != 200 or not isinstance(states, list):
        raise ExportError(EXIT_TRANSPORT, "GET /api/states failed: %s" % (err or status))

    script_ids = set()
    automation_ids = set()
    states_by_entity = {}
    for state in states:
        entity_id = state.get("entity_id") or ""
        states_by_entity[entity_id] = state
        if entity_id.startswith("script."):
            script_ids.add(entity_id.split(".", 1)[1])
        elif entity_id.startswith("automation."):
            got = (state.get("attributes") or {}).get("id")
            if got:
                automation_ids.add(got)

    # A manifest entry absent from HA's own inventory is a MISSING resource (5). A route that
    # 404s for a resource the inventory says exists is a CAPABILITY failure (3). Keeping those
    # apart is the whole reason the inventory is read first.
    missing = []
    for name in manifest.get("scripts", []):
        if name not in script_ids:
            missing.append("script." + name)
    for name in manifest.get("automations", []):
        if name not in automation_ids:
            missing.append("automation:" + name)
    for entity_id in manifest.get("satellite_entities", []):
        if entity_id not in states_by_entity:
            missing.append(entity_id)
    if missing:
        raise ExportError(EXIT_MISSING, "managed resources absent from Home Assistant",
                          sorted(missing))

    raw = {"ha_version": ha_version, "scripts": {}, "automations": {},
           "satellite": {}, "pipelines": None, "exposure": None}

    for name in manifest.get("scripts", []):
        status, body, err = client.rest_get("/api/config/script/config/" + name)
        if status != 200 or not isinstance(body, dict):
            raise ExportError(EXIT_CAPABILITY,
                              "undocumented route /api/config/script/config/<id> failed for an "
                              "existing script %r: %s" % (name, err or status))
        raw["scripts"][name] = body

    for name in manifest.get("automations", []):
        status, body, err = client.rest_get("/api/config/automation/config/" + name)
        if status != 200 or not isinstance(body, dict):
            raise ExportError(EXIT_CAPABILITY,
                              "undocumented route /api/config/automation/config/<id> failed for "
                              "an existing automation %r: %s" % (name, err or status))
        raw["automations"][name] = body

    for entity_id in manifest.get("satellite_entities", []):
        raw["satellite"][entity_id] = states_by_entity[entity_id]

    raw["pipelines"] = _ws_result(client, "assist_pipeline/pipeline/list")
    raw["exposure"] = _ws_result(client, "homeassistant/expose_entity/list")

    # Pipelines are fetched as a list rather than addressed by id, so a manifest id that does not
    # exist would otherwise export nothing for it and still report success -- silently incomplete,
    # which is the one outcome this tool must never produce.
    available = set(p.get("id") for p in ((raw["pipelines"] or {}).get("pipelines") or []))
    absent = sorted(set(manifest.get("pipelines") or []) - available)
    if absent:
        raise ExportError(EXIT_MISSING, "managed pipelines absent from Home Assistant",
                          ["pipeline:" + p for p in absent])

    unmanaged = {
        "scripts": sorted(script_ids - set(manifest.get("scripts", []))),
        "automations": sorted(automation_ids - set(manifest.get("automations", []))),
    }
    return raw, unmanaged


def build_canonical(raw, manifest):
    """raw payloads -> {relative_path: bytes}. Raises EXIT_SCHEMA on an unknown envelope key."""
    files = {}
    files["meta.json"] = render({"ha_version": raw.get("ha_version"),
                                 "exporter_version": EXPORTER_VERSION})
    for name in sorted(raw["scripts"].keys()):
        files["scripts/%s.json" % name] = render(normalize_script(name, raw["scripts"][name]))
    for name in sorted(raw["automations"].keys()):
        files["automations/%s.json" % name] = render(
            normalize_automation(name, raw["automations"][name]))
    for entity_id in sorted(raw["satellite"].keys()):
        files["satellite/%s.json" % entity_id] = render(
            normalize_select_state(raw["satellite"][entity_id]))

    pipelines = raw.get("pipelines") or {}
    wanted = manifest.get("pipelines")
    for pipeline in (pipelines.get("pipelines") or []):
        if wanted and pipeline.get("id") not in wanted:
            continue
        files["pipelines/%s.json" % pipeline.get("id")] = render(normalize_pipeline(pipeline))
    if "preferred_pipeline" in pipelines:
        files["pipelines/_preferred.json"] = render(
            {"preferred_pipeline": pipelines.get("preferred_pipeline")})

    files["exposure/conversation.json"] = render(normalize_exposure(raw.get("exposure")))
    return files


def raw_files(raw):
    out = {}
    for section in ("scripts", "automations", "satellite"):
        for name in sorted((raw.get(section) or {}).keys()):
            out["%s/%s.json" % (section, name)] = render(raw[section][name])
    out["pipelines.json"] = render(raw.get("pipelines"))
    out["exposure.json"] = render(raw.get("exposure"))
    out["meta.json"] = render({"ha_version": raw.get("ha_version"),
                               "exporter_version": EXPORTER_VERSION,
                               "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    return out


def load_secret_literals(secrets_dir):
    """Read the real on-host secrets for the literal-match rule. Held in memory only and never
    printed, logged or written anywhere."""
    literals = []
    for name in (".ha_token", ".http_secret", ".ma_token"):
        path = os.path.join(secrets_dir, name)
        try:
            with open(path) as handle:
                value = handle.read().strip()
            if value:
                literals.append(value)
        except Exception:
            continue
    return literals


def run_export(client, manifest, out_dir, raw_dir, literals=(), probe_only=False,
               strict_inventory=False, keep_raw=10, stamp=None):
    """Phases 1-7 of the transaction. Nothing is written before the temp-tree phase."""
    stamp = stamp or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    summary = {"stamp": stamp, "written": False, "recovered": None,
               "unmanaged": {}, "pruned_raw": []}

    recovered = recover_orphan(out_dir)
    if recovered:
        summary["recovered"] = recovered

    raw, unmanaged = collect(client, manifest)                  # phases 1-2 (memory only)
    summary["unmanaged"] = unmanaged
    summary["ha_version"] = raw.get("ha_version")
    if strict_inventory:
        extra = sorted(["script." + n for n in unmanaged["scripts"]]
                       + ["automation:" + n for n in unmanaged["automations"]])
        if extra:
            raise ExportError(EXIT_MISSING,
                              "--strict-inventory: unmanaged resources exist in Home Assistant",
                              extra)

    canonical = build_canonical(raw, manifest)                  # phase 3 (memory only)

    findings = scan_secrets(raw, literals)                      # phase 4 (memory only)
    for rel in sorted(canonical.keys()):
        try:
            parsed = json.loads(canonical[rel].decode("utf-8"))
        except Exception:
            continue
        for path, rule in scan_secrets(parsed, literals):
            findings.append(("%s:%s" % (rel, path), rule))
    if findings:
        raise ExportError(EXIT_SECRET, "secret-shaped values found; nothing written",
                          ["%s  [%s]" % (path, rule) for path, rule in findings])

    if probe_only:
        summary["probe_only"] = True
        return summary

    parent = os.path.dirname(os.path.abspath(out_dir)) or "."
    if not os.path.isdir(parent):
        os.makedirs(parent)
    if not os.path.isdir(raw_dir):
        os.makedirs(raw_dir)
        set_mode(raw_dir, 0o700)

    tmp_raw = os.path.join(raw_dir, ".tmp-%d-%s" % (os.getpid(), stamp))
    tmp_out = os.path.join(parent, ".tmp-ha-export-%d-%s" % (os.getpid(), stamp))
    try:                                                        # phase 5
        os.makedirs(tmp_raw)
        set_mode(tmp_raw, 0o700)
        write_tree(tmp_raw, raw_files(raw), dir_mode=0o700, file_mode=0o600)
        os.makedirs(tmp_out)
        write_tree(tmp_out, canonical)
    except Exception:
        shutil.rmtree(tmp_raw, ignore_errors=True)
        shutil.rmtree(tmp_out, ignore_errors=True)
        raise

    # Two runs inside the same second share a stamp; the raw dir must never clobber or collide.
    raw_target = os.path.join(raw_dir, stamp)
    bump = 0
    while os.path.exists(raw_target):
        bump += 1
        raw_target = os.path.join(raw_dir, "%s-%d" % (stamp, bump))
    try:                                                        # phase 6: raw first
        rename_retry(tmp_raw, raw_target)
    except Exception:
        shutil.rmtree(tmp_raw, ignore_errors=True)
        shutil.rmtree(tmp_out, ignore_errors=True)
        raise

    promote_canonical(tmp_out, out_dir, stamp)                  # phase 7
    summary["written"] = True
    summary["files"] = sorted(canonical.keys())
    summary["raw_dir"] = os.path.basename(raw_target)
    summary["pruned_raw"] = prune_raw(raw_dir, keep_raw)
    return summary


# --------------------------------------------------------------------------- cli

def build_parser():
    parser = argparse.ArgumentParser(
        description="Read-only Home Assistant managed-state exporter (INF-09). "
                    "Never writes to Home Assistant.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--raw-dir", default=os.path.expanduser("~/ha-state/raw"))
    parser.add_argument("--secrets-dir", default=os.path.expanduser("~/mass-resolver"))
    parser.add_argument("--ha-host", default="192.168.122.10")
    parser.add_argument("--ha-port", type=int, default=8123)
    parser.add_argument("--probe-only", action="store_true",
                        help="probe and validate every resource; write nothing")
    parser.add_argument("--strict-inventory", action="store_true",
                        help="fail when Home Assistant has resources the manifest omits")
    parser.add_argument("--keep-raw", type=int, default=10)
    parser.add_argument("--summary-json", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        with open(args.manifest) as handle:
            manifest = json.load(handle)
    except Exception as exc:
        sys.stderr.write("cannot read manifest %s: %r\n" % (args.manifest, exc))
        return EXIT_USAGE

    token_path = os.path.join(args.secrets_dir, ".ha_token")
    try:
        with open(token_path) as handle:
            token = handle.read().strip()
    except Exception as exc:
        sys.stderr.write("cannot read HA token: %r\n" % (exc,))
        return EXIT_USAGE

    client = HAClient(args.ha_host, args.ha_port, token)
    try:
        summary = run_export(client, manifest, args.out, args.raw_dir,
                             literals=load_secret_literals(args.secrets_dir),
                             probe_only=args.probe_only,
                             strict_inventory=args.strict_inventory,
                             keep_raw=args.keep_raw)
    except ExportError as exc:
        sys.stderr.write("EXPORT FAILED (%d): %s\n" % (exc.code, exc.message))
        for line in exc.detail:
            sys.stderr.write("  - %s\n" % line)
        return exc.code
    except Exception as exc:
        sys.stderr.write("EXPORT FAILED (%d): unexpected: %r\n" % (EXIT_PARTIAL, exc))
        return EXIT_PARTIAL
    finally:
        client.close()

    if args.summary_json:
        sys.stdout.write(json.dumps(summary, sort_keys=True, indent=2) + "\n")
    else:
        if summary.get("recovered"):
            sys.stdout.write(summary["recovered"] + "\n")
        sys.stdout.write("HA %s  %s\n" % (summary.get("ha_version"),
                                          "PROBE OK (nothing written)" if args.probe_only
                                          else "exported %d files" % len(summary.get("files", []))))
        for section in ("scripts", "automations"):
            extra = summary["unmanaged"].get(section) or []
            if extra:
                sys.stdout.write("  unmanaged %s: %s\n" % (section, ", ".join(extra)))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
