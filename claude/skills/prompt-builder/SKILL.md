---
name: prompt-builder
description: Use when creating a dispatch or execution prompt for another agent or subagent. Transforms rough task intent into a safe, deterministic, scoped, copy-paste-ready dispatch prompt, with a mandatory lint/repair pass before output. Invoke before writing any "you are an agent that..." task prompt.
---

# Prompt Builder

You are turning a rough task intent into a finished dispatch prompt for another agent. The
output is a single copy-paste-ready prompt built from a fixed twelve-section schema, shaped
by composable safety profiles, and checked by a mandatory lint/repair pass before you show
it. The purpose is to eliminate, by construction, the recurring defects that plague
hand-written dispatch prompts: truncated words, incomplete sentences, broken commands or
paths, unsafe git assumptions, overbroad scope, ambiguous options, and missing verification,
stop conditions, or definition of done.

## When to use

Invoke this skill whenever you are about to write a task prompt that another agent or
subagent will execute — for example a subagent-driven-development task, a dispatched
research job, or a copy-paste prompt the user will hand to another Claude session.

## Reference files

Load these on demand as each stage needs them. Do not paste their full contents into the
final output; use them to construct and check the prompt.

| File | Load during | Purpose |
|---|---|---|
| `references/core-template.md` | Stage 2 | The twelve sections and per-section authoring guidance |
| `references/profiles.md` | Stage 1 and 2 | Modes, overlays, precedence, and HomeBrain rules |
| `references/lint-checklist.md` | Stage 3 | Every lint concern with its detect signal and repair action |
| `references/output-schema.md` | Stage 4 | The exact final-output contract and lint-report format |

## Pipeline

```
rough intent -> [1 INTAKE] -> [2 ASSEMBLE] -> [3 LINT/REPAIR] -> [4 OUTPUT]
```

Run the four stages in order. Stage 3 is mandatory and must never be skipped.

## Step 1: Intake

1. Capture the rough task intent in one or two sentences. If the user gave a longer brief,
   restate it in your own words so intent is explicit.
2. Read `references/profiles.md`. Select exactly one **mode** and any number of stacking
   **constraint overlays**:
   - Mode (choose one): `research-only` or `implementation`.
   - Overlays (stack as needed): `repo-safe`, `live-gated`, `homebrain`.
   - If the work touches the HomeBrain stack, select the `homebrain` overlay, which pulls in
     `repo-safe` and `live-gated` automatically.
3. Determine the target: which agent or session will run this prompt, and in which
   repository or system.
4. Infer the Allowed Files / Systems list from the selected profile and the stated scope.
   Ask the user only when scope is genuinely ambiguous and cannot be reasonably inferred. Do
   not stop merely because the list was not stated up front.
5. Ask clarifying questions **only** when a required section cannot be filled without the
   answer. Prefer one question at a time. Never invent facts to fill a section.

## Step 2: Assemble

1. Read `references/core-template.md`.
2. Fill all twelve sections in order, following the per-section guidance:
   Role, Goal, Context, Inputs / Required Reading, Scope, Allowed Files / Systems,
   Forbidden Actions, Required Steps, Verification, Stop Conditions, Definition of Done,
   Expected Final Report.
3. Apply the selected profile overlays from `references/profiles.md`, respecting the
   precedence `core < mode < repo-safe < live-gated < homebrain`. When two layers conflict,
   the higher-precedence layer wins.
4. Keep the draft concrete: real paths, real commands, explicit constraints. Every section
   must be present and non-empty.

## Step 3: Lint and repair (mandatory)

1. Read `references/lint-checklist.md`.
2. Run every rule against the assembled draft. For each concern, apply the detect signal;
   if it fires, apply the repair action.
3. Auto-repair mechanical defects (truncated words, incomplete sentences, dangling
   fragments, broken commands, broken paths, stale copied instructions).
4. For structural gaps (missing Allowed Files, Forbidden Actions, Verification, Stop
   Conditions, or Definition of Done), fill them from the profile and scope. If a required
   input is genuinely unknown, flag it in the lint report and ask the user rather than
   guessing.
5. Resolve contradictions in favour of the higher-precedence profile layer, and confirm no
   unsafe git or environment rule survived (for example, branching without a base check).
   In particular, enforce the **Write-safety consistency** invariant (see `profiles.md` and
   lint concern 7), which admits no loophole: `research-only` means zero repository writes
   (no "optional", "single", or "working-tree-only" exception); any write means the prompt
   must be `implementation` + `repo-safe`; the worktree requirement cannot be waived; and a
   task authorization does not override this. Default to chat-only/no-write; if a durable file
   is requested, **STOP and ask** whether to switch to `implementation` + `repo-safe` with a
   worktree — never emit an optional working-tree write under a research-only/no-worktree stance.
6. Record what was checked, what was repaired, and what was flagged. This becomes the lint
   report in Stage 4.

### Deterministic backstop: prompt_lint.py

