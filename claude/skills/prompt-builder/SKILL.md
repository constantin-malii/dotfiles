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
6. Record what was checked, what was repaired, and what was flagged. This becomes the lint
   report in Stage 4.

**Do not proceed to Stage 4 until every lint rule has been run.**

## Step 4: Output

1. Read `references/output-schema.md`.
2. Emit the final dispatch prompt inside a single fenced block, using the twelve sections in
   the fixed order.
3. After the fenced block, emit the short lint report: concerns checked, repairs made, and
   any items flagged for the user.
4. Present both to the user. If the lint report flagged an unknown required input, ask for
   it before treating the prompt as final.

## Rules

- Stage 3 is never optional. A prompt that has not been linted is not a finished prompt.
- Never invent scope, paths, or authorizations. When unsure, flag and ask.
- The final prompt must itself satisfy every lint rule (dogfooding).
- Do not add AI or Claude attribution to any generated prompt.
