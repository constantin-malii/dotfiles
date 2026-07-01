# Core Template — the twelve sections

This is the base structure for every dispatch prompt. Fill all twelve sections, in this
order, before applying profile overlays. Each section below states its purpose, what good
content looks like, and the failure it prevents.

The final prompt uses these exact section headings, in this exact order. See
`output-schema.md` for the emitted contract.

---

## 1. Role

**Purpose:** Tell the executing agent who it is and how to behave.

**Good content:** One or two sentences. Name the environment (repo path, system) and the
working posture ("work like a careful human developer who follows this repo's conventions").

**Prevents:** Vague, personaless prompts that drift in tone or ignore repo conventions.

## 2. Goal

**Purpose:** State the single outcome the agent must achieve.

**Good content:** One sentence, outcome-focused, testable. If there are multiple outcomes,
the scope is probably too large — split the task.

**Prevents:** Overbroad scope; agents optimising for the wrong result.

## 3. Context

**Purpose:** Give the minimum background needed to act correctly.

**Good content:** Why this work exists, where it sits, and any prior decisions that constrain
it. Link to authoritative docs rather than restating them.

**Prevents:** Stale copied instructions; agents re-deriving decisions already made.

## 4. Inputs / Required Reading

**Purpose:** List exactly what the agent must read before acting.

**Good content:** A numbered list of real file paths or URLs, each with a one-line reason.
Order by read priority. Verify every path exists.

**Prevents:** Broken file paths; agents acting without the governing context.

## 5. Scope

**Purpose:** Draw the boundary of the work.

**Good content:** What is in scope, stated concretely. Name what is explicitly out of scope
when it is a likely temptation.

**Prevents:** Scope creep; unrelated refactoring.

## 6. Allowed Files / Systems

**Purpose:** Enumerate what the agent may create, edit, or touch.

**Good content:** Explicit paths or globs the agent may write, and which systems (git, a
service, an API) it may act on. Infer from the profile and scope; ask only when genuinely
ambiguous. This section must be present and non-empty.

**Prevents:** Missing allowed-file scope; edits landing in the wrong place.

## 7. Forbidden Actions

**Purpose:** State the hard "do not" rules.

**Good content:** A bulleted list. Always include the profile's forbidden actions (see
`profiles.md`). Be specific: "do not edit main directly", not "be careful with git". This
section must be present and non-empty.

**Prevents:** Missing forbidden actions; unsafe git or environment behaviour.

## 8. Required Steps

**Purpose:** The ordered procedure to follow.

**Good content:** A numbered list of concrete steps with exact commands where relevant. For
repo work, the first step is usually the base-safety check (see the repo-safe overlay).

**Prevents:** Ambiguous procedure; steps performed out of order.

## 9. Verification

**Purpose:** How the agent proves the work is correct before claiming completion.

**Good content:** Explicit commands to run and the expected output. For repo work, always
include a changed-files check (`git status --porcelain`). This section must be present and
non-empty.

**Prevents:** Missing verification; success claimed without evidence.

## 10. Stop Conditions

**Purpose:** The situations in which the agent must halt and report instead of proceeding.

**Good content:** A bulleted list of concrete triggers, each paired with the action ("STOP
and report"). Always include a stop before any irreversible or outward-facing action. This
section must be present and non-empty.

**Prevents:** Missing stop conditions; agents pushing past a point of no return.

## 11. Definition of Done

**Purpose:** The checklist that defines "finished".

**Good content:** A bulleted list of verifiable conditions. Each item should be objectively
checkable, not aspirational. This section must be present and non-empty.

**Prevents:** Missing definition of done; work declared complete prematurely.

## 12. Expected Final Report

**Purpose:** What the agent must report back.

**Good content:** A bulleted list of the facts the caller needs: what changed, verification
evidence, judgment calls, and the recommended next action.

**Prevents:** Thin or unstructured hand-offs.
