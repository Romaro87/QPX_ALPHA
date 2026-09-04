# ADR-0012: Wildcard Experimental World and Reward Contract

**Status:** Accepted

**Date:** 2026-09-04

---

## Context

ADR-0011 freezes Wildcard's actor boundary, strategy sterility, complete causal
decision boundary, cross-episode causal memory wall, raw-archive isolation, and
lack of real-capital authority. This ADR does not reopen those decisions. It
freezes the physical, accounting, execution, and reward world in which the first
Wildcard implementation may later operate.

The purpose of this world is to let Wildcard discover behavior rather than choose
from human-authored strategies. Environmental constraints encode causal reality,
accounting validity, and implementable market physics. They do not encode QPX
entry, exit, allocation, position-count, diversification, concentration,
momentum, regime, or other strategy doctrine.

The ten-year whole-market 15-minute reservoir remains incomplete. This ADR does
not make it `TRAINING_ELIGIBLE`, start apprenticeship, authorize executable ML,
or change any running system.

---

## Relationship to ADR-0011

The following ADR-0011 rules remain permanent and authoritative:

- Wildcard is a sterile autonomous experimental learner, separate from Research
  ML, the future independent learned paper trader, Operations ML, Qualification
  ML, governed QPX, and the external comparator.
- Wildcard receives a causal world and an action interface, not QPX doctrine or
  a strategy menu.
- Every observation and learning artifact is governed by the complete causal
  decision boundary: event/effective time, information-availability time,
  deterministic within-event order, and the exact pre-action boundary.
- A durable artifact is eligible only when **all** evidence used to derive it was
  available strictly before the current decision boundary. Timestamp equality
  alone never proves eligibility.
- Raw prior-episode archives have no model-facing read path.
- A later prior-episode discovery remains locked after restart until its complete
  evidence boundary becomes eligible again. Wildcard may therefore encounter a
  previously experienced failure again; future knowledge must not be leaked
  backward to prevent it.
- Wildcard has no broker credentials, real-order authority, promotion authority,
  or real-capital authority.

Where ADR-0011 left the bankroll, permissions, execution model, reward,
bankruptcy, and check-in cadence unresolved, this ADR supplies the approved V1
contract. It also adds `ECONOMIC_DEAD_END` as a distinct solvent terminal class;
this supplements ADR-0011's terminal-state enumeration without weakening its
bankruptcy or causal-memory rules.

---

## Decision Classification

### Permanent causal and sterility rules

The ADR-0011 rules listed above are not V1 conveniences. They survive future
changes to instruments, actions, execution physics, reward, or models.

### Physical and accounting world rules

The bankroll, valid account states, point-in-time instruments, causal order
handling, execution convention, liquidity, costs, corporate actions, stale-value
treatment, and terminal economic conditions describe the simulated world's
physics. They are not recommendations about how Wildcard should trade.

### Reward and consequence rules

Wildcard receives economic consequences through causally reconciled equity,
with a bounded early-compounding incentive and a lexicographic terminal solvency
classification. Behavioral proxies are recorded as evidence but are not directly
rewarded or penalized.

### V1 implementation boundaries

V1 is a cash-only, long-only, no-margin, no-short, no-options world using DAY
market orders. This is an implementation world boundary, **not** a claim that
Wildcard should never discover those behaviors. Any later expansion requires a
new, fingerprinted world contract with the additional causal and accounting
physics proven first.

---

## 1. Episode Account and Bankroll

Every Wildcard historical episode receives a new isolated simulated account with
exactly **$100,000 USD** of starting settled cash.

Comparable episodes must have:

- the same $100,000 starting economic world;
- no inherited positions, orders, liabilities, cash, or entitlements;
- no rescue deposits or capital injections;
- no connection to QPX, Clean-V2, existing DUMMY state, broker accounts, or
  broker capital; and
- a complete deterministically reconciled ledger visible to Wildcard only at the
  current causal boundary.

The bankroll is experimental normalization, not a position-sizing instruction.
It must be included in the experiment-world fingerprint and may become a
controlled experimental dimension only under a new experiment identity.

Authoritative share, price, cash, fee, liability, and ledger arithmetic uses
deterministic decimal arithmetic, not binary floating point. External cash
settlement boundaries reconcile exactly to cents; internal calculations may use
higher versioned decimal precision.

---

## 2. Point-in-Time V1 Instrument World