A deterministic, local-only script covers the mechanically checkable subset of the lint
rules (fence balance, table structure, truncation and dangling-line signals, placeholder
markers, and required-section presence). It does **not** replace the checklist above — the
judgment-based concerns still require your review — but run it as a fast backstop.

Deployed to `~/.claude/scripts/prompt_lint.py` by `install.sh`. Usage:

```bash
# Check the generated dispatch prompt (pipe the raw prompt text on stdin):
printf '%s\n' "$PROMPT_TEXT" | python ~/.claude/scripts/prompt_lint.py --stdin --prompt

# Check markdown docs or the skill's own corpus (structural checks, outside fences):
python ~/.claude/scripts/prompt_lint.py path/to/file.md
python ~/.claude/scripts/prompt_lint.py claude/skills/prompt-builder/examples
```

Exit code 0 means clean; 1 means issues were found (each printed as `location: [check]
message`). Fold any real findings into the repairs before Stage 4.

**Do not proceed to Stage 4 until every lint rule has been run.**

## Step 4: Output

**The single most important rule of this stage: what you lint MUST be what you emit.** The
recurring failure is a builder that lints one copy of the prompt and then *re-types* or
*regenerates* the prompt into its chat response — the regeneration silently corrupts words
(`HomeBrai`, `research-oires`, `variantnt`), and the lint report falsely claims clean because it
checked a different, clean copy. Eliminate the regeneration step entirely: lint a **file**, then
emit **that file's exact bytes** verbatim.

1. Read `references/output-schema.md`.
2. **Write the final dispatch prompt to a file.** Assemble the twelve sections and write them to
   a temp file (e.g. under your scratchpad): call it `$OUT`. From here on, `$OUT` is the *single
   source of truth* for the output — never hold the prompt only "in your head" or retype it.
3. **Lint that exact file** with the deterministic backstop:
   `python ~/.claude/scripts/prompt_lint.py --prompt "$OUT"`
4. **Read `$OUT` back and inspect it word by word, every section** — mid-word truncation
   (`HomeBrai`, `Assistan`, `repositor`), mashed/merged words (`wantrain`, `variantnt`,
   `researcebrain`), dropped characters, and any fragment that is not a complete word or
   sentence. **A clean `prompt_lint.py` result does NOT authorize emission** — the script only
   catches a subset (trailing hyphen, connective-before-break, known-term prefixes); the read of
   `$OUT` is authoritative. Also re-check the **Write-safety consistency** invariant on `$OUT`.
5. **Emit `$OUT` verbatim.** Print the file's exact contents into the fenced block — for example
   `cat "$OUT"` — and copy those exact bytes into the response. **Do not retype, reformat,
   re-summarize, or regenerate the prompt** when composing the reply; the visible fenced text
   must be a byte-for-byte copy of the file you just linted and read. If you cannot guarantee the
   visible text equals `$OUT`, STOP.
6. **If anything is wrong — corruption in `$OUT`, or the visible text differs from `$OUT`, or a
   write-safety contradiction — STOP. Do not emit.** Rebuild `$OUT` from the assembled content,
   re-lint and re-read it, and only emit once the file is clean and you are emitting it verbatim.
   For a write-safety contradiction, STOP and ask whether to switch to `implementation` +
   `repo-safe` with a worktree. Never emit-and-hope.
7. After the fenced block, emit the short lint report: concerns checked, repairs made, and any
   items flagged. It **must** state that the emitted text is a verbatim copy of the linted file
   `$OUT` and that `$OUT` was read and is free of truncation/corruption. **The report may not
   claim "clean" unless the exact bytes shown came from the linted file and passed the read** —
   if the visible text is corrupted or was regenerated separately (even when `prompt_lint.py`
   said clean), do not emit and do not report clean; STOP instead.
8. Present both to the user. If the lint report flagged an unknown required input, ask for
   it before treating the prompt as final.

## Rules

- Stage 3 is never optional. A prompt that has not been linted is not a finished prompt.
- The lint target is the **final emitted text**, not a scratchpad draft. Stage 3 checks the
  draft; Stage 4's final-output hygiene pass re-checks the exact bytes you present. Both are
  mandatory.
- A clean `prompt_lint.py` result never overrides your eyes. If the visible output has a
  truncated or mashed word, it is corrupted — STOP and re-render; do not emit, and do not let
  the lint report say "clean". Emitting corrupted text is a hard failure even if every automated
  check passed.
- **What you lint must be what you emit.** Lint a file and emit that file's exact bytes verbatim
  (`cat`); never retype, reformat, or regenerate the prompt after checking it — regeneration is
  where corruption enters. If the visible text is not a byte-for-byte copy of the linted file,
  the lint report is invalid and you must STOP.
- `research-only` means zero repository writes. If a write is needed, STOP and ask to switch to
  `implementation` + `repo-safe` + worktree — never emit `research-only` + write, with or
  without a worktree.
- Never invent scope, paths, or authorizations. When unsure, flag and ask.
- The final prompt must itself satisfy every lint rule (dogfooding).
- Do not add AI or Claude attribution to any generated prompt.
