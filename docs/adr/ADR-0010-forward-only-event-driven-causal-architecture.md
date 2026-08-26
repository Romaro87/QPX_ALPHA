# ADR-0010: Forward-Only Event-Driven Causal Architecture

**Status:** Accepted

**Date:** 2026-08-26

---

## Context

QPX is fundamentally forward-only and data/event driven. Its current protected historical dataset happens to contain 15-minute market bars, but that resolution is a property of the dataset, not the architectural clock.

Causality depends on when information legitimately becomes available. At any causal decision point, QPX may use only information available by that point. Chronology may advance through heterogeneous timestamped inputs rather than a fixed sequence of equal-duration bars.

The existing protected Top-100 was intentionally produced through personalized historical discovery and remains the canonical frozen discovery/control artifact. Its role must remain distinct from future prospective qualification. The future operational universe policy has not been selected.

This decision records shared architectural invariants without changing economic behavior, selecting a universe policy, or authorizing implementation.

---

## Decision

### Forward-only causal progression

QPX processes information only in causal forward order. At causal point `T`, a component may use only observations, state, configuration, and governance decisions legitimately available by `T`.

Where applicable, inputs must distinguish their event or effective time from their information-availability time. Equal-time events require deterministic, validated ordering.

### Event-driven chronology

The architectural clock is causal event progression, not market-data resolution. Chronology may advance through validated timestamped events including:

- market bars or updates;
- corporate-action or dividend events;
- volatility observations;
- accounting or settlement events;
- universe-membership events;
- configuration or governance events; and
- other legitimate causal inputs.

### Resolution independence

Fifteen-minute bars are the resolution of the current frozen historical data only. QPX engine, strategy, universe, and qualification infrastructure must not hard-code 15-minute progression or any other fixed market-data resolution.

Changing storage format or feed resolution does not by itself authorize changed strategy economics. Semantically equivalent inputs require demonstrated parity; materially different observation semantics require explicit validation and qualification as a distinct input configuration.

### One causal engine, configurable universe policies

Static frozen and reconstituted universes are policies or configurations operating over the same causal engine. They are not separate causal architectures.

A static policy supplies causally effective frozen membership. A reconstituted policy may emit membership changes only under causally governed rules and schedules. Resolution, cadence, lookback, effective-time behavior, and universe-policy behavior must be explicit validated configuration where applicable, not hidden assumptions.

No reconstitution cadence is selected by this ADR. Daily, weekly, monthly, annual, bar-aligned, or other fixed cadence must not be inferred.

### Candidate V1 boundary

Candidate V1 remains independent of market-data resolution, universe-policy mode, and reconstitution cadence except through its defined causal input contract. Candidate V1 does not own the system clock or universe policy.

This ADR authorizes no modification to Candidate V1, its economics, the strict runner, or their qualification evidence.

### Protected Top-100 role

The existing historical Top-100 remains unchanged as the canonical frozen personalized discovery/control artifact. Existing discovery-period evidence retains its documented research, preliminary-viability, or conditional causal-accounting role. It must not be silently upgraded into prospective, paper, live, or promotion evidence.

### Unresolved universe-policy choice

The future universe-policy choice is explicitly **UNRESOLVED**. Governed options remain:

- static frozen operation;
- reconstituted or walk-forward operation; or
- both as separately governed modes.

This ADR does not prefer or approve any option. Qualification must remain scoped to the exact universe policy, causal inputs, configuration, and evidence interval evaluated.

### Deferred manifest abstraction

`CausalUniverseManifest` remains deferred until universe-policy and governance requirements are sufficiently defined. No universe implementation is authorized by this ADR.

---

## Consequences

Positive:

- Causality is defined consistently across heterogeneous data resolutions and event types.
- Future universe policies can share one causal engine.
- Candidate V1 remains isolated from unresolved universe governance.
- The protected Top-100 remains reproducible without defining QPX as fundamentally static.
- Qualification scope is based on information availability rather than physical bar interval.

Constraints:

- Event types need validated temporal semantics and deterministic ordering.
- Resolution and cadence assumptions must be explicit configuration and provenance where applicable.
- A new resolution or event stream cannot inherit qualification when its observation semantics materially differ.
- Static and reconstituted universe evidence cannot silently qualify one another.

---

## Non-Authorization and Preservation Boundary

This ADR is architectural and additive only. It authorizes no:

- economic behavior change;
- historical replay or research experiment;
- universe rebuild, rerank, or reconstitution;
- static-versus-reconstituted policy selection;
- Candidate V1 or strict-runner modification;
- qualification or promotion status change; or
- paper or live integration.

Protected Candidate V1 lineage and economics, strict causal code and provenance, frozen Top-100 membership/order/data/fingerprints, existing qualification artifacts, permanent controls, and completed research evidence remain untouched.

---

## References

- `QPX_RECOVERY_DECISION_LEDGER.md`, especially Personalized Universe Discovery, Promotion, Top-100 Portfolio Viability, and the protected-boundary continuity addenda.
- `docs/CANDIDATE_V1_STRICT_CAUSAL_QUALIFICATION_2026-08-11.md`.
- `qpx_bot/research_universes/alpaca_top100_qdte1300_thursday_v1.json`.