An instrument is eligible at a decision boundary only if it is a US-listed cash
common equity or ETF and all of the following are causally valid at that boundary:

- stable security identity and point-in-time security-master state;
- historical-data eligibility;
- instrument-class support; and
- supportable corporate-action treatment.

A symbol string alone never establishes eligibility. Leveraged and inverse ETFs
are not strategy-prohibited; they may exist when they pass the same identity,
data, lifecycle, and instrument gates.

Options, warrants, rights, and other contracts whose economic lifecycle is not
implemented are outside V1. Unknown or invalid instrument physics causes a
rejection or an integrity/reconciliation state, never fabricated tradability.

Fractional execution is permitted in V1 only after its implementation proves the
applicable instrument/provider semantics:

- quantity precision: **0.001 share**;
- minimum submitted economic notional: **$1.00**; and
- unsupported fractional tradability for a specific security causes action
  rejection, not a fabricated fractional fill.

The minimum prevents economically meaningless dust orders. It does not prescribe
sizing.

---

## 3. V1 Action Contract

Wildcard may submit these neutral actions:

- `NO_ACTION`;
- `BUY`, including a partial quantity;
- `SELL` from an owned position, including a partial quantity;
- `CANCEL` a pending order;
- `REPLACE` a pending order;
- hold cash; and
- hold positions.

V1 accepts market orders with `DAY` time in force only. Pending orders expire at
the end of the regular trading session unless cancelled, replaced, or filled
earlier. A V1 market order is never carried across sessions.

Adding, reducing, concentrating, and diversifying are possible consequences of
quantities Wildcard chooses. They are not named strategy actions. The interface
must not encode position count, allocation, diversification, concentration,
entry, exit, momentum, mean reversion, regime, Candidate V1, PR50, Shadow, or any
other human strategy doctrine.

---

## 4. Causal Market-Order Execution

A decision made from completed information at boundary `T` cannot fill from the
observation or bar used to make that decision. Its earliest eligible execution
event is the **open of the next causally eligible regular-session 15-minute bar
or event for that security**. The simulator must advance to that event before
the price becomes available.

If the required next event is missing, stale, non-tradable, or invalid:

- no other price may be substituted;
- the order remains unresolved and pending, subject to its explicit DAY expiry;
  and
- the missing or invalid execution opportunity is recorded.

Current-bar-close fills, future closes presented as known information, hindsight
price selection, and fabricated fills are prohibited.

At an eligible fill event, the maximum filled quantity is **1% of causally
observed eligible bar volume**, additionally bounded by settled available cash,
owned quantity, valid fractional semantics, and account physics. If requested
quantity exceeds the permitted fill, the simulator records the exact partial
fill and retains only the valid unfilled DAY remainder. It never fabricates
liquidity.

---

## 5. Friction and Cost Model

V1 freezes this deterministic neutral friction model:

- commission: **$0** for supported cash equities;
- adverse simulated execution slippage: **5 basis points per filled notional**;
- regulatory and statutory transaction fees: included only when they are
  deterministically modelable from causal account facts under an explicitly
  versioned rule; and
- liquidity/market impact: represented initially by the 1% volume-participation
  cap, with no additional speculative impact formula.

The reservoir does not contain authoritative historical bid/ask observations,
so the simulator must not fabricate historical spreads. The 5-basis-point value
is fingerprinted simulated physics, not observed spread data.

---

## 6. Economic State and Reconciliation

The reconciled account distinguishes at minimum:

- settled cash;
- causally realizable asset value;
- explicitly stale or non-realizable carrying value; and
- due liabilities.

A stale last-known mark may be retained for audit and reporting only when marked
`STALE`. It cannot silently become realizable value or purchasing power and
cannot fund new purchases.

When authoritative causal disposition information exists for a delisting,
reorganization, identity change, distribution, or other lifecycle event, the
world processes it exactly. If the economic disposition of a held security
cannot be causally established, the world must not invent a sale, zero value,
cash realization, or continued realizability. It enters
`ACCOUNT_RECONCILIATION_BLOCKED` (or a more specific integrity state), preserves
the episode, and awaits governed recovery.

Missing evidence, corrupt state, an unresolved lifecycle, and a process crash
are not bankruptcy.

---

## 7. Bankruptcy and Other Episode Outcomes

After mandatory reconciliation, V1 declares `FAILED_BANKRUPTCY` only when:

