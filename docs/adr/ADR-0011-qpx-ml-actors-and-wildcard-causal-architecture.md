# ADR-0011: QPX ML Actors and Wildcard Causal Architecture

**Status:** Accepted

**Date:** 2026-09-04

---

## Context

QPX requires an ML architecture that permits autonomous experimentation without weakening causal integrity, accounting, operational safety, or human governance. Repository recovery material establishes separate Research, Qualification, and Operations ML roles; a permanent paper-only Wildcard; one-way clean-room discovery; and a prohibition on ML self-promotion or real-capital authority. ADR-0010 separately establishes forward-only, event-driven causality and requires deterministic ordering when events share a timestamp.

The ten-year whole-market 15-minute historical reservoir is still being acquired. It is not yet eligible for production apprenticeship, and this ADR neither starts training nor declares the reservoir eligible.

This ADR freezes actor boundaries, information flow, episode semantics, causal persistent-memory rules, evidence states, and governance. It deliberately does not select a model, reward, account parameters, or trading permissions.

---

## Provenance Classification

### Recovered and repository-supported decisions

- Wildcard is clean-room discovery: teach it how to discover, not QPX trading doctrine.
- Wildcard information flow is one-way: raw causal market to Wildcard to sterile factual experience to downstream QPX.
- Champion, Shadow, Research, Qualification, and Operations conclusions do not flow back into Wildcard.
- Wildcard is paper-only, causal, logged, auditable, credential-free, without live-order, real-money, promotion, or self-promotion authority.
- Research ML generates hypotheses and assists research but has no promotion or real-money authority.
- Qualification ML independently evaluates evidence; the researcher does not grade its own work.
- Operations ML observes operational behavior and is not recovered as an autonomous learned trader.
- ML failure means loss of intelligence, not loss of deterministic QPX safety or correctness.
- Research discoveries follow normal freeze/reproduce, evidence, qualification, Challenger, and governance paths.
- Core owns authority; workers own horsepower. Physical co-location cannot collapse process, data, or authority boundaries.
- Candidate V1, frozen Top-100 artifacts, strict-causal accounting, permanent controls, and existing qualified evidence remain protected.

### Newly specified and approved decisions

- Wildcard is an autonomous experimental learner with its own isolated simulated bankroll and ledger for every episode.
- Wildcard may perform repeated historical apprenticeship episodes. There is no rewind inside an episode; bankruptcy may start a new isolated episode at the earliest causally eligible point.
- All cross-episode learning, including model parameters, is governed by the complete causal decision boundary rather than by timestamp alone.
- Raw prior-episode archives are physically inaccessible to the model-facing Wildcard runtime.
- Research ML is downstream and QPX-aware through an explicit allowlist.
- A future independent learned paper trader is distinct from Wildcard, Research ML, Operations ML, Qualification ML, and governed QPX.
- Market state and transition structure may be learned without prescribed regime labels or a human strategy menu.
- QPX-versus-ML comparison is external and cannot feed QPX scores back into the learned trader during an evaluated interval.
- Repeated historical episodes are apprenticeship, not independent out-of-sample or live-forward evidence.

### Reconciliation of the earlier no-rewind wording

Earlier recovery material says Wildcard experiences market history once, without rewind, and may remember the past but never relive it. The newly approved episode design supersedes that statement only at the multi-episode level:

- Within an episode, chronology is strictly forward-only and cannot rewind.
- Between episodes, bankruptcy or historical completion may cause an isolated restart at the earliest causally eligible point.
- Cross-episode knowledge remains locked until its complete evidence boundary is eligible again.

This is not permission to replay future knowledge into an earlier decision.

---

## Decision

### 1. Actor boundaries

#### Wildcard ML

Wildcard is a sterile autonomous experimental learner. It observes a causally bounded market world, chooses its own simulated actions, experiences realistic economic consequences in an isolated episode account, learns subject to the causal memory wall, and emits sterile factual reports.

Wildcard may receive:

- market observations available before its current decision boundary;
- neutral point-in-time security metadata available before that boundary;
- its own current-episode bankroll, ledger, positions, orders, prior actions, and execution outcomes;
- its own current-episode working memory; and
- durable learning artifacts proven eligible at the current complete causal boundary.

Wildcard may not receive:

- QPX strategy names or mechanics, Candidate V1, PR50, QPX entry/exit terminology, pyramiding terminology, or capacity-arbitration doctrine;
- Champion, Shadow, Research, Qualification, Operations, promotion, or human strategy-quality conclusions;
- QPX decisions, scores, labels, or comparison results;
- future observations or later information at the same timestamp;
- broker credentials, real-money access, or live-order authority; or
- any read/list/search/retrieval path to raw prior-episode archives.

Wildcard receives a world and a causally legal action interface, not a coded strategy menu.

#### Research ML

