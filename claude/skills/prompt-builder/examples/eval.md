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
| 7 | contradictions | contradiction |
| 8 | unsafe git or environment rules | unsafe-git |
| 9 | ambiguous optional choices | ambiguous-broken-stale |
| 10 | missing allowed-file scope | missing-sections |
| 11 | missing forbidden actions | missing-sections |
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

## Results

Record dated runs here. No automated run has been executed yet; this table is seeded empty
on purpose and is filled when the eval is run.

| Date | Golden passed / total | Defect concerns detected / tagged | Notes |
|---|---|---|---|
| (pending) | | | first run to be recorded when eval is executed |