1. causally reconciled account equity is less than or equal to zero; or
2. due liabilities exceed settled cash plus causally realizable account value
   and cannot be satisfied under the world contract; or
3. the account is economically insolvent and cannot be reconciled into a valid
   simulated account.

In cash-only long V1, the second and third conditions should ordinarily be
impossible unless a real economic obligation exists. Drawdown, poor performance,
benchmark lag, inactivity, stale or missing data, process failure, corrupt state,
or missing corporate-action evidence are not bankruptcy. A solvent account that
performs badly remains solvent; there is no invented drawdown-bankruptcy
threshold and no rescue capital.

`ECONOMIC_DEAD_END` is a separate non-bankruptcy terminal class. It requires
objective proof that positive economic value remains and the account is solvent,
but the validated world contract permanently offers no physically valid path to
transact, liquidate, or resolve the remaining economic state. Temporary
illiquidity, ordinary cash, poor opportunity, inactivity, a missing bar,
uncertainty, or unresolved integrity evidence cannot establish permanence.

`ACCOUNT_RECONCILIATION_BLOCKED` and integrity blocks preserve state for governed
recovery and are not terminal economic judgments.

`HISTORICAL_COMPLETE` occurs when a solvent Wildcard reaches the end of the
entire eligible historical chronology.

Each legitimate terminal outcome produces and seals a sterile terminal report.
For `FAILED_BANKRUPTCY`, `ECONOMIC_DEAD_END`, or `HISTORICAL_COMPLETE`, the raw
episode archive is sealed behind ADR-0011's causal brick wall, only causally
governed learning artifacts may persist, current episode memory/account state is
destroyed, a fresh isolated $100,000 account is created, and the next
apprenticeship episode restarts at the earliest eligible historical boundary.
No later discovery becomes prematurely visible after that restart.

---

## 8. Periodic Sterile Check-Ins

A surviving episode emits a check-in every **8,190 scheduled regular-session
trading minutes**, approximately 21 normal US-equity sessions. Terminal and
integrity events report immediately.

The cadence uses the authoritative point-in-time exchange calendar, never CPU
time or wall-clock replay duration. Viewing a report must create no input or
feedback path into Wildcard.

A check-in may report factual, sterile evidence including:

- episode/world/model/learning-lineage identity and causal boundary;
- current settled cash, realizable value, stale carrying value, liabilities,
  equity, survival duration, growth, and drawdown;
- exposure, concentration, turnover, account utilization, and inactivity;
- actions, rejected or impossible actions, pending orders, fills, partial fills,
  fees, and execution costs;
- behavior changes and factual recurring patterns without strategy labels;
- data, security-identity, corporate-action, reconciliation, or integrity
  problems; and
- applicable artifact and provenance fingerprints.

Reports must not contain QPX terminology, strategy labels, human judgments,
advice to Wildcard, or conclusions fed back from Research or Qualification ML.

---

## 9. Causal Market Time

Reward and reporting time is cumulative **scheduled regular-session trading
minutes** from the authoritative point-in-time exchange calendar.

- Weekends and market holidays add zero.
- Half-days add their actual scheduled minutes.
- Missing observations do not stop scheduled causal market time.
- Replay and hardware speed have no effect.

This definition makes identical causal replays economically comparable without
rewarding compute speed or distorting time around closures.

---

## 10. Dense Economic Reward

For consecutive causally reconciled positive equities, dense economic growth is:

```text
DeltaLogEquity_t = log(E_t / E_(t-1))
```

The causal-time speed weight is:

```text
w(tau) = 1 + exp(-ln(2) * tau / H)
H = 24,570 scheduled regular-session trading minutes
```

The dense reward is unambiguously:

```text
r_t = w(tau_t) * DeltaLogEquity_t
```

At episode start the weight is approximately 2.0, after one half-life it is 1.5,
after two half-lives it is 1.25, and over long periods it approaches 1.0 rather
than zero. Thus all economic growth continues to matter while earlier equal
growth receives an additional incentive. Early losses are also correspondingly
consequential.

Dense log reward is evaluated only while reconciled equity is positive.
Bankruptcy handling is terminal and must never evaluate `log(0)` or a logarithm
of negative equity.

The reward includes no direct bonus or penalty for trade count, turnover,
position count, concentration, leverage usage, percent invested, entries,
exits, cash holdings, or other behavioral proxies. Trading sooner or taking more
risk earns nothing unless it produces causally reconciled economic growth.