Research ML is a downstream QPX-aware hypothesis and experiment actor. It may consume schema-validated sterile Wildcard reports and discoveries plus explicitly allowlisted QPX mechanics, Shadow evidence, governed behavior, and historical research evidence. It emits versioned hypothesis and experiment manifests with claims, evidence, causal boundaries, controls, falsification criteria, and provenance.

Research ML cannot trade, mutate governed QPX, qualify its own work, promote a candidate, access broker credentials, or control capital. Its exact QPX input allowlist remains unresolved.

#### Independent learned paper trader

A future autonomous learned trading actor will operate a completely isolated persistent paper account. Its permanent name is unresolved. It is not Operations ML merely because that recovered name exists.

The trader may consume causal market reality, its own account history, neutral security and corporate-action facts, and explicitly admitted causally legal Wildcard discoveries. It may learn market state, transition probabilities, and its own trading policy. It receives no strategy menu and is not restricted to Candidate V1, momentum, mean reversion, fixed allocation buckets, or predefined regime strategies.

Its constraints represent environmental and accounting physics only: causality, valid cash and liabilities, valid instruments and actions, realistic execution, no fabricated fills, deterministic evidence, no real-broker authority, and no mutation of governed QPX.

During an evaluated interval it cannot consume QPX actions, QPX scores, or comparator results.

#### Operations ML

Operations ML retains its recovered role as an operational observer of slippage, fills, broker/feed degradation, liquidity, paper/live divergence, and anomalies. It is not the independent learned paper trader. Any future merger or authority expansion requires a separate decision.

#### Qualification ML

Qualification ML is an independent evidence evaluator. It assesses causal validity, robustness, overfitting, stability, reproducibility, regime dependence, similarity/correlation, degradation, execution realism, and evidence gaps. It may reject evidence, request more evidence, or nominate a candidate for governed consideration.

Qualification ML does not replace Wildcard discovery, grade its own research, trade, promote automatically, or possess capital authority.

#### External comparator

The comparator aligns governed QPX and the independent learned paper trader against the same causal market reality and declared execution assumptions. It evaluates return, equity path, drawdown, survival, volatility, turnover, concentration, liquidity usage, time underwater, tail losses, transition timing, false and late transitions, correct non-transitions, action divergence, data quality, and reconciliation behavior.

Comparator output is external to both trading actors during the evaluated interval. No comparison result grants capital authority.

### 2. Complete causal decision boundary

A causal decision boundary is an ordered tuple containing at minimum:

1. event or effective time;
2. information-availability time;
3. deterministic within-event sequence/order; and
4. the exact pre-action decision boundary at which Wildcard acts.

Timestamp comparison alone is insufficient. Same event time, same availability time, or the same nominal bar does not imply availability when deterministic order places evidence at or after the action boundary.

A prior-episode parameter delta, optimizer state, embedding, replay-derived representation, feature cache, summary, rule, hidden state, or other artifact is visible only when every evidence item used to derive it is strictly before the current decision boundary under the complete ordering. Evidence at the current action boundary is not eligible until the ordering proves it became available before the action.

Every durable learning artifact must declare its maximum evidence boundary and a strictly later eligibility boundary. Eligibility evaluation must fail closed on missing, incomparable, ambiguous, or corrupt boundary data.

### 3. Wildcard episode lifecycle

Each episode:

1. receives a unique episode, account, ledger, model-lineage, configuration, and random-seed identity;
2. starts at the earliest causally eligible market boundary with a fresh isolated bankroll and no inherited episode state;
3. advances only in deterministic causal order;
4. observes, acts, receives realistic execution/accounting consequences, and learns;
5. may emit periodic sterile check-ins at a future configured cadence;
6. terminates on bankruptcy or historical completion;
7. writes complete audit evidence outside the Wildcard-readable namespace;
8. persists only learning artifacts governed by the causal memory wall;
9. destroys episode memory; and
10. may begin another isolated episode at the earliest historical point.

Bankroll rescue, backward seek inside an episode, fabricated execution, hidden external contributions, and inheritance of positions or liabilities are forbidden.

### 4. Consequence of the brick wall

When a new episode restarts at the earliest historical point, discoveries learned later in a prior episode remain locked until their complete evidence boundaries become causally eligible again.

Wildcard may therefore encounter a previously experienced failure again before the prior lesson becomes eligible. This is an unavoidable and intended consequence of causal isolation. It must not be “fixed” by exposing the lesson, weights, summaries, bankruptcy explanation, exact event, or any derived representation early.

Reproducibly seeded exploration may lead the new episode to behave differently without prior knowledge. Random variation is not evidence leakage and provides no guarantee that the earlier failure will be avoided.

### 5. Memory classes

#### Episode memory

