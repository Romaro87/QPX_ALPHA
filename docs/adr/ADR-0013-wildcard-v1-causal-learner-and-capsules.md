# ADR-0013: Wildcard V1 Causal Learner and Learning Capsules

**Status:** Accepted for `DEVELOPMENT_ONLY` implementation

**Date:** 2026-09-12

## Scope and authority

This is the separate high-risk model-family review required by ADR-0011. It
selects the causal container for Wildcard V1 and authorizes toy engineering
fixtures only. It does not authorize historical apprenticeship, training on the
reservoir, research conclusions, promotion, broker/live use, or capital.

The strict reservoir state remains
`ACQUISITION_COMPLETE_NOT_TRAINING_ELIGIBLE`. Only an independent
`TRAINING_ELIGIBLE` decision followed by separately authorized transition may
create `HISTORICAL_APPRENTICESHIP`.

## Model-family review

| Family | Finding |
| --- | --- |
| Online linear/logistic | Most auditable and cheapest, but lacks learned nonlinear sequential state. Retained as the completed engineering baseline, not selected for Wildcard. |
| Small feed-forward network | Nonlinear and simple, but sequence memory would move into hand-engineered state or an external history cache. Runner-up. |
| Small LSTM | Sequentially capable but has more gates, parameters, state, and capsule/restart surface than V1 requires. Rejected in favor of GRU. |
| Small GRU | Smallest conventional recurrent family that learns bounded sequential state while keeping episode memory, parameter state, and deterministic composition explicit. Selected. |
| Larger attention/replay models | Unnecessary compute and a larger archive/replay isolation surface. Rejected for V1. |

Wildcard V1 selects a small GRU policy with a softmax action head. The
`DEVELOPMENT_ONLY` proof uses deterministic categorical sampling and one-step
truncated online reward-modulated policy-gradient SGD. It has no replay buffer,
momentum, mutable global optimizer, or raw-history input. Architecture sizes,
the real neutral action-token/quantity encoding, and resource configuration for
apprenticeship remain part of a later authorized experiment configuration; toy
values are not operational defaults.

## Causal state and preference contract

The model receives only:

1. a fixed-length neutral causal state vector produced from events already
   delivered by the one-event gateway;
2. a fixed-length approved reward/preference vector;
3. episode-local recurrent hidden state; and
4. causally eligible immutable capsules.

State, preference, and neutral action vocabulary each have independent
fingerprints. The learner has no archive path or archive navigation capability.
Feature construction is incremental outside the model from delivered causal
data only. QPX rankings, strategy labels, Candidate V1 doctrine, comparator
results, and downstream Research/Qualification conclusions are prohibited.

The preference vector is model conditioning, not a source-code constant.
Changing reward values creates a new reward-policy and effective-experiment
identity. A change that preserves the exact preference schema and architecture
may continue only on a separately declared compatible lineage; a schema,
dimension, world-physics, or architecture change requires a new base/lineage.
No claim is made that objective changes require zero adaptation.

## Action and learning order

For each completed world boundary:

1. causal events are delivered in established order;
2. a pre-action state containing only available evidence is formed;
3. the learner selects one neutral action token;
4. the existing world owns order/execution/account consequences;
5. later causal events produce fills and consequences;
6. `BOUNDARY_COMPLETE` reconciles scheduled time, equity, and reward once;
7. only then may the learner update from that action and reward; and
8. an episode-terminal capsule records the update's maximum evidence boundary
   and a strictly later eligibility boundary.

The implementation rejects reward evidence that is not strictly after its
action boundary and rejects a new action at or before learned evidence. It does
not define the eventual economic quantity decoder; the toy skeleton operates on
a fingerprinted neutral token vocabulary and does not call the real world.

## Episode memory and optimizer

Recurrent hidden state, a pending action transition, causal feature cache,
working parameters, SGD working values, and RNG state are episode-local.
Legitimate episode restart destroys hidden/pending memory. Plain SGD has no
momentum or adaptive persistent state, so every capsule records:

`DESTROYED / PLAIN_SGD_HAS_NO_PERSISTENT_STATE`

No raw episode history or replay buffer survives. Learned parameters survive
only by transformation into an immutable capsule.

## Immutable capsule contract

V1 capsules are sealed at a legitimate episode terminal boundary. Each is a
single-parent additive parameter delta and binds:

- capsule identity and checksum;
- immutable base model fingerprint;
- parent capsule and parent composed-model fingerprints;
- composition sequence and resulting model fingerprint;
- maximum evidence and strictly later eligibility boundaries;
- episode and effective experiment identities;
- world and reward-policy fingerprints;
- state/feature, preference, action-space, algorithm/config, and architecture
  fingerprints;
- complete parameter delta;
- optimizer destruction record;
- deterministic composition rule;
- RNG seed and state at seal;
- code revision and environment fingerprint; and
- explicit zero promotion/live/broker/capital authority.

The loader starts from the immutable base, follows exactly one declared parent
chain in ascending sequence, validates each parent/result fingerprint, and adds
each delta in fixed parameter/index order. A capsule is loadable only when its
maximum evidence precedes its eligibility boundary and its eligibility boundary
is strictly before the current action boundary. Missing, corrupt, forked,
ambiguous, same-boundary, or future lineage fails closed.

## Restart and world boundary

The learner checkpoint atomically binds architecture/config, base and capsule
lineage, episode/experiment/world/reward identities, current parameters,
initial composed parameters, hidden state, pending transition, last learned
evidence boundary, and RNG state. Recovery restores the last committed learner
boundary and cannot synthesize an action or update. The existing Wildcard world
continues to own account, order, fill, clock, reward, and audit state; this ADR
does not alter it.

## Resource estimate

For input width `I`, hidden width `H`, and action count `A`, parameters are
`3(HI + H² + H) + AH + A`, with `O(H(I+H+A))` work per causal action and
`O(H + parameters)` resident model state. A modest V1 configuration is expected
to remain well below one million parameters and fit comfortably on CPU. Exact
apprenticeship sizes and quotas are not selected by toy fixtures.

## Verification and apprenticeship boundary

Focused toy verification must prove deterministic initialization and action,
strict action/reward ordering, episode-memory destruction, capsule boundaries,
deterministic composition, corrupt/ambiguous-lineage rejection, checkpoint
equivalence, preference plumbing, absence of an archive API, and zero authority.

Authority states remain:

- `DEVELOPMENT_ONLY`: toy/synthetic mechanics only; no research conclusion.
- `ACQUISITION_COMPLETE_NOT_TRAINING_ELIGIBLE`: no Wildcard apprenticeship.
- `TRAINING_ELIGIBLE`: independently granted dataset evidence state.
- `HISTORICAL_APPRENTICESHIP`: only a separately authorized transition after
  `TRAINING_ELIGIBLE`, binding the complete dataset, world, reward, model,
  capsule, feature, action, RNG, code, environment, and governance identity.

No learner implementation or passing toy test grants apprenticeship, forward
evidence, qualification, promotion, broker, live, or capital authority.
