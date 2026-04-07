# DDUP — Duplicate Issue Detector

Check whether a GitHub issue is a duplicate of an existing open issue. Uses the `gh` CLI for all GitHub operations. Requires human confirmation before posting any comment.

## Usage

```
/ddup <issue-number>
```

## Steps

### Step 1: Verify gh authentication

```bash
gh auth status
```

If this fails, stop immediately and tell the user: "Please run `gh auth login` before using /ddup."

### Step 2: Fetch the target issue

```bash
gh issue view <issue-number> --json number,title,body,labels,state
```

If the issue is not found: stop and report "Issue #<number> not found in this repository."

If the issue is already closed: note it ("This issue is closed — continuing analysis") and proceed.

### Step 3: Fetch all open issues

```bash
gh issue list --state open --json number,title,body --limit 200
```

Remove the target issue from the list before analysis.

### Step 4: Semantic duplicate analysis

Compare the target issue against every issue in the list. Assign each a similarity score (0–100):

**Increase the score when:**
- Same root cause or underlying bug
- Same feature being requested, even if described with different words
- Same error message or observable symptom
- Overlapping reproduction steps
- Same component or subsystem affected

**Decrease the score when:**
- Issues share keywords but describe different problems
- One is a sub-task or follow-up of the other (related ≠ duplicate)
- Different root causes even if the same symptom appears
- One is a regression of a previously fixed bug (a new issue, not a duplicate)

### Step 5: Present all findings

List every candidate with score ≥ 40, sorted by score descending:

```
Duplicate analysis for #<target>: "<target title>"

Score 85/100 — #<number>: "<title>"
  Reason: <one sentence explaining the specific overlap>

Score 52/100 — #<number>: "<title>"
  Reason: <one sentence — note if this is "related but not duplicate">

No other candidates above 40.
```

If no candidates ≥ 40: report "No duplicates found for #<number>." and stop.

### Step 6: For the highest match ≥ 70 — draft a comment

Draft this comment and display it to the user before doing anything:

```
This issue appears to be a duplicate of #<original-number>.

<One sentence explaining why: what specific aspect makes them the same problem.>

Closing in favor of #<original-number> where the discussion is ongoing. Please add any additional context there if needed.
```

**STOP — ask the user explicitly: "Shall I post this comment on #<issue-number>? (yes/no)"**

Do not post without a clear "yes".

### Step 7: Post the comment (only after explicit yes)

```bash
gh issue comment <issue-number> --body "<comment text>"
```

Expected output: URL of the posted comment.

Report: "Comment posted: <url>"

**Important:** This command only comments — it never closes an issue. Closing is a separate human decision.
