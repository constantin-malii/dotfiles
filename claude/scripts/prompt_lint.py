#!/usr/bin/env python3
"""prompt_lint.py — deterministic, local-only linter for prompt-builder dispatch prompts.

This handles MECHANICALLY checkable defects only. It does NOT replace the LLM lint pass
described in the prompt-builder SKILL.md; it is a fast, deterministic backstop for the
subset of lint concerns that can be checked without judgment.

Modes
-----
file (default)
    Lint markdown documents. Checks, all performed OUTSIDE fenced code blocks so that
    intentionally-broken fenced examples (the defect corpus) are not flagged:
      - unbalanced code fences
      - broken markdown table pipe counts
      - obvious truncation markers / dangling fragments
      - suspicious incomplete lines (ending on a connective before a break)
      - placeholder markers (TODO / TBD / FIXME / XXX)

--prompt
    Treat the whole input as a generated dispatch prompt (no surrounding markdown). Checks:
      - all twelve required sections are present and non-empty
      - the same truncation / dangling signals

Input
-----
Paths (files, or directories which are walked for *.md), or --stdin to read one document
from standard input.

Exit codes: 0 = clean, 1 = issues found, 2 = usage error.
No external dependencies (Python 3 standard library only).
"""

import argparse
import os
import re
import sys

REQUIRED_SECTIONS = [
    "ROLE",
    "GOAL",
    "CONTEXT",
    "INPUTS / REQUIRED READING",
    "SCOPE",
    "ALLOWED FILES / SYSTEMS",
    "FORBIDDEN ACTIONS",
    "REQUIRED STEPS",
    "VERIFICATION",
    "STOP CONDITIONS",
    "DEFINITION OF DONE",
    "EXPECTED FINAL REPORT",
]

FENCE_RE = re.compile(r"^\s*```")
PLACEHOLDER_RE = re.compile(r"\b(TODO|TBD|FIXME|XXX)\b")
INLINE_CODE_RE = re.compile(r"`[^`]*`")

# Words that should not end a complete line/paragraph. Kept conservative to avoid flagging
# ordinary soft-wrapped prose (where the sentence continues on the next non-blank line).
CONNECTIVES = {
    "and", "or", "but", "so", "to", "the", "a", "an", "of", "in", "on", "for", "with",
    "at", "by", "from", "into", "than", "that", "is", "are", "was", "were", "be", "will",
}

# A line ending in one of these is a properly terminated sentence/clause, so a trailing
# connective (e.g. "acted on.") is legitimate and must not be treated as dangling.
TERMINATORS = set('.!?:;)]}"\'`')


def compute_fence_flags(lines):
    """Return (flags, unbalanced). flags[i] is True if line i is inside a fenced block
    (fence marker lines themselves count as inside). unbalanced is True if a fence is left
    open at end of file."""
    flags = []
    inside = False
    for line in lines:
        if FENCE_RE.match(line):
            flags.append(True)
            inside = not inside
        else:
            flags.append(inside)
    return flags, inside


def _last_word(stripped):
    words = stripped.split()
    if not words:
        return ""
    return re.sub(r"[^A-Za-z]+$", "", words[-1]).lower()


def _is_structural(s):
    """A stripped line that is a heading, table row, or horizontal-rule / separator."""
    if not s:
        return True
    if s.startswith("#"):
        return True
    if s.startswith("|"):
        return True
    if set(s) <= set("-|: "):
        return True
    return False


def _truncation_findings(lines, flags=None):
    """Trailing-hyphen and connective-before-break signals. If flags is given, lines inside
    fences are skipped."""
    findings = []
    n = len(lines)
    for idx, line in enumerate(lines):
        if flags is not None and flags[idx]:
            continue
        stripped = line.rstrip()
        s = stripped.strip()
        if _is_structural(s):
            continue
        if stripped.endswith("-"):
            findings.append((idx + 1, "truncation",
                             "line ends with '-' (possible truncated word or dangling fragment)"))
        # A properly terminated line is a complete sentence/clause, even if its last word is
        # a preposition ("acted on."). Only unterminated lines can dangle.
        if stripped and stripped[-1] in TERMINATORS:
            continue
        last = _last_word(stripped)
        if last in CONNECTIVES:
            nxt = lines[idx + 1] if idx + 1 < n else ""
            nxt_s = nxt.strip()
            breaks = (nxt_s == "" or nxt_s.startswith("#") or nxt_s.startswith("|")
                      or bool(FENCE_RE.match(nxt)))
            if breaks:
                findings.append((idx + 1, "dangling",
                                 "line ends with connective '%s' before a break "
                                 "(suspicious incomplete line)" % last))
    return findings


