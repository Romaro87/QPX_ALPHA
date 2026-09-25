# QPX rule traceability

Status: human-audit reference; **not mandatory startup reading**.

The complete pre-consolidation documents are preserved verbatim in
`docs/governance/archive/pre_consolidation_2026-09-25/`. The checklist below is
deterministic: every row is an operative source clause or a tightly coupled
clause set, every row is marked `[x]`, and every row names one or more canonical
IDs. The user-authorized removal of per-prompt/archive rereading is recorded as
an amendment to QPX-01, not silently treated as unchanged policy.

| Archived source | Lines | Words | Bytes | SHA-256 |
|---|---:|---:|---:|---|
| `AGENTS.md` | 149 | 1,045 | 7,524 | `e8a978557e8bd4c3e5b082f658c761c0b115b1218eec9e370abfed70747c4cf6` |
| `QPX_CODEX_COMPLIANCE_PROMPT.md` | 272 | 1,760 | 12,545 | `8cc35c268593b97a85d8e71083224461c55e537076705ba958d477790a6463ea` |
| `QPX_CONTEXT_CONTINUITY_RULE.md` | 322 | 1,605 | 11,548 | `8e0bebc0d42f4b5f329a0037da43563d85315cacb2432a0c566543b52f0c7c4f` |
| `QPX_ASSISTANT_CODEX_FAILURE_WARNING.md` | 104 | 663 | 4,728 | `a60ebf1779908f45ce547db5db9227eb6132f41ce1fec78a5a6c0fe278d53c22` |
| `QPX_ASSISTANT_CODEX_ACCOUNTABILITY_AND_REFUND_RECORD.md` | 121 | 848 | 5,599 | `29ab4a3b1ed15822175f32b7f0418dc0543133e58bcfed5f55053791457c6d9a` |
| **Old mandatory total** | **968** | **5,921** | **41,944** | — |

## QPX_CODEX_COMPLIANCE_PROMPT.md

- [x] C01 Per-prompt, full-file, fail-closed read; no cached/partial read → QPX-01 (explicitly amended to once before actual work per continuous session).
- [x] C02 First work update states read/risk/scope/prohibitions/sequence/evidence → QPX-54.
- [x] C03 Mandatory archive chain and current task/contracts → QPX-01, QPX-02, QPX-03 (archive chain explicitly retired).
- [x] C04 Constitutional hierarchy; architecture over implementation; ADR/builders → QPX-02, QPX-17.
- [x] C05 Process rules subordinate; task amendments recorded at proper level → QPX-02, QPX-03.
- [x] C06 No waiver; retrieve/resolve conflicts without convenient selection → QPX-04.
- [x] C07 Follow governed road; no reinterpretation or implementation override → QPX-20, QPX-21, QPX-28.
- [x] C08 Verify repository/branch/HEAD/upstream/worktree; preserve unrelated work → QPX-08.
- [x] C09 Identify scope, criteria, order, prohibitions, surfaces, evidence → QPX-09.
- [x] C10 Risk classification/pre-code gate; stop missing prerequisites → QPX-10–QPX-14.
- [x] C11 Direct impact is semantic; inspect affected paths only → QPX-15.
- [x] C12 Smallest change; reuse mechanisms; preserve behavior; defer nonblockers → QPX-07, QPX-20, QPX-21.
- [x] C13 No fabricated/reacquired/relabelled evidence; RAM is buffer → QPX-22.
- [x] C14 Keep acquisition/qualification/eligibility/training/promotion/capital and priority/exclusivity distinct → QPX-23.
- [x] C15 Focused and affected tests; no ceremonial broad tests → QPX-29–QPX-31.
- [x] C16 Literal sequence and prerequisite transactions; later success does not cure → QPX-36.
- [x] C17 Exact runtime evidence; tests/logs/startup are not substitutes; classify blockers/readiness → QPX-32.
- [x] C18 Authorized unattended recovery only → QPX-37.
- [x] C19 Accepted work on main; temporary isolation only while unfinished → QPX-38.
- [x] C20 Explicit staging, inspect stage, preserve unrelated changes → QPX-39.
- [x] C21 Same-push recovery prompt/ledger/journal continuity → QPX-41.
- [x] C22 Verify local/tracking/remote target; honor CI/test scope → QPX-39, QPX-42.
- [x] C23 Pre-commit/push completion audit; no retroactive repair → QPX-43.
- [x] C24 Evidence classifications; separate claim domains; no unsupported success → QPX-06, QPX-48.
- [x] C25 Evidence-to-claim matrix, including skipped-CI absence proof → QPX-34, QPX-35.
- [x] C26 Sixteen-item completion audit and evidence-backed YES answers → QPX-50.
- [x] C27 Mandatory implementation completion fields → QPX-51.
- [x] C28 Build governed architecture, prevent corruption, fix blockers, preserve evidence, keep moving → QPX-07, QPX-17, QPX-22, QPX-52.

## AGENTS.md

- [x] A01 Constitution outranks process rules → QPX-02.
- [x] A02 Per-message compliance read/fail-closed/no carry-forward → QPX-01 (explicitly amended).
- [x] A03 Focused changed-behavior and affected dependency tests → QPX-29.
- [x] A04 No automatic broad suite for shared/additive changes or ceremony → QPX-31.
- [x] A05 Broad-suite authorization cases require a concrete semantic reason → QPX-31.
- [x] A06 Update all affected contract tests/fixtures and require passage → QPX-30.
- [x] A07 Inspect affected siblings/consumers and reuse existing mechanisms → QPX-15, QPX-20.
- [x] A08 LOW/MEDIUM/HIGH definitions and gates → QPX-10–QPX-13.
- [x] A09 Stop uncovered semantic questions; tests do not design policy → QPX-14.
- [x] A10 Keep gates and resource use shortest sufficient → QPX-07, QPX-12.
- [x] A11 Implementation report fields and incomplete status on violation → QPX-49, QPX-51.

