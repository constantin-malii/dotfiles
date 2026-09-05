# prompt-builder Skill Design

**Date:** 2026-07-01
**Status:** Approved for Increment 0 (design doc only)
**Component:** `prompt-builder` skill, invoked as `/prompt-builder`

## Goal

Provide a reusable component that transforms rough user task intent into a safe,
deterministic, scoped, execution-ready dispatch prompt for another agent. The output is
copy-paste ready and passes a mandatory lint/repair pass before it is presented.

## Motivation

Previously generated dispatch prompts repeatedly shipped with the same defects:

- truncated words and incomplete sentences
- dangling fragments and broken commands or file paths
- unsafe branch/base assumptions (for example, branching without checking base state)
- overbroad scope and ambiguous optional choices
- missing stop conditions
- incomplete verification

`prompt-builder` exists to eliminate these classes of defect by construction: a fixed
section schema, composable safety profiles, and a lint/repair stage that cannot be skipped.

## Context

Repository conventions that constrain this design:

- Skills live at `claude/skills/<name>/SKILL.md` and deploy to `~/.claude/skills/` via
  `install.sh`, which rsyncs the whole skill directory. Bundled `references/` and
  `examples/` subdirectories deploy automatically.
- A skill's `description` frontmatter is what Claude reads to auto-invoke it; skills are
  also user-invocable as `/<name>`.
- The two closest precedents are the generator skills `skillify` and `verify-template`:
  both take intent, produce an artifact, present it, gate on approval, and save.
- Skill style: numbered Steps with exact commands and expected output, explicit
  "STOP — confirm with user" gates, "do not invent steps", idempotent where possible.
- Docs conventions: specs at `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`;
  workflow index at `docs/claude-code-workflow.md`.

No prompt-lint or eval-corpus pattern exists in the repo today, so that portion is
greenfield.

## Chosen form: skill (not command, not agent)

| Form | Verdict | Reasoning |
|---|---|---|
| Skill | Chosen | Interactive generator with clarifying questions and approval gates — the same shape as `skillify` and `verify-template`. The `description` field gives auto-invocation when Claude is about to write a dispatch prompt. `install.sh` copies the whole directory, so profiles, lint rules, schema, and examples are available via progressive disclosure. |
| Command | Rejected | Single file, no auto-selection, no bundled references. Too thin for profiles plus lint plus schema plus an example corpus. |
| Agent | Rejected | Agents are autonomous doers dispatched to execute a task. This is a user-driven builder with gates; an agent consumes this component's output rather than being its form. |
| Hybrid (skill plus script) | Later | A deterministic `prompt_lint.py` for mechanically checkable defects is a genuine hybrid, scheduled as Increment 3. |

Name rationale: the repo's naming style is plain and descriptive (`skillify`, `tech-debt`,
`verify-template`, `ddup`). `prompt-builder` matches it. No repo-specific reason was found
to prefer an alternative name.

## Architecture

A single skill running a four-stage pipeline:

```
rough intent -> [1 INTAKE] -> [2 ASSEMBLE] -> [3 LINT/REPAIR] -> [4 OUTPUT]
                    |              |                 |                 |
              profile select  core template +  mandatory checklist  fixed schema +
              + minimal Qs     profile overlays  pass + repair        lint report
```

- **Stage 1, Intake.** Capture the rough intent; select a mode and any constraint overlays;
  ask only the minimal questions needed to fill required sections.
- **Stage 2, Assemble.** Fill the twelve core sections from `core-template.md`; apply the
  selected profile overlays from `profiles.md`.
- **Stage 3, Lint/Repair (mandatory, cannot be skipped).** Run every rule in
  `lint-checklist.md` over the draft, auto-repair mechanical defects, and fill or flag
  structural gaps. Emit a short lint report.
- **Stage 4, Output.** Emit the final dispatch prompt in the exact `output-schema.md`
  contract, fenced and copy-paste ready, followed by the lint report.

### Allowed-Files handling