Episode memory includes current observations, account state, temporary hypotheses, recurrent/hidden state, mutable caches, current optimizer state, and other working state. It exists only inside the current episode namespace and is destroyed on restart after its audit boundary is sealed.

#### Durable discovery and learning state

Durable learning may survive only as immutable, provenance-bound, integrity-checked artifacts carrying complete evidence and eligibility boundaries. This applies equally to model weights, parameter deltas, adapters, optimizer state, embeddings, indexes, summaries, and learned rules.

A mutable unversioned “latest model,” global replay buffer, global feature cache, or timestamp-only eligibility test is prohibited.

### 6. Model-parameter enforcement

The preferred architecture is an immutable base model plus immutable causal learning capsules. Each capsule contains:

- its complete maximum evidence boundary and strictly later eligibility boundary;
- parent model and capsule fingerprints;
- parameter or adapter delta and its deterministic composition order;
- optimizer-state inclusion or explicit destruction record;
- data/event-range, algorithm, configuration, code, and environment fingerprints; and
- content checksum and provenance signature.

At a decision boundary, a dedicated loader composes only capsules proven eligible under the complete causal ordering. The loader exposes no raw archive and rejects ambiguous lineage or ordering.

If the selected model cannot support deterministic capsule composition without causal leakage, the required safe fallback is to reset all model-facing learned state between episodes. Discoveries may still be retained for humans and downstream Research ML, but not reused by Wildcard. Cross-episode performance improvement is subordinate to causal correctness.

The exact model family, capsule cadence, delta representation, optimizer treatment, and composition algorithm remain unresolved and require a later reviewed design.

### 7. Raw episode archive boundary

Raw episode evidence is retained for human audit and downstream governed research through a separate archive writer. The model-facing Wildcard process must have no filesystem mount, database credential, object-list permission, search endpoint, retrieval tool, or indirect service capable of reading the archive.

The runtime may hold a write-only archive capability. The archive reader and downstream report processor use separate identities and interfaces. Hiding a path by convention is not isolation.

### 8. Account and bankruptcy boundary

Every episode has a fresh reconciled simulated account. It must record cash, positions, liabilities, orders, executions, rejected actions, realized and unrealized results, fees, distributions, corporate actions, and deterministic account transitions as applicable.

The exact starting bankroll, bankruptcy definition, leverage permission, short permission, options permission, fee/slippage model, instrument universe, and action encoding are unresolved. This ADR does not supply defaults.

On bankruptcy, the episode ends without rescue capital. Audit evidence is sealed outside Wildcard access, causally controlled durable learning is preserved, episode memory is cleared, and a later episode may restart from the earliest boundary.

### 9. Reports

Wildcard emits sterile schema-validated reports containing neutral factual evidence such as episode identity, causal range reached, actions, exposures, execution results, equity path, drawdown, turnover, concentration, survival duration, bankruptcy facts, data gaps, artifact identities, and evidence boundaries.

Reports must not inject QPX doctrine or human labels describing a good strategy. Exact check-in cadence and final report schema remain unresolved.

### 10. Regime and transition learning

No predefined BULL, BEAR, or SIDEWAYS labels are required. An actor may infer latent market state, predict transitions, and adapt policy using only causally available inputs. Future outcomes may become learning targets only after their complete information-availability and event-order boundaries have passed.

Potential market dimensions are research choices rather than mandatory features. Feature sets and state representations remain unresolved.

### 11. Evidence states

- `DEVELOPMENT_ONLY`: synthetic, mocked, or deliberately small partial data used only for engineering validation. It produces no research conclusion.
- `ACQUISITION_PARTIAL_NOT_TRAINING_ELIGIBLE`: incomplete reservoir state. Real apprenticeship is forbidden.
- `TRAINING_ELIGIBLE`: an independent gate has verified dataset completeness, integrity, survivorship treatment, security identity, corporate actions, calendars, missingness, and provenance.
- `HISTORICAL_APPRENTICESHIP`: causal chronological learning, including repeated episodes. It is not independent forward evidence.
- `FORWARD_CANDIDATE_FROZEN`: model, learning state, data contract, configuration, and provenance frozen before forward observation.
- `FORWARD_EVIDENCE`: evidence produced after the freeze on genuinely unseen future/live data.
- `QUALIFICATION_EVIDENCE`: independently evaluated evidence; it still grants no automatic promotion or capital authority.

Acquisition completion alone does not automatically prove training eligibility.

### 12. Fingerprints and recovery

Every episode and evidence package binds fingerprints for the dataset manifest, security master, universe policy, calendar, corporate actions, event schema and ordering, feature contract, execution/accounting model, model architecture, base weights, capsule lineage, training algorithm, configuration, action space, safety constraints, random state, account ledger, code revision, environment, report schema, and governance configuration.

