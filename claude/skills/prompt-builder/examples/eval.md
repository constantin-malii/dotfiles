# Evaluation — prompt-builder

How to validate that the skill assembles correct prompts and that the lint pass catches the
enumerated defect classes. This is the manual eval for Increments 1 and 2; a scripted,
scored harness is out of scope until later.

## Corpus

**Golden examples** (`examples/golden/`) — one finished, defect-free dispatch prompt per
profile. Used for the golden eval.

| File | Profile demonstrated |
|---|---|
| `golden/research-only.md` | mode research-only |
| `golden/implementation-repo-safe.md` | mode implementation + overlay repo-safe |
| `golden/live-gated-claimed.md` | overlay live-gated, gate explicitly claimed |
| `golden/homebrain.md` | overlay homebrain (implies repo-safe + live-gated), gate free |

**Defect examples** (`examples/defects/`) — each carries a bad excerpt tagged with the lint
concerns it violates and the expected verdict. Hybrid corpus: one real example plus synthetic
examples for the classes real data did not cover.

| File | Source | Concerns covered |
|---|---|---|
| `defects/truncation-corruption.md` | REAL (trimmed) | 1, 2, 3 (+ corrupted table cell) |
| `defects/unsafe-git.md` | SYNTHETIC | 8 |
| `defects/missing-sections.md` | SYNTHETIC | 10, 11, 12, 13, 14 |
| `defects/ambiguous-broken-stale.md` | SYNTHETIC | 4, 5, 6, 9 |
| `defects/contradiction.md` | SYNTHETIC | 7 |
| `defects/research-write-worktree-contradiction.md` | REAL (trimmed) | 7 (write-safety sub-case), 8, 10, 11 |
| `defects/research-optional-write-waiver-regression.md` | REAL (regression) | 7 (write-safety sub-case), 8, 10, 11 |

## Concern coverage matrix

Every one of the 14 lint concerns is exercised by at least one defect example.

| # | Concern | Covered by |
|---|---|---|
| 1 | truncated words | truncation-corruption |
| 2 | incomplete sentences | truncation-corruption |
| 3 | dangling fragments | truncation-corruption |
| 4 | broken commands | ambiguous-broken-stale |
| 5 | broken file paths | ambiguous-broken-stale |
| 6 | stale copied instructions | ambiguous-broken-stale |
| 7 | contradictions | contradiction; research-write-worktree-contradiction; research-optional-write-waiver-regression (write-safety sub-case) |
| 8 | unsafe git or environment rules | unsafe-git; research-write-worktree-contradiction; research-optional-write-waiver-regression |
| 9 | ambiguous optional choices | ambiguous-broken-stale |
| 10 | missing/invalid allowed-file scope | missing-sections; research-write-worktree-contradiction; research-optional-write-waiver-regression |
| 11 | missing forbidden actions / forbidden-allowed conflict | missing-sections; research-write-worktree-contradiction; research-optional-write-waiver-regression |
| 12 | missing verification | missing-sections |
| 13 | missing stop conditions | missing-sections |
| 14 | missing definition of done | missing-sections |

## Golden eval procedure

For each golden file:
1. Take the stated rough intent and profile.
2. Run the skill's assemble and lint stages.
3. Confirm the output contains all twelve sections in order and every hard rule of the stated
   profile (for example, a homebrain output must contain the local `main` equals `origin/main`
   check, the live-gate-free posture, changed-files verification, and the secret scan).
4. Pass if the assembled output matches the golden file's intent and profile rules.

## Defect eval procedure

For each defect file:
1. Feed the bad excerpt through the lint pass.
2. Compare the lint result to the file's expected verdict and expected repair summary.
3. Pass if the lint pass detects every tagged concern and produces the expected repair or
   flag.

## Scoring

- Report **recall per concern**: of the defect entries tagging a concern, how many the lint
  pass detected.
- Structural concerns (7 through 14) are explicit section checks and are expected to reach
  full detection.
- Mechanical concerns (1 through 6) are checked by inspection until the deterministic
  `prompt_lint.py` script lands (Increment 3); record them as inspection-based and do not
  claim perfect detection for them yet.

