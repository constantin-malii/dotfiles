# Claude Skills Expansion — Master Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan phase-by-phase. Execute phases in order. Each phase is independently committable and testable.

**Goal:** Expand the dotfiles Claude Code setup with 7 marketplace plugins and 4 custom-built skills/commands derived from the Anthropic team's internal workflow.

**Spec:** `docs/superpowers/specs/2026-04-06-claude-skills-expansion-design.md`

---

## Phases

| Phase | Plan | Deliverable | Depends on |
|-------|------|-------------|------------|
| 1 | [Phase 1 — Marketplace Plugins + verify.sh](claude-skills-expansion/phase-1-plugins.md) | 7 plugins installed, verify.sh generalized, docs updated | Nothing |
| 2 | [Phase 2 — Skillify Skill](claude-skills-expansion/phase-2-skillify.md) | `/skillify` converts sessions into reusable skills | Phase 1 (skill-creator plugin) |
| 3 | [Phase 3 — Tech Debt Skill](claude-skills-expansion/phase-3-tech-debt.md) | `/tech-debt` finds duplication end-of-session | Phase 1 |
| 4 | [Phase 4 — DDUP Command](claude-skills-expansion/phase-4-ddup.md) | `/ddup` detects duplicate GitHub issues | Phase 1 |
| 5 | [Phase 5 — Verify Template Skill](claude-skills-expansion/phase-5-verify-template.md) | `/verify-template` generates project-specific verify skills | Phase 1 |

---

## File Map (all phases)

| File | Action | Phase |
|------|--------|-------|
| `verify.sh:157–162` | Modify — generalize hardcoded skill loop | 1 |
| `README.md` | Modify — update plugin table + add custom skills section | 1, post |
| `CLAUDE.md` | Modify — update bootstrap plugin commands | 1 |
| `claude/skills/skillify/SKILL.md` | Create | 2 |
| `claude/skills/tech-debt/SKILL.md` | Create | 3 |
| `claude/commands/ddup.md` | Create | 4 |
| `claude/skills/verify-template/SKILL.md` | Create | 5 |

---

## Success Criteria (all phases)

- `claude plugin list` shows all 11 plugins installed and enabled
- `bash verify.sh` passes with dynamic skill detection (not hardcoded names)
- `/skillify` generates a valid SKILL.md from a described session
- `/tech-debt` detects duplication, discovers toolchain, runs verification
- `/ddup <number>` fetches issues via `gh`, scores matches, requires confirmation before posting
- `/verify-template` discovers test/lint commands and writes `.claude/skills/verify/SKILL.md`