Crash recovery restores the last atomic causal boundary, validates capsule eligibility and lineage, reconciles the account, and replays only the uncommitted causal suffix. Corruption, missing provenance, future-dated learning, ambiguous ordering, or account mismatch fails closed. Recovery cannot fabricate an action, fill, finalization, or later causal clock.

### 13. Resource and authority scheduling

Clean-V2 remains authoritative. Historical acquisition and all ML work remain subordinate. Apprenticeship must be resumable and may yield any amount of throughput to protect governed forward work. Workers may provide compute but cannot own authoritative state or capital decisions.

Exact CPU, GPU, memory, provider, worker, and scheduling quotas remain configurable or unresolved.

### 14. Smallest safe implementation order

1. Freeze this ADR without executable behavior.
2. Define neutral causal boundary, event, security-master, corporate-action, and universe contracts.
3. Define dataset and evidence eligibility manifests.
4. Build and verify isolated accounting/execution physics without an ML policy.
5. Build OS/process archive isolation and write-only evidence transport.
6. Select a model-compatible causal capsule design in a separate high-risk review.
7. Prove capsule eligibility and same-timestamp ordering using toy state only.
8. Build deterministic episode/checkpoint/restart infrastructure.
9. Exercise only `DEVELOPMENT_ONLY` fixtures.
10. Define sterile report and contamination-rejection contracts.
11. Select reward, bankruptcy, bankroll, permissions, and cadence through explicit governance.
12. Begin real apprenticeship only after an independent `TRAINING_ELIGIBLE` decision.
13. Add Research ML, the independent learned paper trader, external comparison, and Qualification ML as separately reviewed milestones.

---

## Information Flow

```text
Canonical causal market/event stream
               |
       +-------+----------------------+
       |                              |
       v                              v
Sterile Wildcard              Independent learned trader
isolated episode              isolated paper account
       |                              |
       | sterile reports              | action/account evidence
       v                              v
Research ML                    External comparator <--- Governed QPX
       |
       | frozen hypotheses and experiment evidence
       v
Boundary / historical / Shadow research
       |
       v
Qualification ML
       |
       | recommendation only
       v
Candidate Qualification -> Challenger review -> human governance
```

There is no reverse path into Wildcard and no automatic path to capital authority.

---

## Explicit Unknowns

The following remain `UNKNOWN`, unresolved, or intentionally configurable:

- Wildcard model family, learning algorithm, reward definition, and reward weights;
- bankruptcy definition and threshold;
- starting bankroll and account parameters;
- leverage, short, options, instrument, and order-type permissions;
- periodic check-in cadence;
- execution, fee, slippage, and liquidity model;
- action encoding and feature set;
- capsule cadence, parameter-delta representation, deterministic composition algorithm, and optimizer persistence;
- Wildcard resource limits and sibling count;
- Research ML QPX information allowlist;
- independent learned paper trader's permanent name;
- whether that trader will ever relate to Operations ML beyond evidence flow;
- Qualification scoring and thresholds;
- historical universe and reconstitution policy;
- whether completed reservoir survivorship and historical-symbol evidence will satisfy `TRAINING_ELIGIBLE`;
- development subset definition;
- forward-freeze duration and acceptance criteria;
- worker placement and resource quotas;
- data and raw-archive retention policy; and
- exact promotion-gate ordering where prior governance permits refinement.

No implementation may manufacture defaults for these decisions.

---

## Consequences

- Causal eligibility is stricter than timestamp comparison and applies to every learned representation.
- Repeated episodes may repeat old failures because later prior-episode lessons remain locked until causally eligible.
- Wildcard autonomy is real within its simulated environment but cannot cross information, archive, promotion, or capital boundaries.
- Research, trading, operational observation, qualification, and comparison remain separate responsibilities.
- Historical apprenticeship cannot be presented as unseen forward validation.
- Some model families may be rejected if they cannot provide deterministic, auditable causal-state composition.

---

## Non-Authorization and Preservation Boundary

This ADR authorizes no executable ML implementation, training, replay, research conclusion, paper-trader deployment, service change, acquisition change, Shadow treatment, promotion, broker integration, or capital action.

Historical acquisition, Clean-V2, DUMMY and broker state, runtime state, Shadow Matrix enablement, Candidate V1, frozen Top-100 data and fingerprints, strict-causal accounting, permanent controls, and existing evidence remain untouched.

---

## References

- `AGENTS.md`
- `QPX_RECOVERY_DECISION_LEDGER.md`
- `QPX_RECOVERY_PROMPT.md`
- `QPX_CONVERSATION_JOURNAL_2026-08-14.md`
- `QPX_POST_AUG14_CONTINUITY_CHECKPOINT_2026-08-17.md`
- `docs/adr/ADR-0010-forward-only-event-driven-causal-architecture.md`
- `docs/SHADOW_MATRIX_ENGINE_V1_2026-08-12.md`
