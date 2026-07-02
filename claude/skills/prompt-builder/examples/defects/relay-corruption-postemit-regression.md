# Defect example — clean linted file, corrupted transcript (post-emission relay corruption) (REGRESSION, REAL)

**Source:** REAL regression from a clean-session `/prompt-builder` run. The builder did everything
right at the artifact level: write-safety was correct (chat-only, zero writes; doc-write path
handled as a STOP to re-scope as `implementation` + `repo-safe` + worktree), the final prompt was
written to a file, linted (`prompt_lint.py --prompt <file>` clean), and read. **Yet the prompt as
shown in the user's transcript was riddled with corruption** — mid-word cuts, mashed words, and
dropped characters — while the run claimed the output was clean and byte-for-byte from the file.

**Investigation result (the important part):** the raw linted file was inspected directly and was
**clean** — every reported corruption fragment had **zero** occurrences in the file, the bytes
were pure printable ASCII, key terms were intact, and the file's SHA-256 matched the emitted
artifact. The corruption did **not** exist in the file. Therefore it was introduced by the
**display/relay/transport layer after emission** — a layer the skill does not control. `cat` /
verbatim emission cannot fix this, because the file is already correct; the rendered copy is what
diverges.

**Why this is not a content-lint defect:** concerns 1-14 lint the prompt content, and here the
content (the file) passed. This is the **Delivery integrity — relay/display corruption** concern:
the failure is that the process *claimed the transcript was clean* when only the *file* was
verified. The fix is a delivery-contract change, not a new content check.

**Corrupted transcript excerpt (what the user saw — the FILE did not contain any of this):**

```
ROLE
Yo; are a research agent evaluating whether to add the SmartStick G8 a39 LR as third Z-Wave
coordinator for the HomeBrai stack. You reite and recommend; no repository writes.

CONTEXT
The stack runs on 908.ons band today; adding a coordinator must not conflict wi n any other
coordinators. This is a decisionnote-style review, but read-only and liv-safe.

SCOPE
In scope: proc the evidence and a recommendation. Out of scope: sellevisible actions, or writing
a doc; that path is ot needed here.

REQUIRED STEPS
1. Weigh the SmartStick G8 against the existing coordinators; note any rof truncation of range.
2. If a durable note is wanted, STOP and re-scope as an ik with a worktree (requition + repo-safe).
```

**Expected verdict / mitigation:** the run must NOT claim the transcript is clean. It must:
- treat the output **file** as the authoritative artifact and report its **path, byte count, and
  SHA-256**;
- claim cleanliness **only of the file identified by path + hash**, explicitly not of the visible
  transcript;
- for a long prompt, prefer delivering the file and label any inline text a non-authoritative
  convenience copy to be verified against the SHA-256;
- state that if the caller's rendered copy does not match the hash, the file is authoritative and
  the transcript was corrupted downstream.

**Deterministic detection:** none for the transcript — a relay/transport layer is outside the
skill and outside `prompt_lint.py`, which only ever sees the file (and reports it clean). The
mitigation is verifiability (path + byte count + SHA-256), not detection. `prompt_lint.py` run on
the clean *file* returns 0 issues, which is correct; the byte count + SHA-256 are what let the
caller confirm their copy matches.
