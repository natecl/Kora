# Kora Portion 1 Roadmap

**Status:** Approved next-step sequence
**Updated:** 2026-08-26

This roadmap turns the existing PRD, technical architecture, and current-state
recommendation into an execution order. It does not change Kora's product
decisions. The first proof must be that Kora can keep an approved product
mission moving without a human continuously steering an agent session. Product
surfaces and additional channels follow that proof.

## The sequence

| Order | Phase | Primary question | Exit gate |
|---|---|---|---|
| 1 | **Headless autonomous development loop** | Can Kora preserve intent, choose the next unblocked task, run it safely, verify the result, and stop or escalate correctly? | A disposable sample product mission runs from explicit approval to verified code/test/artifact evidence, survives process restart, and stops on ambiguity or missing authority without inventing work. |
| 2 | **Desktop and context productization** | Can a person understand, correct, and approve Kora's interpretation without configuring an agent workforce? | A five-to-ten-minute desktop onboarding produces a context-alignment receipt, an approved mission contract, a readable Kora skill/context view, and a semantic work projection. |
| 3 | **Cloud and phone continuity** | Can Kora keep working while the user's Mac is closed and handle normal interaction from a phone? | A persistent logical cloud workspace resumes approved work while the Mac is offline; iMessage, calls, daily alignment, and mobile review/approval preserve the same mission state. |
| 4 | **Deployment and approved outreach** | Can Kora carry a verified MVP through consequential external actions with bounded authority? | The user can approve production deployment and a bounded initial outreach campaign; Kora executes, records receipts, reports outcomes, and never treats connector access as authority. |

This is a sequence, not a requirement to build every phase in parallel. Later
phases may inform interface contracts, but they should not pull product work
forward before the preceding proof is credible.

## Phase 1: headless autonomous development loop

Portion 1 is the control-plane slice that makes the first phase testable. It
should add the smallest Kora-owned layer above the existing Hermes runtime
adapter. Hermes is only Kora's replaceable initial execution harness, not
Kora's product foundation: the mission store and authority boundary must remain
valid if the harness is replaced.

1. A durable SQLite mission store for the approved mission contract, tasks,
   dependencies, decisions, assumptions, checkpoints, escalations, permission
   grants, and evidence/artifacts.
2. A mission controller that enforces one overarching mission, chooses the
   highest-value unblocked task on the critical path, and owns stop conditions.
3. A separate authority check that turns a task's required capabilities into a
   narrow runtime job only when the corresponding decision authority exists.
4. A headless loop that submits work through the existing
   [`HermesRuntimeAdapter`](../src/kora/runtime/hermes.py) or
   [`HermesACPRuntimeAdapter`](../src/kora/runtime/hermes_acp.py), then maps
   sanitized runtime results into Kora task state.
5. Evidence and evaluation gates that reject an unsupported
   `KORA_TASK_COMPLETE`, attach tests/diffs/artifacts, and expose unresolved
   risk before completion.
6. A disposable sample product repository and scripted ambiguity, failure, and
   permission fixtures so the behavior can be proven without external
   accounts.

Hermes memory, scheduling, approvals, and self-improvement state are never
authoritative. They may support commodity execution behind `RuntimeAdapter`,
but Kora's SQLite state, controller, semantic permissions, evidence, and stop
conditions are the source of truth.

The loop is headless, not authority-free. A mission is created in
`AWAITING_MISSION_APPROVAL` and becomes active only after an explicit owner
approval through the CLI or application service. The initial sample mission
may use a pre-reviewed contract, but it still exercises that approval boundary.

### Phase 1 definition of proof

The first end-to-end run is successful only if it demonstrates all of the
following in one preserved run record:

- the owner approves one bounded mission;
- Kora creates or loads a task graph inside that mission;
- the controller selects a ready task without a new prompt choosing it;
- the runtime receives only the task's workspace, toolset, capability, and
  isolation envelope;
- a code change is made in a disposable cloud workspace and is verified with
  tests or an equivalent acceptance check;
- the result is represented as evidence/artifact records rather than a model
  claim alone;
- restarting the controller resumes from SQLite without losing the mission or
  repeating a completed side effect;
- a deliberately ambiguous requirement creates an escalation and stops the
  affected path;
- a missing or denied authority grant prevents the consequential action;
- unrelated work is not generated merely to keep the process busy.

The detailed data model, state machine, persistence boundary, and proposed
interfaces for this phase are in
[`PORTION_1_MISSION_CONTROL_PLANE.md`](./PORTION_1_MISSION_CONTROL_PLANE.md).

