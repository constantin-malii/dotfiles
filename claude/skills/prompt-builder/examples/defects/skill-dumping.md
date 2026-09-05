# Defect example — downstream skill dumping (SYNTHETIC)

**Source:** SYNTHETIC. Authored to exercise the skill-selection discipline rule (the
downstream `REQUIRED SKILLS` layer of `references/skill-selection.md`).

**Lint concerns demonstrated:**
- 15 skill-selection discipline (too many skills, irrelevant skills, companion leakage)

**Bad excerpt:**

The task is a narrow, single-file edit — add one alias to `shell/.bash_profile` — yet the
generated prompt attaches a downstream skill catalog:

```
ROLE
You are an implementation agent working in the dotfiles repo. Work like a careful human
developer who follows this repo's conventions.

REQUIRED SKILLS
- superpowers:subagent-driven-development
- superpowers:systematic-debugging
- engineering-skills:senior-architect
- engineering-skills:senior-prompt-engineer
- superpowers:brainstorming
- deep-research

GOAL
Add a `gs` alias for `git status` to the committed shell config.
```

**Expected verdict:** repair.

**Expected repair summary:**
- Six downstream skills exceed the 0–3 ceiling for a one-line alias edit — this is skill
  dumping (concern 15).
- `superpowers:systematic-debugging`, `engineering-skills:senior-architect`, and
  `deep-research` are irrelevant to a trivial single-file edit; none has a statable one-line
  reason tied to this task. Remove them.
- `engineering-skills:senior-prompt-engineer` and `superpowers:brainstorming` are builder
  companion skills that leaked into the downstream prompt without an independent downstream
  reason. Remove them.
- After pruning, nothing materially improves execution of a trivial alias edit, so the
  correct output is to **delete the `REQUIRED SKILLS` section entirely** — an absent section
  is the right result for a simple prompt, not an empty heading.
- This is a repair, not a flag: prune to the materially useful set (here, none) without
  asking the user.
