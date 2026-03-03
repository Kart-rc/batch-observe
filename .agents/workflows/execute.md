---
description: Execute an implementation plan
argument-hint: [path-to-plan]
---

# Execute: Implement from Plan

## Plan to Execute

Read plan file: `$ARGUMENTS`

## Execution Instructions

### 1. Read and Understand

- Read the ENTIRE plan carefully
- Understand all tasks and their dependencies
- Note the validation commands to run
- Review the testing strategy

### 2. Execute Tasks in Order using TDD (The Iron Law)

**NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.**

For EACH task in "Step by Step Tasks", apply the **Red-Green-Refactor** cycle:

#### a. RED: Write a Failing Test First
- Identify the behavior to implement for the current task.
- Write one minimal test showing what should happen BEFORE writing production code.
- Focus on testing real behavior, not mocks (unless unavoidable).

#### b. Verify RED: Watch It Fail
- Run the test suite: `$ npm test path/to/test` (or equivalent).
- **MANDATORY**: Ensure the test fails, and it fails for the right reason (feature missing, not a syntax error).

#### c. GREEN: Minimal Code
- Write the simplest code necessary to make the failing test pass.
- Do NOT over-engineer, add features, or refactor other code. Just pass the test.

#### d. Verify GREEN: Watch It Pass
- Run the test suite again.
- **MANDATORY**: Ensure the new test passes, and no existing tests are broken.

#### e. REFACTOR: Clean Up
- Only after the tests are green, refactor the code (remove duplication, improve names, etc.) while keeping tests passing.

#### RED FLAGS - STOP and Start Over if you:
- Write code before the test.
- Write a test after implementation.
- Have a test pass immediately.

### 4. Run Validation and Regression Tests

Execute ALL validation commands from the plan in order. **In addition, you MUST run the full recursive test suite (unit, integration, component, and live dependency tests)** to ensure no existing functionality was broken by the new changes.

```bash
# Run each command exactly as specified in plan
# Run the full test suite (e.g., npm run test:all, or equivalent)
```

If any command or existing test fails:
- Fix the issue (regression)
- Re-run the command/tests
- Continue only when it passes completely

### 5. Final Verification

Before completing:

- ✅ All tasks from plan completed
- ✅ All new feature tests created and passing
- ✅ Full regression test suite passes
- ✅ All validation commands pass
- ✅ Code follows project conventions
- ✅ Documentation added/updated as needed
- ✅ Builds support multiple environments utilizing `.env.example`

## Output Report

Provide summary:

### Completed Tasks
- List of all tasks completed
- Files created (with paths)
- Files modified (with paths)

### Tests Added
- Test files created
- Test cases implemented
- Test results

### Validation Results
```bash
# Output from each validation command
```

### Ready for Commit
- Confirm all changes are complete
- Confirm all validations pass
- Ready for `/commit` command

## Notes

- If you encounter issues not addressed in the plan, document them
- If you need to deviate from the plan, explain why
- If tests fail, fix implementation until they pass
- Don't skip validation steps
