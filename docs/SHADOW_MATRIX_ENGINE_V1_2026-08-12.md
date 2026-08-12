# Shadow Matrix Engine V1

Status: research orchestration and state-isolation foundation only. It does not execute strategies, fabricate trades, promote a Champion, or authorize production capital.

## Provenance

- Candidate V1 qualification: `7213db1e17fedce9e923889b116775cca121f766`
- Qualified fixed-25 variant: `bba0f48273815ede42374015db7c5770bf446962`
- Dynamic Sizing paired-cap evidence: `625cb218d9ec6b15278716dad648d9e25614bb04`
- Research/CI parent: `cf1d059a54efdbe455e2f9edf340662d15d57aa3`

## Registry-owned matrix

`qpx_bot/shadow_matrix/configs/shadow_matrix_v1.json` is the authoritative V1 registry. It defines exactly nine immutable identities in deterministic dispatch order:

1. `permanent_control`
2. `fixed_25`
3. `dynamic_25`
4. `fixed_40`
5. `dynamic_40`
6. `fixed_60`
7. `dynamic_60`
8. `fixed_90`
9. `dynamic_90`

The permanent control and fixed 90 remain separate governance identities even though both currently use a 90% hard cap with Dynamic Sizing disabled. Automatic promotion is explicitly forbidden.

Every Shadow starts with its own QDTE state ($1,438.00), swing cash ($5.34), tax reserve, positions, pending orders, accelerator state, metrics, and event/checkpoint state. Configuration dataclasses are frozen and carry deterministic SHA-256 fingerprints. The Dynamic variants use the unchanged V1 tiers:

- utilization below 0.25: 1.00
- 0.25 to below 0.50: 0.85
- 0.50 to below 0.75: 0.70
- 0.75 or above: 0.50

Within each fixed/dynamic pair, strategy, starting-state profile, and hard cap are identical. The fixed arm disables Dynamic Sizing; the Dynamic arm enables the paired-cap configuration established by commit `625cb21`.

## Causal event fan-out

`MarketEvent` is recursively immutable and has a content-derived event ID, positive sequence, and timezone-aware timestamp. One exact event object is sent to all nine Shadows in registry order. Duplicate event IDs, sequence gaps/replays, and non-increasing timestamps fail closed. Recovery/resume authority is represented in state but V1 provides no mechanism that authorizes bypassing these checks.

Dispatch is transactional. The engine deep-copies all states, processes every Shadow, and commits the complete state set only if every handler succeeds. One Shadow failure therefore cannot leave the matrix partially advanced.

The V1 default handler only acknowledges an event and records `strategy_decision: null`. It deliberately does not invoke Candidate V1, Dynamic Sizing, or any trading implementation. Later execution adapters must be separately designed and tested against the same causal boundary.

## Audit records and position retention

Each per-Shadow event record includes event ID/sequence/timestamp, Shadow ID and configuration fingerprint, before/after state hashes, accelerator identities, status/result payload, and its own deterministic record ID.

`PositionEntrySnapshot` stores the complete frozen Shadow configuration that governed entry, plus entry event and optional accelerator-decision identity. Later registry revisions cannot rewrite that snapshot or the assumptions of an existing position.

## Explicit non-goals

V1 does not implement strategy decisions, order generation, pyramiding, Champion selection, automatic promotion, broker connectivity, network access, credentials, or live capital authority. Candidate V1, fixed-25 qualification behavior, Dynamic Sizing V1 tiers, causal accounting, and provenance protections remain untouched.
