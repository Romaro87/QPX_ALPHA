
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

---

## QPX_PRE_CODE_GATE_V1 - BINDING STANDING RULE

This is a persistent QPX project rule. It applies automatically to all Codex work in this repository until the user explicitly supersedes it.

The purpose is to prevent "write it, run it, see what breaks" engineering while using the least reasoning, tokens, compute, and user time necessary.

### Risk classification

Before editing code, classify the task:

**LOW RISK** - reporting, pure helpers, focused tests, cosmetic/non-semantic changes.
- Code directly, then run focused tests.

**MEDIUM RISK** - persistence, providers, schedulers, lifecycle, unattended operation, recovery, resource arbitration, operational state machines.
- Before editing, produce a compact pre-code gate, normally no more than 10-20 lines, stating:
  1. existing mechanism/rule being reused;
  2. state being changed;
  3. main failure paths;
  4. restart/recovery behavior;
  5. invariant(s) that must not break;
  6. focused tests that will prove the change.
- If any required behavior is UNKNOWN, stop and report it instead of improvising.

**HIGH RISK** - strategy semantics, accounting, broker/order authority, causal data rules, ML training/governance, promotion, qualification, capital authority.
- Inspect the authoritative code/rules/history first.
- Produce a reviewed design before implementation.
- Do not code until the design resolves state ownership, causal boundaries, failure/restart behavior, invariants, and verification.

### Global stop rule

If implementation exposes a state, condition, dependency, or semantic question that was not covered by the approved design/pre-code gate:

STOP AND REPORT IT.

Do not invent behavior while implementing.
Do not silently patch around an uncovered condition.
Testing is verification of the design, not a substitute for designing the behavior first.

### Resource discipline

Use the shortest sufficient gate for the risk class.

Do not turn medium-risk work into a long architecture essay.

Do not spend large token/compute budgets rediscovering rules already recorded in the repository.

### Completion-report requirement

Every Codex completion report for implementation work must include:

RISK CLASS: LOW | MEDIUM | HIGH
PRE-CODE GATE: SATISFIED | NOT REQUIRED | VIOLATED

If violated, do not represent the task as complete.

---
