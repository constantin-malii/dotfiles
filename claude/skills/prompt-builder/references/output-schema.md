# Output Schema — the final contract

Stage 4 emits two things, in this order: the dispatch prompt, then the lint report.

## Part 1: the dispatch prompt

Emit the prompt inside a single fenced code block so it is copy-paste ready. Use the twelve
sections in this exact order, with these exact uppercase headings:

```
ROLE
<one or two sentences>

GOAL
<one sentence, outcome-focused>

CONTEXT
<minimum background; link to authoritative docs>

INPUTS / REQUIRED READING
<numbered list of real paths or URLs, each with a one-line reason>

SCOPE
<what is in scope; note explicit out-of-scope temptations>

ALLOWED FILES / SYSTEMS
<explicit paths or globs and systems the agent may act on>

FORBIDDEN ACTIONS
<bulleted hard "do not" rules, including the profile's>

REQUIRED STEPS
<numbered procedure with exact commands>

VERIFICATION
<commands to run and expected output; changed-files check for repo work>

STOP CONDITIONS
<bulleted triggers, each paired with "STOP and report">

DEFINITION OF DONE
<bulleted, objectively checkable completion criteria>

EXPECTED FINAL REPORT
<bulleted list of facts the caller needs back>
```

Rules for the emitted prompt:
- All twelve sections present and non-empty.
- Fixed order, exact headings.
- Concrete paths and commands; no placeholders, no truncation.
- No AI or Claude attribution anywhere in the prompt.

## Part 2: the lint report

Immediately after the fenced block, emit a short report (plain text, not fenced):

```
Lint report
- Profile: <mode> + <overlays>
- Checked: all 14 concerns
- Repaired: <list what was fixed, or "nothing">
- Flagged (needs your input): <list unknown required inputs, or "none">
- Mechanical checks: by inspection (deterministic script arrives in Increment 3)
```

## Presentation

- Show both parts to the user.
- If the report flagged an unknown required input, ask for it before treating the prompt as
  final.
- Do not emit anything else after the lint report except a direct answer to the user.
