# Skill Selection — companion skills and downstream required skills

Skill selection has **two independent layers**, and the recurring mistake is to conflate
them. Keep them separate:

1. **Builder companion skills** — skills that *you, the prompt-builder*, load and use while
   creating the dispatch prompt. They shape how you work; they do **not** appear in the
   output by default.
2. **Downstream required skills** — skills that the *generated dispatch prompt* tells the
   implementer or research agent to use. When present, they appear in an optional
   `REQUIRED SKILLS` section in the emitted prompt.

This guidance is deliberately bounded. Do **not** scan the machine's installed-skill
inventory, do not enumerate the full catalog into a prompt, and do not attach required
skills to every prompt. Pick from the curated shortlist below, or pick none.

---

## Layer 1: Builder companion skills

These are the skills prompt-builder itself reaches for while running the four-stage
pipeline. They stay on the builder side of the boundary.

**For non-trivial prompt-generation work, use both of these:**

- `engineering-skills:senior-prompt-engineer` — sharpen structure, wording, section
  altitude, and eval framing so the dispatch prompt is clear and unambiguous.
- `superpowers:verification-before-completion` — treat as the required final-QA behavior:
  verify the artifact (sections present, lint clean, write-safety consistent, bytes match
  the linted file) before claiming the prompt is done.

**Use only when the task warrants it:**

- `superpowers:brainstorming` — use **only** when the prompt-generation task is
  underdefined, strategic, architectural, or has multiple viable approaches that need to be
  explored before a single dispatch prompt makes sense. Do **not** use it by default for
  routine or simple dispatch prompts; it adds bloat and slows a task that has one obvious
  shape.

**Trivial prompts:** a small, well-defined dispatch prompt (a one-file edit, a narrow
lookup) needs no companion skills — the four-stage pipeline alone is sufficient.

**Hard rule:** builder companion skills are not automatically copied into the generated
dispatch prompt. They govern how you build; they reach the downstream prompt only if they
independently pass the Layer 2 relevance test below.

---

## Layer 2: Downstream required skills

These are the skills the generated prompt instructs its executing agent to use, emitted in
the optional `REQUIRED SKILLS` section (placed right after `ROLE`; see `core-template.md`
and `output-schema.md`).

Selection rules:

- Include a skill **only** when it materially improves the downstream agent's execution
  quality, safety, or adherence to repo convention. "Might be nice" is not enough.
- **Prefer 0–3 skills.** Fewer is better. Three is a ceiling, not a target.
- **Omit the section entirely** when no downstream skill is clearly needed. Most simple
  prompts have no `REQUIRED SKILLS` section at all, and that is correct.
- Never copy builder companion skills into the downstream prompt unless they independently
  earn a place by the relevance test (for example, a prompt whose whole job is to write
  *another* prompt legitimately lists `engineering-skills:senior-prompt-engineer`
  downstream).

---

## Curated selection table (baseline)

Match the task to the closest shape and pick the smallest useful subset. This is a
shortlist, not an inventory; when nothing fits, emit no `REQUIRED SKILLS` section.

| Task shape | Recommended downstream skills (0–3) |
|---|---|
| Prompt building or prompt improvement | `engineering-skills:senior-prompt-engineer`; `superpowers:verification-before-completion`; optionally `superpowers:brainstorming` when underdefined or architectural |
| Multi-file implementation | `superpowers:subagent-driven-development`; `superpowers:verification-before-completion` |
| Bug investigation | `superpowers:systematic-debugging`; `superpowers:verification-before-completion` |
| Architecture or design | `engineering-skills:senior-architect`; `superpowers:verification-before-completion` |
| Backend or API work | `engineering-skills:senior-backend`; `superpowers:verification-before-completion` |
| ML / MLOps / RAG | `engineering-skills:senior-ml-engineer`; `superpowers:verification-before-completion` |
| Test-first implementation | `superpowers:test-driven-development` or `engineering-skills:tdd-guide`; `superpowers:verification-before-completion` |
| PR or code review | `pr-review-toolkit:review-pr` or `code-reviewer`, per repo convention |
| Deep external research | `deep-research` |
| Targeted lookup | `research-lookup` or `perplexity-search` |

Notes on the table:

- `superpowers:verification-before-completion` recurs because it fits most
  implementation-shaped downstream work; it is still subject to the relevance test, so drop
  it for pure lookup or read-only research where there is no artifact to verify.
- Where a row lists an "or", pick the single option that matches the repo's convention or
  the task's framing — do not include both.
- A prompt may combine at most one task-shape row's picks; if two rows seem to apply, the
  task is probably too broad and should be split.

---

## Selection procedure

1. Classify the task into the closest single row of the table above.
2. From that row, select only the skills that materially change execution quality, safety,
   or convention adherence for *this* task. Selecting zero is a valid outcome.
3. Cap the result at three. If more than three feel necessary, the scope is too broad —
   narrow the task rather than the skill list.
4. If one or more skills survive, emit them in the `REQUIRED SKILLS` section right after
   `ROLE`. If none survive, omit the section entirely.

---

## Anti-dumping guardrails

The failure mode this layer prevents is *skill dumping*: padding a prompt with skills that
do not change the outcome. Guard against it:

- **Count:** more than three downstream skills is a signal to prune, not to keep.
- **Relevance:** every listed skill must have a one-line reason tied to this task. If you
  cannot state why it changes the outcome, remove it.
- **No companion leakage:** do not copy `engineering-skills:senior-prompt-engineer`,
  `superpowers:brainstorming`, or `superpowers:verification-before-completion` into the
  downstream prompt merely because you used them while building. They belong downstream only
  when the downstream task independently calls for them.
- **No catalog dumps:** never list skills "for completeness" or "in case they help", and
  never enumerate the installed-skill inventory.
- **Omission is fine:** an absent `REQUIRED SKILLS` section is the correct output for most
  simple prompts. Do not manufacture one.

The lint pass enforces these guardrails; see concern 15 in `lint-checklist.md`.