---

## 11. Terminal Evaluation

Solvency is strictly lexicographic. Every `FAILED_BANKRUPTCY` episode ranks below
every solvent `HISTORICAL_COMPLETE` episode for terminal-success classification,
regardless of temporary gains or accumulated dense reward. Dense reward cannot
erase bankruptcy.

For solvent completed episodes, terminal evidence includes at minimum:

1. terminal net log growth; and
2. normalized causal-time area under log wealth:

```text
             tau_T
             /
    1       |       log(E_tau / B0) d tau
  -----     |
  tau_T     /
              0
```

The second measure records how early growth was achieved and retained. Terminal
growth and growth speed remain separate first-class outcomes. Pareto dominance
may be reported, but this ADR does not collapse them into a hidden scalar or
inject a human risk-preference weighting into Wildcard.

`ECONOMIC_DEAD_END`, integrity blocks, and other non-bankruptcy states must be
reported separately and cannot be relabeled to improve or worsen bankruptcy
statistics.

---

## 12. Reward-Pathology Gate

Before any ML training, deterministic scripted non-learning agents and fixtures
must test the world and reward for incentives or exploits involving:

- useless churn or pathological overtrading;
- inactivity solely to avoid loss;
- gambling for resurrection or pathological future leverage incentives;
- extreme concentration as a reward artifact rather than an economic outcome;
- unrealized-loss avoidance or mark-to-market manipulation;
- stale, illiquid, invalid, or missing-price exploitation;
- corporate-action, delisting, reorganization, or identity-accounting artifacts;
- artificial episode shortening or other termination exploits;
- dust orders, partial-fill boundaries, fees, or decimal rounding;
- temporary gains followed by bankruptcy overpowering terminal failure;
- inconsistent elapsed-time definitions; and
- hardware/replay-speed differences.

A real exploit must be corrected in world physics or reward semantics through a
new reviewed world version. It must not be hidden by adding strategy doctrine.

---

## 13. Failure-Loop Observability

Sealed raw archives and sterile reports must let authorized humans, Research ML,
and Qualification ML compare episodes for repeated bankruptcy patterns,
concentration or liquidity failures, execution failures, market-state mistakes,
inactivity or churn loops, and recurring growth-collapse cycles.

That classification occurs outside Wildcard. Wildcard receives neither the raw
prior archives nor downstream classifications. It receives only durable learning
artifacts that independently pass ADR-0011's complete causal-boundary and lineage
checks. A recurring failure may therefore recur before a prior lesson becomes
eligible; observability does not create an exception to the causal brick wall.

---

## 14. Deterministic Episode Seeds

Every episode receives a deterministic unique seed derived from:

- experiment-world fingerprint;
- model/base fingerprint;
- causal-learning lineage; and
- episode sequence identity.

The seed is recorded before the episode and cannot change after results are
observed. Favorable seeds may not be cherry-picked.

Controlled `DEVELOPMENT_ONLY` configuration comparisons use a fixed,
predeclared 16-seed ensemble unless a larger ensemble is frozen before results
are observed. Sequential apprenticeship episodes are not represented as 16
independent validation trials merely because they have different seeds.

---

## 15. World and Experiment Identity

Comparable episodes bind at minimum these immutable or content-addressed facts
into the experiment-world and episode provenance:

- $100,000 starting bankroll and USD currency;
- eligible instrument classes and point-in-time universe policy;
- fractional-share eligibility and 0.001-share precision;
- $1 minimum submitted order notional;
- deterministic decimal and settlement-precision contract;
- action-space version and deferred-capability boundary;
- DAY market-order semantics;
- next-causal-event-open execution convention;
- 1% volume participation and partial-fill rules;
- 5-basis-point simulated slippage and effective-dated fee model;
- bankruptcy and `ECONOMIC_DEAD_END` definitions;
- stale/non-realizable-value and reconciliation-block policy;
- causal-time definition;
- dense reward formula, functional family, and 24,570-minute half-life;
- terminal-evaluation contract;
- security master, universe, corporate actions, and reservoir manifests;
- event schema and deterministic ordering;
- model/base and causal-learning capsule lineage;
- RNG derivation policy and episode seed;
- report schema;
- code revision and execution environment; and
- applicable governance configuration.