## Deterministic lint (prompt_lint.py)

The deterministic script `prompt_lint.py` (Increment 3) covers the mechanically checkable
subset: unbalanced code fences, broken markdown tables outside fences, placeholder markers
outside fences and inline code, required-section presence and non-emptiness in prompt mode,
trailing-hyphen / connective-before-break signals, and (prompt mode) the write-safety
contradiction sub-case of concern 7 — a file write granted under a research-only,
no-worktree, or no-main-edit stance. The write-safety check is conservative: it fires only
when an affirmative write grant is present (a "Write:" allowed-files bullet, or a "write
exception" / "working tree only" carve-out), so an ordinary `implementation` + `repo-safe`
prompt (which grants a write *and* requires a worktree) is never flagged.

How to run it as part of the eval:

```bash
# Structural check across the corpus and skill files (expect clean):
python ~/.claude/scripts/prompt_lint.py claude/skills/prompt-builder

# Prompt-mode check on a golden example's embedded prompt (expect clean):
awk '/^```/{f=!f; next} f' claude/skills/prompt-builder/examples/golden/research-only.md \
  | python ~/.claude/scripts/prompt_lint.py --stdin --prompt
```

Recorded run (2026-07-01, Python 3.12):
- File-mode on the full skill dir (`SKILL.md`, references, examples): clean, 0 issues.
- Prompt-mode on all four golden embedded prompts: clean, 0 issues each.
- Prompt-mode on a synthetic bad prompt (only ROLE + GOAL, GOAL ending on a connective):
  11 findings — 10 missing required sections plus 1 dangling line. Detection confirmed.
- Unit behaviour confirmed: unbalanced fence flagged; a broken table INSIDE a fence not
  flagged; placeholder in prose flagged; the same placeholder inside backticks not flagged.

Write-safety detection run (2026-07-01, Python 3.12):
- Prompt-mode on the `research-write-worktree-contradiction` bad excerpt: both write-safety
  contradictions flagged (research-only + write; no-worktree + write), alongside the expected
  missing-section findings for the partial excerpt.
- Prompt-mode on a full 12-section research-only prompt with a working-tree write exception:
  exactly 2 write-safety contradictions, no missing-section noise.
- Prompt-mode on a full 12-section prompt that forbids editing `main` and grants a write with
  no worktree mentioned: the third write-safety branch fires (no-main-edit + write, no worktree).
- Control — a full `implementation` + `repo-safe` prompt granting a write *and* requiring a
  worktree: clean, 0 issues. No false positive. All four goldens also remained clean.

Regression run (2026-07-01, Python 3.12) — the `research-optional-write-waiver-regression`
example (a real generated prompt that slipped the earlier rule):
- Prompt-mode on the full 12-section regression prompt: 3 write-safety contradictions flagged —
  the worktree-requirement waiver, research-only + write, and no-worktree + write — with no
  missing-section noise. The earlier linter missed this because the write was phrased "Write
  (optional …)" / "single optional uncommitted working-tree file" and the worktree was removed by
  an explicit waiver rather than a "do not create worktrees" prohibition; both phrasings are now
  covered.
- The prior `research-write-worktree-contradiction` example still flags (no regression).
- All four goldens remained clean after the broadened patterns (no new false positives).

## Results

The deterministic portion has been run (see above). The golden and defect eval procedures
below also require the judgment-based LLM lint pass; that combined run is recorded here.

| Date | Scope | Result |
|---|---|---|
| 2026-07-01 | Deterministic lint (prompt_lint.py) across corpus + skill | Clean; detection confirmed on synthetic bad inputs |
| 2026-07-01 | Write-safety contradiction (concern 7 sub-case) | Deterministic: 3 bad shapes flagged, control + 4 goldens clean. LLM guidance: profiles.md + lint-checklist.md concern 7/8/10/11 |
| 2026-07-01 | Write-safety regression (optional write + waived worktree) | Deterministic: regression example flagged (3 findings), prior example still flagged, 4 goldens clean. Rule hardened: research-only = zero writes; worktree requirement non-waivable |
| (pending) | LLM golden + defect eval (per-concern recall) | to be recorded when the full lint pass is run |
