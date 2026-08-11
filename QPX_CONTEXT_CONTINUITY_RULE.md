# QPX_ALPHA CHAT CONTEXT CONTINUITY RULE

**STATUS: USER_CONFIRMED / PERMANENT OPERATING RULE — 2026-08-11**

This rule applies to every ChatGPT conversation used to develop, operate, research, debug, document, or plan QPX_ALPHA.

## Early warning

The assistant must warn the user **about five messages/exchanges before the conversation is likely to reach its usable context-length limit**, to the extent that remaining context can reasonably be estimated.

The assistant must warn **before starting another substantial block of work** when the conversation appears close enough to the limit that the next several exchanges could exhaust usable context.

The assistant must not intentionally wait until the last message or until usable context is already exhausted.

Because exact remaining context may not be directly observable, "about five messages" is an early-warning target, not an exact counter. When uncertain, warn conservatively early.

## Restore point

When the warning is triggered, priority shifts to creating or updating a durable QPX restore point before continuing major new work.

The restore point should preserve, as applicable:

- repository and branch
- latest verified Git commit/checkpoint
- current code/research state
- latest test results
- active errors/blockers
- files created/changed
- important commands and outputs
- decisions approved since the previous restore point
- unresolved questions
- current strategy/research configuration
- data/provider state
- hardware/environment state when relevant
- next exact implementation step

All recovered material must continue to be classified honestly as:

- VERIFIED_REPO
- VERIFIED_ARTIFACT
- USER_CONFIRMED
- USER_APPROVED
- USER_REQUIREMENT
- RECOVERED_CONTEXT
- ASSISTANT_PROPOSED
- DISCUSSED
- FUTURE_DECISION
- UNKNOWN / UNRECOVERED

## Purpose

The purpose of this rule is to prevent another QPX context-loss event from forcing repeated reconstruction of settled decisions, capabilities, features, architecture, research state, or debugging history.

**DO NOT REINTERPRET. DO NOT INVENT MISSING HISTORY.**

<!-- QPX_PER_PUSH_RECOVERY_RULE_20260811 -->
## PER-PUSH RECOVERY PROMPT RULE
**STATUS: USER_CONFIRMED — 2026-08-11**
Every QPX push must include a freshly updated `QPX_RECOVERY_PROMPT.md`.
Substantive milestones also update `QPX_RECOVERY_DECISION_LEDGER.md`.
Never use `git add .` for this purpose and never silently stage unrelated work.
Verify local HEAD equals remote main after every push.
This rule does not replace the five-exchange context-length warning.
Prefer terminal-created files and Git checkpoints over browser downloads or browser refreshes.

<!-- QPX_MAXIMUM_GRANULAR_CONVERSATION_RECOVERY_20260811 -->
# MAXIMUM-GRANULARITY CONTEXT AND CONVERSATION RECOVERY RULE

**STATUS: USER_CONFIRMED / PERMANENT — 2026-08-11**

This rule applies to every QPX_ALPHA development, research, debugging,
architecture, infrastructure, Git, Codex, deployment, hardware, strategy,
and planning conversation.

## 1. Maximum granularity is mandatory

Every QPX context checkpoint, recovery prompt, recovery journal, project
handoff, restore point, and context retrieval must preserve the **most
granular context reasonably available**.

A short summary is not sufficient when exact information exists.

The user should never again have to explain:

- where QPX currently is
- what was just done
- what was tested
- what succeeded
- what failed
- what was discussed
- what was rejected
- what is undecided
- what hardware was discussed
- what workflow was being changed
- what files were created or modified
- what command was run
- what output resulted
- what the next exact action is

## 2. Preserve conversation, not merely conclusions

Context checkpoints must preserve as much of the actual QPX conversation
as reasonably available.

Where available, preserve:

- chronological user messages
- important assistant responses
- exact user corrections
- exact requirements
- decisions
- objections
- failed recovery attempts
- misunderstandings and their corrections
- relevant tool/repository findings
- important command output
- important code/test results
- unresolved questions
- the reason a decision was made
- the exact next step

User wording should be preserved verbatim where available and useful.

Assistant statements must not silently be converted into user decisions.

If exact conversation text is unavailable, clearly label the recovered
material as summarized/reconstructed rather than pretending it is verbatim.

## 3. Active-conversation backup cadence

During active QPX work, context must be checkpointed approximately every
**5 minutes**, with **10 minutes as the absolute maximum target interval**
between checkpoints when substantial conversation is occurring.

A checkpoint must happen sooner than five minutes when any of these occur:

- major user decision
- architecture decision
- strategy decision
- hardware decision
- workflow decision
- code creation
- code modification
- significant test run
- meaningful test result
- new failure/blocker
- bug diagnosis
- important research result
- Git commit/push
- correction of previously recovered history
- context recovery event
- imminent chat/context exhaustion
- browser/session instability
- transition to another development tool such as Codex

This is an **active-work cadence**, not a claim that ChatGPT can wake itself
up asynchronously when no conversation is occurring.

## 4. Conversation delta files

The preferred durable format is an append-only daily conversation journal:

`QPX_CONVERSATION_JOURNAL_YYYY-MM-DD.md`

Each checkpoint should append a new delta containing, where available:

- timestamp and timezone
- conversation sequence
- verbatim user messages
- important assistant responses or precise summaries
- decisions made
- corrections
- commands
- tool findings
- files changed
- test outputs
- repository state
- blockers
- unresolved items
- next exact action

Do not replace previous journal entries.

## 5. Every checkpoint must capture exact state

Where available, preserve:

- repository
- branch
- local HEAD
- remote HEAD
- commit SHA
- commit message
- worktree status
- staged files
- files intentionally left unstaged
- files created
- files changed
- configuration values
- dataset identities
- dataset fingerprints
- selection fingerprints
- report paths
- test names
- test counts
- exact PASS / FAIL / UNQUALIFIED status
- exact numerical research results
- control/comparison results
- errors
- exception text
- failed approaches
- reason an approach failed
- active blocker
- user-approved decisions
- user requirements
- assistant proposals not yet approved
- deferred decisions
- UNKNOWN / UNRECOVERED material
- next exact implementation step

## 6. Evidence classification remains mandatory

Every recovered item must continue to distinguish:

- VERIFIED_REPO
- VERIFIED_ARTIFACT
- USER_CONFIRMED
- USER_APPROVED
- USER_REQUIREMENT
- RECOVERED_CONTEXT
- ASSISTANT_PROPOSED
- DISCUSSED
- FUTURE_DECISION
- UNKNOWN / UNRECOVERED

Never fill missing history with a plausible invention.

## 7. Git-backed continuity

Every meaningful QPX Git push must include an updated recovery prompt.

Substantive checkpoints must also update the decision ledger and relevant
conversation journal.

Never use:

`git add .`

for context preservation.

Stage only explicitly intended files.

After every push verify that local HEAD and remote `main` match.

## 8. Failure to write directly to Git

If the active ChatGPT integration cannot write directly to GitHub, that is
not permission to skip the checkpoint.

The assistant must immediately produce the shortest safe phone/Termux
command needed to create and push the checkpoint.

Do not continue through large amounts of substantive QPX work while known
important context remains only inside chat.

## 9. Core requirement

**THE USER MUST NOT HAVE TO RE-EXPLAIN WHERE QPX IS.**

**PRESERVE THE MOST GRANULAR CONTEXT AVAILABLE.**

**PRESERVE AS MUCH OF THE ACTUAL CONVERSATION AS AVAILABLE.**

**DO NOT REINTERPRET. DO NOT INVENT MISSING HISTORY.**
