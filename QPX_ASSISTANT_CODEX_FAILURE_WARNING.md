# 🚨🚨🚨 BIG FUCKING WARNING — CHATGPT AND CODEX ARE FUCKING EVERYTHING UP 🚨🚨🚨

The purpose of this file is to stop ChatGPT and Codex from repeatedly
over-engineering QPX_ALPHA, inventing unnecessary blockers, misreading already
governed architecture, and turning skeleton-time development into endless
hardening and redesign.

QPX_ALPHA IS STILL MOSTLY IN SKELETON TIME.

THE JOB RIGHT NOW IS TO BUILD THE FUCKING THING.

HARDENING CAN COME LATER.

DO NOT:
- turn non-critical issues into blockers;
- add gates that were not required;
- reinterpret existing rules more conservatively than intended;
- stop productive work for hypothetical edge cases;
- confuse "Clean-V2 has priority" with "historical work must stop";
- create serial design loops;
- invent another rule to fix failure to follow an existing rule;
- treat skeleton code like final-production banking infrastructure;
- keep moving the goalposts after a milestone passes its stated acceptance criteria.

FOLLOW THE ROAD THAT IS ALREADY GOVERNED.

If something is not actually blocking safe progress, RECORD IT FOR LATER AND
KEEP FUCKING MOVING.

---

Because **we deliberately coded the wrong policy earlier**. This wasn’t some mysterious runtime bug.

When the historical acquisition was made safe to coexist with Clean-V2, the intended rule was:

**Clean-V2 has priority; historical work runs alongside it whenever resources/provider capacity permit.**

But that got translated into two different rules in the implementation:

**Downloads:** allowed during `LIVE_COEXISTENCE`.

**Finalization:** treated as “heavy work” and forced to wait for `OFF_MARKET`.

You can actually see the assumption baked into the code: it uses labels like `FINALIZATION_DEFERRED_DURING_LIVE` and `HEAVY_FINALIZATION_DEFERRED_DURING_LIVE`, and `_drain_pending_finalizations()` refuses to drain unless the mode is `OFF_MARKET`.

So this was not caused by V3. **V3 inherited the existing lifecycle behavior.** The real V3 smoke finally exposed it because batch `00187` successfully downloaded 82 pages while Clean-V2 was running, then hit the special finalization rule and stopped.

The actual mistake was conceptual: **“Clean-V2 gets priority” was incorrectly turned into “some historical work must wait for market close.”** Those are not the same thing.

The capacity system already knows how to answer the question we actually care about:

> Is it safe for historical work to use resources right now without hurting Clean-V2?

If yes, it should download **and finalize**. If no, it yields. Market-open status by itself should never have been another gate.

And because that mistaken rule was intentional, its tests likely confirmed the wrong behavior instead of catching it. The software did precisely what we told it to do.

So the root cause is straightforward: **an over-conservative design decision during the coexistence work, reinforced by me treating “heavy finalization” as off-market-only when that was never your intended architecture.** The fix is removing that special case and letting the existing capacity arbitration govern both parts.

---

# STANDING INTERPRETATION GOING FORWARD

This warning does NOT replace AGENTS.md or existing QPX governance.

Both ChatGPT and Codex must treat `AGENTS.md` and
`QPX_CONTEXT_CONTINUITY_RULE.md` as completion criteria, not optional context.
They must also load and apply `QPX_CODEX_COMPLIANCE_PROMPT.md` before every task;
its sequencing, evidence-to-claim, and completion-audit requirements are
fail-closed and cannot be satisfied retroactively.

It exists because ChatGPT and Codex have repeatedly FAILED TO FOLLOW the
governance already present.

QPX_TEST_SCOPE_RULE_V1 remains binding.

QPX_PRE_CODE_GATE_V1 remains binding.

The intended interpretation during skeleton-time development is:

1. Build the architecture correctly.
2. Prevent known destructive/corrupting mistakes.
3. Fix observed blocking failures.
4. Use focused tests and directly affected dependencies.
5. Keep moving.
6. Record non-critical hardening for later.
7. Do not manufacture another fucking blocker because something could someday
   be more robust.

A milestone that passes its stated acceptance criteria should MOVE FORWARD.

Do not conduct another unsolicited forensic audit looking for hypothetical
reasons to stop it.

HIGH risk does not mean infinite scrutiny.
MEDIUM risk does not mean redesign.
LOW risk does not mean broad testing.

PROPORTIONALITY IS ALREADY THE RULE.

FOLLOW IT.
