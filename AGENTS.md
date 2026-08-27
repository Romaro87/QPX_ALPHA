
---

## QPX_TEST_SCOPE_RULE_V1 - BINDING STANDING RULE

This is a persistent QPX project rule. It applies automatically to all Codex work in this repository until the user explicitly supersedes it.

### Test-scope rule

Routine QPX changes MUST NOT trigger broad regression suites merely because a shared module was touched.

For routine implementation work:

1. Run the focused tests for the behavior actually changed.
2. Run only dependency/regression tests whose behavior could reasonably be affected by the specific semantic change.
3. Do NOT automatically run a pre-existing broad "protected", regression, or qualification bundle solely because a shared/foundation file changed.
4. Additive changes to a shared module do NOT by themselves justify broad regression testing.
5. Broad regression/qualification suites are reserved for:
   - changes with genuinely broad semantic impact;
   - explicit qualification/requalification work;
   - milestone/gate validation where broad testing is specifically required;
   - an explicit user instruction to run them.
6. Test scope must be proportional to the actual change.
7. Previously passing broad tests MUST NOT be rerun merely for ceremony or reassurance.
8. If broader testing is genuinely required, there must be a concrete technical reason tied to the changed behavior.

### Governing intent

The purpose is to prevent unnecessary repeated test execution, wasted compute, wasted Codex usage, and wasted user time while preserving appropriate verification.

The default is:

FOCUSED TESTS + DIRECTLY AFFECTED DEPENDENCIES.

The default is NOT:

FOCUSED TESTS + AUTOMATIC LARGE REGRESSION BUNDLE.

Do not reinterpret this rule into another standing broad-test requirement.