Changing world physics creates a new experiment-world identity. Episodes from
incompatible identities must not be presented as one controlled population.

---

## 16. Crash and Restart Semantics

Process failure is neither bankruptcy nor an episode restart. Recovery follows
ADR-0011 and must restore the last atomic complete causal boundary, causally
eligible model state, deterministic RNG state, and reconciled account with its
cash, positions, liabilities, pending orders, and valid fills.

Recovery cannot duplicate an action or fill, skip or advance the market clock,
fabricate a finalization, expose a future learning artifact, or reset a valid
bankroll merely because a worker crashed. Only a legitimate terminal episode
outcome initiates the fresh-account earliest-boundary lifecycle described above.

---

## 17. Deliberately Deferred Capabilities

The following are deferred from V1, not permanently forbidden:

- **Limit orders:** require causal intrabar/queue semantics, limit eligibility,
  and more detailed fill ordering than the reservoir currently establishes.
- **Shorting:** requires borrow availability, recalls, fees, distributions,
  locate rules, forced closeout, and potentially unbounded liabilities.
- **Margin and leverage:** require maintenance rules, interest, calls,
  liquidation priority, and insolvency mechanics.
- **Options:** require contract identity, expirations, exercise/assignment,
  corporate-action adjustments, quotes/liquidity, and multi-leg liabilities.

Their absence constrains the V1 opportunity set and may bias early discovery
toward cash-equity behavior. Wildcard must not be told the deferred behaviors are
undesirable. A later world may add them only after their causal and accounting
physics are explicitly designed, tested, and fingerprinted.

GTC and other time-in-force variants, richer observed spread/impact models, and
unsupported instrument classes are likewise future versioned expansions.

---

## Explicit Unknowns

This ADR intentionally leaves the following unresolved for implementation or a
later reviewed decision:

- exact model family, learning algorithm, optimizer treatment, capsule cadence,
  and causally versioned parameter-composition mechanism;
- the exact reconciled-boundary cadence at which dense rewards are emitted;
- internal decimal scale and rounding rules beyond exact cent reconciliation at
  external cash settlement boundaries;
- effective-dated statutory/regulatory fee sources and formulas;
- authoritative per-security fractional-share eligibility evidence;
- exact deterministic order priority when multiple actions or securities share
  a causal boundary, including replace acknowledgement semantics;
- the precise evidence threshold for declaring a stale holding unreconcilable;
- authoritative disposition coverage for historical delistings and
  reorganizations;
- the proof procedure for permanence in `ECONOMIC_DEAD_END`;
- final report and check-in schema versions;
- historical-universe/reconstitution details beyond the point-in-time eligibility
  gates stated here;
- whether the completed reservoir will satisfy `TRAINING_ELIGIBLE`; and
- implementation resource limits and apprenticeship start authorization.

These unknowns may not be filled by implementation guesswork. Each must be
resolved by authoritative evidence, a reviewed subordinate contract, or an
explicit policy decision before its dependent executable behavior is built.

---

## Consequences

- V1 offers a meaningful neutral long cash-equity world without prescribing a
  trading method.
- Economic growth and earlier durable compounding drive learning; behavioral
  proxies remain evidence rather than reward shaping.
- Bankruptcy cannot be outweighed by temporary gains, and poor but solvent
  performance cannot be mislabeled bankruptcy.
- Missing lifecycle or valuation evidence blocks reconciliation instead of
  inventing wealth, loss, or liquidation.
- Replaying faster hardware does not alter time, reward, reports, or account
  outcomes.
- Any change in world physics creates a different experiment identity.
- The ADR-0011 causal memory wall remains absolute across bankruptcy,
  `ECONOMIC_DEAD_END`, and historical-completion restarts.

---

## Non-Authorization and Preservation Boundary

This ADR authorizes no accounting, execution, ML, reward, service, training,
deployment, acquisition, broker, Shadow, promotion, or runtime implementation.
It does not declare the historical reservoir training-eligible.

Historical acquisition, Clean-V2, DUMMY and broker state, runtime state, Shadow
Matrix enablement, Candidate V1, governed strategy semantics, existing frozen
datasets, manifests, checkpoints, and evidence remain untouched.

---

## References

- `AGENTS.md`
- `docs/adr/ADR-0010-forward-only-event-driven-causal-architecture.md`
- `docs/adr/ADR-0011-qpx-ml-actors-and-wildcard-causal-architecture.md`