The skill infers a sensible Allowed-Files list from the selected profile and the stated
scope, and asks the user only when scope is genuinely ambiguous and cannot be reasonably
inferred. It does not hard-STOP merely because the list was not stated up front. The lint
stage checks that the Allowed-Files section is present and non-empty, not that intake must
halt.

## Profile model

Two axes, composed with explicit precedence.

- **Mode (mutually exclusive):** `research-only` or `implementation`.
- **Constraint overlays (stackable, and they override the mode on any conflict):**
  `repo-safe`, `live-gated`, `homebrain`.

Precedence, low to high:

```
core < mode < repo-safe < live-gated < homebrain
```

HomeBrain is therefore a mode plus `repo-safe` plus `live-gated` plus the `homebrain`
overlay, which is why its rules subsume the others. This maps one-to-one to the flat list
of profile names (repo-safe, research-only, implementation, live-gated, HomeBrain); the
composition is made explicit so that contradictions resolve deterministically, and
"contradiction" becomes a lint rule.

### HomeBrain overlay rules (verbatim)

- Never edit `main` directly.
- Check that local `main` equals `origin/main` before branching; if not, STOP and report.
- No live Home Assistant, host, API, service, resolver, or exposure changes unless
  explicitly authorized.
- No `BACKLOG.md` edits unless explicitly authorized.
- No stage, commit, or push unless separately approved.
- No AI or Claude attribution.
- Keep the live gate FREE unless the task explicitly claims it.
- Always include changed-files verification.
- Include a secret scan when writing docs or config-like content.

## Default dispatch-prompt sections (twelve)

1. Role
2. Goal
3. Context
4. Inputs / Required Reading
5. Scope
6. Allowed Files / Systems
7. Forbidden Actions
8. Required Steps
9. Verification
10. Stop Conditions
11. Definition of Done
12. Expected Final Report

`core-template.md` will carry per-section authoring guidance so each section is filled with
concrete, defect-free content.

## Mandatory lint concerns

Every generated prompt must be checked against all of the following. Each concern in
`lint-checklist.md` pairs a detect signal with a repair action.

- truncated words
- incomplete sentences
- dangling fragments
- broken commands
- broken file paths
- stale copied instructions
- contradictions
- unsafe git or environment rules
- ambiguous optional choices
- missing allowed-file scope
- missing forbidden actions
- missing verification
- missing stop conditions
- missing definition of done

## Output schema and lint report

Stage 4 emits, in order:

1. The dispatch prompt inside a single fenced block, using the twelve sections above in a
   fixed order so downstream copy-paste is deterministic.
2. A short lint report listing which concerns were checked, what was repaired, and any items
   flagged for the user's attention.

The exact contract lives in `output-schema.md`.

## Validation and evaluation approach

1. **Defect corpus.** Each entry is a redacted snippet exhibiting one defect class plus the
   expected verdict (repair or flag), covering every concern listed above.
2. **Lint eval.** Run Stage 3 against each entry; an entry passes if the defect is detected
   and repaired or flagged. Realistic target: high recall across the enumerated classes.
   Structural classes (missing sections, contradictions, unsafe git) are expected to be
   caught reliably because they are explicit checklist items; mechanically checkable classes
   are hardened toward reliable detection once the Increment 3 script lands. LLM-only lint is
   probabilistic, so the eval reports recall per class rather than asserting perfect
   detection.
3. **Golden eval.** For each profile, a rough-intent input must produce an assembled output
   that contains all required sections and that profile's hard rules. A HomeBrain output, for
   example, must contain the `main` equals `origin/main` check, the live-gate-FREE line,
   changed-files verification, and the secret scan.
4. **Dogfood gate.** Each increment's own implementation prompt must pass the lint rules once
   the checklist exists.
5. **Records.** Results are recorded in `examples/eval.md`.
6. **Corpus source (open decision D1).** Seed from real, redacted prior bad prompts if
   available; otherwise ship clearly labeled synthetic examples and grow the corpus from real
   use. Increments 0 and 1 do not depend on this.

## File layout