## QPX_CONTEXT_CONTINUITY_RULE.md

- [x] R01 Constitution/subordinate hierarchy → QPX-02.
- [x] R02 Per-prompt compliance read/no carry-forward → QPX-01 (explicitly amended).
- [x] R03 Warn about five exchanges, conservatively before substantial work → QPX-44.
- [x] R04 Restore point before context exhaustion → QPX-44.
- [x] R05 Restore point contents and evidence labels → QPX-06, QPX-46.
- [x] R06 Missing parameters are configurable/versioned and must not be invented → QPX-16, QPX-19.
- [x] R07 Safety/accounting/provenance invariants are not tunable → QPX-16, QPX-24.
- [x] R08 Retrieve missing context; never reinterpret/invent history → QPX-47.
- [x] R09 Rules/contracts are criteria; retrieve higher authority → QPX-02, QPX-04, QPX-50.
- [x] R10 Inspect semantically affected surfaces/reuse mechanisms/no new bureaucracy → QPX-07, QPX-15, QPX-20.
- [x] R11 Same-push recovery prompt; substantive ledger/journal → QPX-41.
- [x] R12 Explicit staging, ref verification, accepted main → QPX-38, QPX-39, QPX-42.
- [x] R13 Terminal/Git-backed artifacts preferred → QPX-46.
- [x] R14 Preserve maximum reasonably available context/conversation → QPX-46.
- [x] R15 Do not convert assistant statements to user decisions; label reconstruction → QPX-06, QPX-46, QPX-47.
- [x] R16 Five-minute checkpoint cadence; ten-minute target maximum; early triggers → QPX-45.
- [x] R17 Preferred append-only dated journal; do not replace prior entries → QPX-46.
- [x] R18 Exact checkpoint state inventory → QPX-46.
- [x] R19 Evidence classifications remain mandatory → QPX-06.
- [x] R20 Direct-Git limitation requires immediate shortest safe user command → QPX-47.
- [x] R21 User must not re-explain state; preserve granular truth → QPX-46, QPX-47.

## QPX_ASSISTANT_CODEX_FAILURE_WARNING.md

- [x] W01 No over-engineering, invented blockers/gates, serial design, premature hardening, or moved goalposts → QPX-07, QPX-28, QPX-52.
- [x] W02 Build architecture, prevent known corruption, fix observed blockers, use focused tests, defer noncritical hardening → QPX-07, QPX-17, QPX-22, QPX-29.
- [x] W03 Clean-V2 priority is not historical exclusivity → QPX-23, QPX-27.
- [x] W04 Capacity arbitration governs download and finalization; market-open alone is not a finalization gate → QPX-27.
- [x] W05 Existing governance/test/pre-code gates remain criteria → QPX-02, QPX-10–QPX-14, QPX-29–QPX-31, QPX-50.
- [x] W06 Passed milestones move; risk class does not authorize disproportionate scrutiny → QPX-07, QPX-52.
- [x] W07 Former full-file per-prompt reading instruction → QPX-01 (explicitly amended).

## QPX_ASSISTANT_CODEX_ACCOUNTABILITY_AND_REFUND_RECORD.md

- [x] K01 Former full-file per-prompt reading instruction → QPX-01 (explicitly amended; narrative retained only as archive evidence).
- [x] K02 No added bureaucracy/tests/design loops/hardening/blockers → QPX-07.
- [x] K03 Follow settled decisions, retrieve rather than reinvent, keep scope narrow, test proportionally, finish milestones → QPX-07, QPX-20, QPX-28, QPX-29, QPX-52.
- [x] K04 Refund request and incident narrative → non-operative historical evidence; archived verbatim, no canonical rule.

## docs/CONSTITUTION.md

- [x] N01 Professional modular/explainable/testable quantitative platform purpose and supported capabilities → QPX-05.
- [x] N02 Strategy-agnostic mission; understandable/testable/reproducible decisions → QPX-05, QPX-25.
- [x] N03 Architecture governs implementation; major changes require ADR → QPX-02, QPX-17.
- [x] N04 Builder-first, repeatable structure when practical → QPX-17.
- [x] N05 Clear subsystem responsibility, cohesion, loose coupling, no orphans → QPX-18.
- [x] N06 Explainable decisions, reproducible calculations, traceable automation → QPX-25.
- [x] N07 Significant-feature tests, deployable platform, no broken baseline → QPX-28, QPX-33.
- [x] N08 Documentation deliverable synchronized with architecture/implementation → QPX-26.
- [x] N09 Independent milestone commits and documented transitions → QPX-40.
- [x] N10 Strategies/risk/allocation/execution configurable; no single hardcoded strategy → QPX-05, QPX-19.
- [x] N11 Architecture→Builder→Testing→Doctor→Commit→Push; validations before completion → QPX-33.
- [x] N12 Risk preference belongs to strategy, not platform → QPX-19.
- [x] N13 Maintainability/reliability/modularity/consistency/reproducibility/transparency/professional quality → QPX-05.
- [x] N14 Constitutional authority order and conflict resolution → QPX-02.

## Consolidation amendment and validation contract

- [x] M01 Ordinary discussion/planning requires no governance read → QPX-01.
- [x] M02 Canonical file is the sole actual-work mandatory read; no recursive archive reads → QPX-01.
- [x] M03 Future governance amendment updates canonical and traceability together → QPX-53.
- [x] M04 Narrative records never become mandatory automatically → QPX-53.
- [x] M05 Financial/runtime/deployment safeguards remain explicit → QPX-16, QPX-22–QPX-24, QPX-32, QPX-35–QPX-43, QPX-48–QPX-51.