## Phase 2: desktop and context productization

Once the headless loop is reliable, wrap it in the first user-facing control
surface. This phase productizes the existing control-plane contracts rather
than replacing them.

- Add the desktop onboarding flow beginning with **“What are you working on?”**.
- Ingest local and connected context, then show included, excluded, stale,
  duplicate, inaccessible, and conflicting sources.
- Let the user approve the proposed source authority and mission contract.
- Compile user-readable Markdown knowledge and skills with provenance,
  confidence, freshness, and version history.
- Project mission state into the semantic Work/Kanban view: Working, Next,
  Waiting on you, Ready for review, and Done.
- Present checkpoints and escalations as natural coworker communication;
  internal task and worker topology remains hidden.
- Allow corrections to be reviewed as behavior-changing diffs before they
  become authoritative.

The exit gate is an onboarding and alignment exercise that a founder can
complete in ten minutes or less and that catches a deliberately conflicting
source before implementation begins. The runtime loop must still be able to
run without the desktop app open.

## Phase 3: cloud and phone continuity

After the control plane and desktop projection are trustworthy, move execution
and normal conversation off the developer laptop.

- Provision one durable logical cloud workspace with isolated branches or
  containers for execution.
- Persist approved context, mission state, artifacts, and scoped connector
  references outside any model context window.
- Add scheduling and wakeups governed by the mission controller.
- Add iMessage continuity, Kora-initiated daily calls, meeting transcription,
  concise recaps, and mobile-friendly preview/review links.
- Add the restricted Mac bridge only for explicitly scoped discovery,
  snapshots, synchronization, and recoverable local actions.
- Verify that the Mac can be offline while approved work continues and that a
  user can complete most reviews and approvals from the phone.

The cloud workspace is an implementation of Kora's continuity, not a remote
desktop or VM-management product. The user continues to experience one Kora.

## Phase 4: deployment and approved outreach

Only after the cloud and phone loop is reliable should Kora cross the external
boundaries that define the later parts of the first complete mission.

- Add reviewed Vercel, Supabase, and other provider connectors with separate
  read and write capabilities.
- Prepare a production deployment, show its evidence and consequences, and
  require explicit deployment approval or a bounded standing grant.
- Research the ICP and positioning, prepare an initial outreach campaign, and
  show its audience, content, budget, action limit, and expiration.
- Execute only after the user approves the campaign mandate.
- Record delivery receipts, responses, failures, and evidence of outcomes.
- Keep spending, publishing, consequential messages, account changes, and
  other external actions behind Kora's authority engine.

The outreach phase is not a generic growth automation system. It is the final,
approved step of the product-development mission and must stop when the user,
authority, evidence, or external system is the bottleneck.

## Later runtime-hardening task

Selecting and validating a tagged Hermes release together with an immutable
container digest is a later runtime-hardening task. It is separate from the
Portion 1 mission-store implementation: the mission store must be designed and
tested against the replaceable `RuntimeAdapter` boundary, not coupled to a
particular Hermes release or container image. OpenHands is only a gated
fallback if Hermes fails concrete vertical-slice gates, and must satisfy the
same Kora-owned adapter and authority contract.

## Governing constraints for every phase

- The latest explicit user instruction and active mission approval outrank all
  other context. The PRD and architecture remain the normative product and
  system specifications.
- Kora may choose internal tasks, but cannot create or silently replace the
  overarching mission.
- Technical access and decision authority are separate. A connector or runtime
  capability never proves permission to act.
- Material ambiguity is discussed; safe reversible inference is recorded as an
  assumption; technical infeasibility first triggers a faithful alternative.
- Evidence, not activity or persuasive language, proves completion.
- When the critical path is blocked and no other approved work advances it,
  Kora waits or pauses rather than inventing work.
- Models, prompts, workers, routing, compaction, tokens, and runtime topology
  remain hidden from the user-facing product.

## Baseline references

- [`KORA_V1_PRD.md`](../KORA_V1_PRD.md)
- [`KORA_TECHNICAL_ARCHITECTURE.md`](../KORA_TECHNICAL_ARCHITECTURE.md)
- [`docs/kora-context/README.md`](./kora-context/README.md)
- [`docs/kora-context/CURRENT_STATE.md`](./kora-context/CURRENT_STATE.md)
- [`HERMES_SPIKE_REPORT.md`](../HERMES_SPIKE_REPORT.md)
