---
description: Execute an implementation plan using Subagent-Driven Development
argument-hint: [path-to-plan]
---

# Execute: Implement from Plan (Subagent-Driven)

## Plan to Execute

Read plan file: `$ARGUMENTS`

## Execution Instructions

### 1. Read and Extract Context
- Read the ENTIRE plan carefully (`$ARGUMENTS`).
- Create a TodoWrite list extracting out all tasks along with their full text and context.

### 2. Subagent-Driven Execution Loop
For EVERY task in your TodoWrite list, you must perform the following procedure sequentially. **NEVER dispatch multiple implementation subagents in parallel.**

#### A. Dispatch Implementer Subagent
Read the template `.agents/workflows/prompts/implementer-prompt.md`. Dispatch a fresh subagent equipped with that prompt. Provide the subagent with the full context of the single task it needs to implement.

**Handling Implementer Questions:**
- If the implementer subagent asks questions before or during work, ANSWER them clearly and completely. Provide additional context if needed. Do not rush them.

**Implementer Duties:**
- The implementer subagent MUST use Test-Driven Development (Red-Green-Refactor).
- The implementer subagent will write tests, implement code, commit, and self-review.

#### B. Dispatch Spec Compliance Reviewer Subagent
Once the implementer subagent is finished, read the template `.agents/workflows/prompts/spec-reviewer-prompt.md`. Dispatch a fresh review subagent.

- Ask the reviewer: *Does the implementation code match the spec exactly?* (No missing features, no extra "nice-to-have" features).
- **If Reviewer finds issues (❌):**
  - Dispatch the SAME implementer subagent to fix the spec gaps.
  - Dispatch the Spec Reviewer subagent again for a **re-review**.
  - **Do NOT proceed** to code quality review until Spec compliance is ✅.

#### C. Dispatch Code Quality Reviewer Subagent
Once Spec Compliance is ✅, read the template `.agents/workflows/prompts/code-quality-reviewer-prompt.md`. Dispatch a fresh quality review subagent.

- Ask the reviewer to assess code quality, readability, test coverage, and security.
- **If Reviewer finds issues (❌):**
  - Dispatch the SAME implementer subagent to fix the quality issues.
  - Dispatch the Code Quality Reviewer subagent again for a **re-review**.
  - Repeat until Approved (✅).

#### D. Dispatch QA / Regression Tester Subagent
Once Code Quality is ✅, read the template `.agents/workflows/prompts/qa-tester-prompt.md`. Dispatch a fresh QA subagent.

- Ask the QA subagent to run the full comprehensive test suite (unit, integration, component, live dependency).
- It must aggressively verify that the new implementation has had **no negative impact** on existing or prior features.
- **If Reviewer finds issues (❌):**
  - Dispatch the SAME implementer subagent to fix the regression.
  - Dispatch the QA Reviewer subagent again for a **re-review**.
  - Repeat until Approved (✅).

#### E. Mark Task Complete
- Once the QA/Regression tester approves, mark the task as complete in your TodoWrite list.
- Move to the next task in the plan.

### 3. Final Code Review
Once ALL tasks in the TodoWrite list are complete:
- Dispatch a final code reviewer subagent for the entire implementation to ensure everything works together holistically.

### 4. Finish Development
- Follow project conventions for verifying builds or finishing the development branch.
- Indicate to the user that completion is ready for `/commit` or merging.

## Red Flags - STOP IMMEDIATELY IF:
- You start code quality review BEFORE spec compliance is approved.
- You skip any review loops.
- You let the implementer's self-review replace the actual subagent reviews.
- You move to the next task while either review subagent still has open issues.
- You dispatch multiple implementers in parallel.
