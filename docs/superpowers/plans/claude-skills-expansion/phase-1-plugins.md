# Phase 1 — Marketplace Plugins + verify.sh Fix

> **Part of:** [Claude Skills Expansion Master Plan](../2026-04-06-claude-skills-expansion.md)

**Goal:** Install 7 marketplace plugins, generalize verify.sh's hardcoded skill loop, and update docs.

**Files:**
- Modify: `verify.sh:156–162`
- Modify: `README.md`
- Modify: `CLAUDE.md`

---

### Task 1: Fix verify.sh skill loop

- [ ] **Step 1: Replace the hardcoded skill loop at line 157**

Current code:
```bash
section "Claude skills"
for skill in jira confluence azure-devops; do
    if [[ -d "$CLAUDE_DIR/skills/$skill" ]]; then
        ok "$skill skill"
    else
        fail "$skill skill not found in ~/.claude/skills/"
    fi
done
```

Replace with:
```bash
section "Claude skills"
for skill_dir in "$REPO_DIR/claude/skills"/*/; do
    skill_name=$(basename "$skill_dir")
    if [[ -d "$CLAUDE_DIR/skills/$skill_name" ]]; then
        ok "$skill_name skill"
    else
        fail "$skill_name skill not found in ~/.claude/skills/ — run: bash install.sh"
    fi
done
```

- [ ] **Step 2: Run verify.sh to confirm existing skills still pass**

```bash
bash verify.sh 2>&1 | grep -A6 "Claude skills"
```

Expected:
```
── Claude skills
  ✅ azure-devops skill
  ✅ confluence skill
  ✅ jira skill
```

- [ ] **Step 3: Commit**

```bash
git add verify.sh
git commit -m "fix: generalize verify.sh skill loop to scan repo directory dynamically"
```

---

### Task 2: Install 7 marketplace plugins

- [ ] **Step 1: Install each plugin**

```bash
claude plugin install commit-commands@claude-plugins-official
claude plugin install code-review@claude-plugins-official
claude plugin install pr-review-toolkit@claude-plugins-official
claude plugin install skill-creator@claude-plugins-official
claude plugin install claude-md-management@claude-plugins-official
claude plugin install claude-code-setup@claude-plugins-official
claude plugin install security-guidance@claude-plugins-official
```

Each expected to output: `Successfully installed <name>`

- [ ] **Step 2: Verify all 11 plugins are installed and enabled**

```bash
claude plugin list
```

Expected — all present with `✔ enabled`:
```
superpowers@claude-plugins-official
engineering-skills@claude-code-skills
finance-skills@claude-code-skills
c-level-skills@claude-code-skills
commit-commands@claude-plugins-official
code-review@claude-plugins-official
pr-review-toolkit@claude-plugins-official
skill-creator@claude-plugins-official
claude-md-management@claude-plugins-official
claude-code-setup@claude-plugins-official
security-guidance@claude-plugins-official
```

---

### Task 3: Update README.md plugin section

- [ ] **Step 1: Replace the existing "Claude Code Plugins" section**

Find the section starting with `## Claude Code Plugins` and replace its install commands and table with:

```markdown
## Claude Code Plugins

Plugins extend Claude Code with additional skills and workflows. Managed by Claude Code's plugin system — versioned and auto-updated independently of dotfiles.

Install on a new machine:
```bash
# Superpowers suite
claude plugin install superpowers@claude-plugins-official
claude plugin install engineering-skills@claude-code-skills
claude plugin install finance-skills@claude-code-skills
claude plugin install c-level-skills@claude-code-skills

# Development workflow
claude plugin install commit-commands@claude-plugins-official
claude plugin install code-review@claude-plugins-official
claude plugin install pr-review-toolkit@claude-plugins-official
claude plugin install skill-creator@claude-plugins-official

# Project maintenance
claude plugin install claude-md-management@claude-plugins-official
claude plugin install claude-code-setup@claude-plugins-official
claude plugin install security-guidance@claude-plugins-official
```

Update all plugins:
```bash
claude plugin update superpowers@claude-plugins-official
claude plugin update engineering-skills@claude-code-skills
claude plugin update finance-skills@claude-code-skills
claude plugin update c-level-skills@claude-code-skills
claude plugin update commit-commands@claude-plugins-official
claude plugin update code-review@claude-plugins-official
claude plugin update pr-review-toolkit@claude-plugins-official
claude plugin update skill-creator@claude-plugins-official
claude plugin update claude-md-management@claude-plugins-official
claude plugin update claude-code-setup@claude-plugins-official
claude plugin update security-guidance@claude-plugins-official
```

| Plugin | What it adds |
|---|---|
| `superpowers` | Brainstorming, planning, subagent-driven development, TDD, code review workflows |
| `engineering-skills` | Architecture analysis, dependency analysis, architecture diagrams |
| `finance-skills` | Financial analysis and modelling skills |
| `c-level-skills` | Executive-level reporting and strategy skills |
| `commit-commands` | `/commit`, `/commit-push-pr` — auto-generates commit messages, pushes, opens PRs |
| `code-review` | `/code-review` — 4 parallel agents review PRs with confidence-scored findings |
| `pr-review-toolkit` | 6 specialized agents: comment accuracy, test coverage, silent failures, type design, general review, simplification |
| `skill-creator` | Create, improve, and benchmark skills; foundation for custom skill development |
| `claude-md-management` | `claude-md-improver` keeps CLAUDE.md accurate; `/revise-claude-md` captures session learnings |
| `claude-code-setup` | Scans a codebase and recommends hooks, skills, MCP servers tailored to it |
| `security-guidance` | Always-on PreToolUse hook — warns about security issues on every file edit |
```

---

### Task 4: Update CLAUDE.md bootstrap

- [ ] **Step 1: Replace the plugin install step in the bootstrap sequence**

Find step 11 (current plugin install step) and replace with:

```bash
# 11. Install Claude Code plugins
# Superpowers suite
claude plugin install superpowers@claude-plugins-official
claude plugin install engineering-skills@claude-code-skills
claude plugin install finance-skills@claude-code-skills
claude plugin install c-level-skills@claude-code-skills

# Development workflow
claude plugin install commit-commands@claude-plugins-official
claude plugin install code-review@claude-plugins-official
claude plugin install pr-review-toolkit@claude-plugins-official
claude plugin install skill-creator@claude-plugins-official

# Project maintenance
claude plugin install claude-md-management@claude-plugins-official
claude plugin install claude-code-setup@claude-plugins-official
claude plugin install security-guidance@claude-plugins-official
```

- [ ] **Step 2: Commit and push**

```bash
git add README.md CLAUDE.md
git commit -m "docs: update plugin list to 11 plugins with install and update commands"
git push
```