def lint_file(text):
    """File mode: lint a markdown document; structural checks apply outside fences only."""
    findings = []
    lines = text.splitlines()
    flags, unbalanced = compute_fence_flags(lines)

    if unbalanced:
        findings.append((len(lines), "fence",
                         "unbalanced code fence (odd number of ``` markers)"))

    # Markdown table pipe consistency, outside fences.
    i = 0
    n = len(lines)
    while i < n:
        if not flags[i] and lines[i].lstrip().startswith("|"):
            block = []
            while i < n and not flags[i] and lines[i].lstrip().startswith("|"):
                block.append((i, lines[i].count("|")))
                i += 1
            base = block[0][1]
            for line_idx, count in block[1:]:
                if count != base:
                    findings.append((line_idx + 1, "table",
                                     "table row has %d pipes, expected %d (broken markdown table)"
                                     % (count, base)))
        else:
            i += 1

    # Placeholder markers, outside fences and outside inline-code spans (so documentation
    # that mentions `TODO` in backticks is not flagged).
    for idx, line in enumerate(lines):
        if flags[idx]:
            continue
        m = PLACEHOLDER_RE.search(INLINE_CODE_RE.sub("", line))
        if m:
            findings.append((idx + 1, "placeholder",
                             "placeholder marker '%s' not allowed outside code fences"
                             % m.group(1)))

    findings.extend(_truncation_findings(lines, flags))
    return findings


def lint_prompt(text):
    """Prompt mode: the whole input is a dispatch prompt. Check section presence,
    non-emptiness, and truncation signals."""
    findings = []
    lines = text.splitlines()

    present = {}
    for idx, line in enumerate(lines):
        s = line.strip()
        if s in REQUIRED_SECTIONS:
            present[s] = idx

    for sec in REQUIRED_SECTIONS:
        if sec not in present:
            findings.append((0, "section", "missing required section: %s" % sec))

    ordered = sorted(present.items(), key=lambda kv: kv[1])
    for i, (sec, pos) in enumerate(ordered):
        end = ordered[i + 1][1] if i + 1 < len(ordered) else len(lines)
        body = [ln for ln in lines[pos + 1:end] if ln.strip()]
        if not body:
            findings.append((pos + 1, "empty-section",
                             "section '%s' is present but empty" % sec))

    findings.extend(_truncation_findings(lines, flags=None))
    return findings


def _gather_files(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, names in os.walk(p):
                for name in names:
                    if name.endswith(".md"):
                        files.append(os.path.join(root, name))
        else:
            files.append(p)
    return sorted(files)


def _report(name, findings):
    count = 0
    for line, check, msg in sorted(findings, key=lambda f: (f[0], f[1])):
        loc = "%s:%d" % (name, line) if line else name
        print("%s: [%s] %s" % (loc, check, msg))
        count += 1
    return count


def main(argv):
    parser = argparse.ArgumentParser(
        description="Deterministic mechanical linter for prompt-builder dispatch prompts.")
    parser.add_argument("paths", nargs="*", help="files or directories (walked for *.md)")
    parser.add_argument("--prompt", action="store_true",
                        help="treat input as a raw dispatch prompt (section + truncation checks)")
    parser.add_argument("--stdin", action="store_true",
                        help="read one document from standard input")
    args = parser.parse_args(argv)

    total = 0
    if args.stdin:
        text = sys.stdin.read()
        findings = lint_prompt(text) if args.prompt else lint_file(text)
        total += _report("<stdin>", findings)
    else:
        files = _gather_files(args.paths)
        if not files:
            parser.print_usage(sys.stderr)
            return 2
        for fp in files:
            try:
                with open(fp, encoding="utf-8") as fh:
                    text = fh.read()
            except OSError as exc:
                print("%s: [io] cannot read: %s" % (fp, exc), file=sys.stderr)
                total += 1
                continue
            findings = lint_prompt(text) if args.prompt else lint_file(text)
            total += _report(fp, findings)

    if total == 0:
        print("prompt_lint: clean (0 issues)")
        return 0
    print("prompt_lint: %d issue(s) found" % total)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