```
claude/skills/prompt-builder/
  SKILL.md                       # orchestrator: intake -> assemble -> lint -> output, with gates
  references/
    core-template.md             # the twelve sections plus per-section authoring guidance
    profiles.md                  # modes and overlays, precedence, HomeBrain rules
    lint-checklist.md            # every lint concern: detect signal plus repair action
    output-schema.md             # the exact final-output contract plus lint-report format
  examples/
    golden/                      # exemplar dispatch prompts, one per profile
    defects/                     # redacted bad prompts, each tagged with the rule it violates
    eval.md                      # eval procedure plus results table

docs/superpowers/specs/2026-07-01-prompt-builder-design.md   # this design doc (Increment 0)
docs/claude-code-workflow.md                                  # one added entry (optional, later)
```

No `install.sh` change is needed until Increment 3 adds `prompt_lint.py` and its
`SKILL_SCRIPTS[prompt-builder]` entry.

## Staged implementation plan

- **Increment 0 — Clean design doc only.** This document. No skill files.
- **Increment 1 — Skill skeleton plus references.** Create `SKILL.md` implementing the
  four-stage pipeline, and the four reference files (`core-template.md`, `profiles.md`,
  `lint-checklist.md`, `output-schema.md`). Deployable and invocable, with placeholder-free
  content but no example corpus yet.
- **Increment 2 — Examples and eval corpus.** Add three to five golden examples (one per
  profile), three to five tagged defect examples, and `eval.md` with the results table.
- **Increment 3 — Deterministic lint script.** Add `claude/scripts/prompt_lint.py` for the
  mechanically checkable classes (code-fence balance, trailing truncation, ellipsis
  fragments, path existence, shell-syntax sanity); wire it into Stage 3 and add the
  `SKILL_SCRIPTS[prompt-builder]` entry.

## Risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| R1 | LLM-only lint is probabilistic and may miss mechanical defects | Explicit detect-and-repair per rule now; deterministic `prompt_lint.py` in Increment 3 |
| R2 | Profile composition contradictions (for example, implementation versus live-gated) | Documented precedence; overlays override the mode; "contradiction" is a lint rule |
| R3 | Scope creep in the builder itself | Increment boundaries and stated non-goals; single skill directory; YAGNI |
| R4 | Unsafe git assumptions leak into generated prompts (the core defect) | repo-safe and homebrain overlays hard-code the `main` equals `origin/main` STOP rule; a dedicated unsafe-git lint rule |
| R5 | Secret leakage in generated prompts | A secret-scan lint rule; the HomeBrain overlay mandates it when writing docs or config |
| R6 | Weak eval from missing real examples | Request real redacted prompts (D1); label synthetics clearly |
| R7 | Windows shell breakage (repo is win32; bash plus pwsh) | Lint checks command syntax for the target shell; examples use the correct shell |

## Non-goals

- No separate lint agent.
- No repo-scanning auto-discovery of Allowed Files (the skill infers from profile and scope,
  then asks when ambiguous).
- No hook or automatic wiring into other skills.
- No non-HomeBrain project-specific profiles.
- No scripted, scored eval harness beyond the `eval.md` table.

## Definition of Done per increment

**Increment 0 (this doc):** the design doc exists, is complete, is free of placeholders and
truncation, uses `prompt-builder` and `/prompt-builder` consistently, and captures
architecture, the profile model with precedence, the twelve sections, the full lint-concern
list, the output-schema outline, the 0–3 staging, the eval approach, and the risks.

**Increment 1:** `SKILL.md` plus the four reference files exist and deploy via
`bash install.sh --only prompt-builder`; `/prompt-builder` runs the full
intake-assemble-lint-output pipeline; lint is mandatory and covers every listed concern;
HomeBrain rules appear verbatim; no example corpus required yet.

**Increment 2:** three or more golden examples plus a defect corpus and `eval.md` exist; the
eval table reports per-class recall across the listed defect classes.

**Increment 3:** `prompt_lint.py` exists, is wired into Stage 3 and `SKILL_SCRIPTS`, and
reliably detects the mechanically checkable defect classes.
