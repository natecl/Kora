# Portion 1 Mission Control Plane

**Status:** Accepted implementation slice and boundary design
**Updated:** 2026-08-27
**Canonical code commit:** `1754168ed09692ed1b5a611ad6b06a220b42543b`

This document describes the accepted Kora-owned mission control plane work
cycle. It is deliberately above the existing Hermes execution adapters and
below future desktop, phone, connector, and deployment surfaces. It refines the
existing PRD and architecture; it does not replace or amend their normative
product decisions or claim whole-product release readiness.

## 1. Purpose and scope

The accepted Portion 1 slice makes one thing demonstrable:

> After the owner explicitly approves one bounded product-development mission,
> Kora can select and execute the next valuable task in a disposable cloud
> workspace, preserve intent and authority outside the model session, verify
> the result with evidence, and stop or ask for the smallest human input when
> the path is blocked.

The verified dogfood fixture starts with an empty repository and a founder brief
and produces a functional, zero-dependency waitlist MVP. At canonical commit
`1754168ed09692ed1b5a611ad6b06a220b42543b`, the Sol High review verdict is
**ACCEPT**; 27 focused acceptance/regression tests and 168 full-suite tests pass.
No P0/P1/P2 findings were identified in the implemented verified work-cycle
slice. This is a control-plane proof only, not a release claim for the complete
Kora product.

The control plane owns mission meaning, lifecycle, authority, prioritization,
evidence, and recovery. The runtime owns execution mechanics. A model may
propose work or a result, but it cannot directly mutate mission state, grant
itself authority, broaden scope, or declare completion without the controller's
validation.

### 1.1 Replaceable harness boundary

Hermes is Kora's replaceable initial execution harness, not Kora's product
foundation. It provides commodity provider/model, tool, skill, subagent, MCP,
session, and sandbox execution only behind `RuntimeAdapter`. Kora must own the
durable state and policy that define the product:

- identity and relationship state;
- mission state, task state, and stop conditions;
- context, provenance, source authority, and conflict references;
- semantic permissions and decision authority;
- evidence, evaluation, and completion criteria;
- cloud-workspace policy, isolation, and recovery rules.

The current code also proves durable task attempts, leases and fencing,
budget reservation/settlement for private routes, descriptor-bound workspace
execution, closed public projections, and bounded evidence for tracked,
ignored, untracked, empty-directory, and nested-`.git` state.

Hermes memory, scheduler, approvals, and self-improvement state are never
authoritative. An adapter may use those capabilities to execute a Kora task,
but their output is an untrusted runtime input that the Kora controller must
validate and persist in its own records. Replacing Hermes must not change
Kora's identity, relationship, mission, authority, context, evidence, or
user-facing behavior contracts.

The current [`HermesRuntimeAdapter`](../src/kora/runtime/hermes.py) and
[`HermesACPRuntimeAdapter`](../src/kora/runtime/hermes_acp.py) are the transport
boundary for this slice. The controller, not Hermes, decides whether to invoke
them, which task-scoped capabilities to pass, whether an ACP permission option
is allowed, and whether a result is evidence-bearing.

Selecting and validating a tagged Hermes release plus an immutable container
digest is a later runtime-hardening task. It is intentionally separate from
the Portion 1 mission-store implementation; the store and application service
must remain harness-independent. OpenHands is only a gated fallback if Hermes
fails concrete vertical-slice gates, and must satisfy the same adapter and
authority contract.

Portion 1 includes:

- one active overarching mission;
- a pre-reviewed mission contract and explicit approval;
- a persistent SQLite state store;
- an internal task/dependency graph and deterministic next-task selection;
- task-scoped capability and authority checks;
- a bounded headless execution loop over the current Hermes adapters;
- semantic checkpoints, escalations, and user responses;
- evidence/artifact references and an independent verification gate;
- append-only state transitions and audit events;
- restart and idempotency behavior for a disposable sample repository.

The proposed CLI and service operations are intentionally small. They are the
headless contract that later desktop, phone, and cloud surfaces can call.

The next live-runtime slice is a **NOT-YET-IMPLEMENTED Codex App Server
adapter**. For founder dogfood/testing it is intended to use the founder's
ChatGPT-managed Codex subscription authentication; Codex owns and refreshes
credentials, tokens never enter Kora durable state or public projections, and
Kora may privately observe plan/rate-limit state. Production uses
company-owned API keys/provider accounts with metering, budgets, and billing,
never a personal Codex subscription. The transport switch must preserve Kora's
durable mission, permission, evidence, memory, and routing contracts.

## 2. Authority and behavior contract

### 2.1 Source authority order

Every mission contract, decision, assumption, task plan, and consequential
action must carry source references and use this precedence order:

1. The latest explicit user instruction.
2. The active mission, definition of done, and current approval scope.
3. [`KORA_V1_PRD.md`](../KORA_V1_PRD.md) for approved product behavior.
4. [`KORA_TECHNICAL_ARCHITECTURE.md`](../KORA_TECHNICAL_ARCHITECTURE.md) for
   system invariants and technical boundaries.
5. [`BEHAVIOR_CONTRACT.md`](./kora-context/BEHAVIOR_CONTRACT.md) and
   [`KORA_IDENTITY.md`](./kora-context/KORA_IDENTITY.md) for durable behavior
   and identity.
6. [`FOUNDER_CONTEXT.md`](./kora-context/FOUNDER_CONTEXT.md) for
   personalization and interpretation only.
7. [`PRODUCT_DECISION_LEDGER.md`](./kora-context/PRODUCT_DECISION_LEDGER.md)
   and [`SOURCE_CONTEXT.md`](./kora-context/SOURCE_CONTEXT.md) for historical
   rationale only.

The SQLite record stores references to sources and the approved context or
mission revision; it does not turn a historical document into authority. A
runtime prompt, worker result, cached model context, or connector response
cannot outrank the active mission or an explicit owner decision.

### 2.2 Behavioral rules enforced outside the model

- **Align before action:** a mission starts in `PROPOSED`, becomes `ALIGNED`
  after its contract is ready, and reaches `ACTIVE` only through an explicit
  owner approval.
- **One mission:** the controller permits at most one non-terminal overarching
  mission. Internal tasks and subgoals remain children of that mission.
- **Intent fidelity:** safe reversible inferences are recorded as assumptions;
  material ambiguity creates an escalation; technical blockage triggers a
  faithful alternative before a product change is proposed.
- **Critical-path work:** the scheduler selects the highest-value unblocked
  task that advances the mission and does not interfere with its critical path.
- **Authority separation:** a runtime capability is necessary but not
  sufficient for a consequential action. The controller also requires a
  matching, unexpired, in-scope permission grant.
- **Exact semantic authority:** preflight and authorization must match the
  active mission, permission grant, action class, resource scope, applicable
  limits, and idempotency key. A connector, capability, or runtime request
  cannot supply any missing part of that authority.
- **Budget discipline:** a private model route is reserved before execution and
  settled with actual usage or a bounded failure outcome; reservation and
  settlement do not become user-facing routing controls.
- **Evidence gate:** a runtime completion marker is only a candidate result.
  The controller requires attached and verified evidence before completing a
  task or mission.
- **Correct stopping:** an unresolved critical-path escalation, missing
  authority, safety boundary, user stop request, or scope conflict pauses the
  affected work. No unrelated work is manufactured to look autonomous.
- **One visible Kora:** records contain concise rationale, decisions,
  assumptions, evidence, and state. They do not expose prompts, chain of
  thought, model/provider identity, worker topology, route details, tokens, or
  raw runtime traces. Public projections are closed Kora-owned allowlists.

## 3. Control-plane concepts

The record definitions below are the intended stable application contract. The
current implementation proves the durable mission/task/attempt/permission/
evidence subset and the guards described in the accepted slice; fields or
surfaces not present in the source remain target design, not current-state
claims.

### 3.1 Common record rules

All records use the following conventions:

- IDs are stable opaque strings. `mission_id` and `task_id` must remain
  compatible with the current adapter's identifier contract in
  [`contracts.py`](../src/kora/runtime/contracts.py): an ASCII identifier that
  starts with a letter or number and is at most 128 characters.
- Timestamps are UTC ISO 8601 values or an equivalent integer representation;
  the format must be consistent within the database.
- Records have a monotonically increasing `revision`. Mutations use an
  expected revision to prevent a stale process from overwriting a newer user
  decision.
- `revision` protects a record projection; the mission's `scope_version` and
  `scope_hash` protect the approved contract. They advance under different
  guards and must not be conflated.
- Every material record has `created_by`, `source_refs`, and a corresponding
  append-only event. `created_by` is one of `owner`, `kora`, `controller`,
  `runtime`, or `system`.
- State changes are append-only facts plus a current-state projection. A record
  is never hard-deleted to hide a decision, action, or failure.
- Extensible fields use canonical, sanitized JSON. JSON is not a bypass around
  relational state checks, foreign keys, or authority validation.
- Source references identify a document, conversation, artifact, or user
  response; they are not a place to store credentials, private chain of
  thought, or unbounded raw transcripts.

### 3.2 Mission

A mission is the single user-approved overarching outcome that governs every
task in Portion 1.

| Field | Meaning |
|---|---|
| `mission_id` | Stable identity passed to every runtime job. |
| `title` | Short human-readable name; not the authority itself. |
| `objective` | The approved outcome in concrete terms. |
| `definition_of_done` | Observable completion conditions. |
| `exclusions` | Explicitly out-of-scope work and product boundaries. |
| `acceptance_evidence` | Evidence classes required before completion. |
| `context_snapshot_ref` | Approved context/mission input revision, if one exists in the fixture. |
| `authority_envelope` | Human-readable summary of allowed action classes and limits; actual grants remain separate records. |
| `scope_version`, `scope_hash` | Monotonic approved contract version and integrity hash; tasks bind to this version. |
| `status` | One of the mission lifecycle states below. |
| `owner_ref` | The authoritative user identity for approval and correction. |
| `approved_decision_id` | The explicit owner decision that activated the mission. |
| `active_checkpoint_id` | Current semantic progress marker, if any. |
| `blocked_reason` | Concise user-relevant reason when waiting or paused. |
| `created_at`, `approved_at`, `completed_at` | Lifecycle timestamps. |

The objective, definition of done, exclusions, and authority envelope are
immutable after approval for this slice. A material change is a new proposed
scope version with a new decision and explicit re-alignment path; it cannot
silently mutate the active version. Tasks record the scope version they were
planned against and cannot start when that version is stale. An agent cannot
edit the mission in place or create a replacement goal.

### 3.3 Task

A task is an internal, mission-scoped unit of work that produces an outcome or
an evidence-bearing decision. Tasks are not a user-managed generic to-do list.

| Field | Meaning |
|---|---|
| `task_id`, `mission_id` | Stable identity and owning mission. |
| `title`, `objective` | What the task must accomplish and why it advances the mission. |
| `kind` | A bounded category such as `research`, `design`, `implement`, `review`, or `verify`. |
| `definition_of_done` | Task-level observable result. |
| `acceptance_criteria` | Criteria that the evaluator must check. |
| `mission_scope_version` | Approved mission scope version used to plan this task. |
| `priority` | Mission-relative priority; never a global agenda. |
| `critical_path` | Whether blocking this task blocks the mission's current path. |
| `required_capabilities` | Kora capability values needed for the runtime job, such as `workspace.write` or `workspace.execute`. |
| `workspace_scope` | Relative path or project scope inside the approved cloud root. |
| `source_refs` | Mission, PRD, decision, or evidence references supporting the task. |
| `status` | Task lifecycle state. |
| `blocked_reason` | Current dependency, authority, ambiguity, or failure reason. |
| `attempt_count`, `lease_expires_at` | Recovery metadata for a bounded execution attempt. |
| `last_runtime_status` | Sanitized mapping from `RuntimeStatus`, never a raw provider trace. |
| `created_by` | Usually `controller` or `kora`; a runtime cannot create an unscoped task. |

Kora may create and prioritize tasks inside the approved mission. The
controller rejects a task whose mission reference, objective, or workspace
scope falls outside that mission.

### 3.4 Dependency

A dependency is a directed relation between two tasks in the same mission.
Portion 1 needs only a blocking relation, but the record is explicit so the
controller can explain why a task is not ready.

| Field | Meaning |
|---|---|
| `dependency_id` | Stable edge identity. |
| `mission_id` | Owning mission; both endpoints must belong to it. |
| `predecessor_task_id` | Task whose outcome is required. |
| `successor_task_id` | Task held until the predecessor condition is met. |
| `relation` | `blocks` in Portion 1. |
| `condition` | The evidence or state that satisfies the edge. |
| `reason` | Human-readable mission relevance. |
| `status` | `OPEN`, `BLOCKED`, `SATISFIED`, `INVALIDATED`, or `SUPERSEDED`. |
| `source_refs` | Plan or decision references that justify the dependency. |

The graph must remain acyclic. A dependency is not silently removed when it is
inconvenient; an accepted decision invalidates or supersedes it with an audit
event.

When an edge is proposed, the application service checks both direct endpoint
ownership and the transitive closure of the graph before committing it. Both
endpoints must belong to the same mission. An edge that would make a successor
reach its own predecessor through any existing path is rejected, as is any
attempt to bridge missions directly or through a transitive chain.

### 3.5 Decision

A decision records a material choice, approval, correction, or rejection. It
is the durable bridge between Kora's recommendation and the owner's authority.

| Field | Meaning |
|---|---|
| `decision_id`, `mission_id` | Stable identity and scope. |
| `subject` | The product, technical, authority, or execution question. |
| `question` | The decision that must be answered. |
| `options` | Bounded alternatives with consequences. |
| `recommendation` | Kora's concise recommendation and rationale. |
| `consequence_of_waiting` | What remains blocked or at risk. |
| `materiality` | `safe_inference`, `material_judgment`, or `authority`. |
| `source_refs` | Evidence and context that informed the proposal. |
| `status` | `PROPOSED`, `ACCEPTED`, `REJECTED`, `WITHDRAWN`, or `SUPERSEDED`. |
| `selected_option` | Owner's chosen option, if accepted. |
| `decided_by`, `decided_at` | Explicit actor and timestamp; Kora cannot populate owner approval as itself. |
| `supersedes_decision_id` | Prior decision replaced by this one, if any. |

An accepted decision does not automatically grant broad authority. If it
approves an action, the matching permission grant and action scope still need
to be checked.

### 3.6 Assumption

An assumption captures an interpretation that Kora is using so it can remain
legible and correctable.

| Field | Meaning |
|---|---|
| `assumption_id`, `mission_id`, `task_id` | Scope and affected task. |
| `statement` | The exact assumption, written so a user can correct it. |
| `class` | `safe_inference`, `material_judgment`, or `technical_workaround`. |
| `supporting_source_refs` | Context or evidence supporting the assumption. |
| `confidence` | Low/medium/high or a bounded numeric scale. |
| `impact_if_wrong` | Product, quality, timing, cost, or authority consequence. |
| `validity_test` | How the controller or evaluator will validate it. |
| `status` | `PROPOSED`, `ACTIVE`, `VALIDATED`, `INVALIDATED`, or `SUPERSEDED`. |
| `resolution_decision_id` | Required when a material judgment is accepted or rejected. |

Only a safe reversible inference may become `ACTIVE` without an owner decision.
A material judgment stays proposed and escalates before it changes product
behavior. A technical workaround cannot silently replace a product requirement;
it must either preserve intent or become a proposed decision.

### 3.7 Checkpoint

A checkpoint is a semantic progress marker, not a log of every tool call. It
lets the controller and later product surfaces describe meaningful progress.

| Field | Meaning |
|---|---|
| `checkpoint_id`, `mission_id`, `task_id` | Scope and related work. |
| `kind` | Examples: `context_reconciled`, `plan_chosen`, `usable_slice`, `review_ready`, or `blocked`. |
| `summary` | Concise coworker-facing update. |
| `expected_evidence` | Evidence classes needed to reach it. |
| `status` | `PLANNED`, `REVIEW_REQUIRED`, `REACHED`, `FAILED`, or `SUPERSEDED`. |
| `evidence_ids` | Attached evidence/artifacts supporting the checkpoint. |
| `user_visible` | Whether a later surface may project it; it does not expose internals. |
| `reached_at` | Time of verified reach or failure. |

The controller creates checkpoints at semantic boundaries such as a first
usable slice, PRD coverage, a material ambiguity, or a ready-for-review result.

### 3.8 Escalation

An escalation is a request for a human decision, authority, access, taste, or
physical action. It should contain enough context for the smallest useful
response and should not become a generic approval queue.

| Field | Meaning |
|---|---|
| `escalation_id`, `mission_id`, `task_id` | Scope and blocked work. |
| `kind` | `ambiguity`, `judgment`, `permission`, `human_work`, `failure`, or `conflict`. |
| `question` | The exact user response needed. |
| `why_it_matters` | Mission impact and why Kora cannot safely infer it. |
| `options` | Bounded choices, if applicable. |
| `recommendation` | Kora's recommended path. |
| `consequence_of_waiting` | What remains blocked or delayed. |
| `smallest_response` | The minimum answer, artifact, access, or action that unblocks work. |
| `blocking` | Whether the critical path must wait. |
| `status` | `OPEN`, `ACKNOWLEDGED`, `RESOLVED`, `DECLINED`, `EXPIRED`, or `WITHDRAWN`. |
| `response_ref` | User answer, artifact, or decision that resolved it. |
| `contact_attempted_at` | At most one call/important follow-up marker for this issue in Portion 1's policy. |

If an important escalation is unanswered, the controller leaves the affected
task waiting and may record one attempted contact. It does not repeatedly
contact the user or create unrelated work.

### 3.9 Permission grant

A permission grant is decision authority for a bounded action. It is not a
credential and it is not the same thing as a technical capability.

| Field | Meaning |
|---|---|
| `permission_grant_id`, `mission_id` | Stable identity and mission scope. |
| `owner_ref` | User whose explicit decision controls the grant. |
| `connector_or_capability` | Semantic connector or capability, such as `workspace.write` or a deployment connector. |
| `resource_scope` | Repository, project, path, audience, or other bounded resource. |
| `action_class` | The operation permitted; never a wildcard by default. |
| `mode` | `once` or `standing`. |
| `limits` | Budget, action count, content/audience ceiling, or other mandate limit. |
| `expires_at` | Required for standing or otherwise time-bounded grants. |
| `status` | `PROPOSED`, `ACTIVE`, `CONSUMED`, `DENIED`, `EXPIRED`, or `REVOKED`. |
| `approved_by`, `approved_at` | Explicit owner approval metadata. |
| `source_decision_id` | Decision that explains the authority. |
| `revoked_at` | Revocation marker, if applicable. |
| `idempotency_key` | Action key used to prevent duplicate consequential execution. |

The controller may propose a grant. Only the owner or an explicitly delegated
authority can activate it. An `once` grant is consumed by one successful,
idempotently identified action and never promotes itself to standing authority.
A standing grant remains within its original scope and limits and can be
revoked or expire at any time.

### 3.10 Evidence/artifact

`EvidenceArtifact` is the control-plane record for both proof and deliverables.
The `kind` distinguishes them:

- **Evidence** proves a claim, such as a test report, diff, walkthrough result,
  acceptance check, or external receipt.
- **Artifact** is a result the user may inspect or use, such as a preview,
  generated file, build, or campaign draft.

| Field | Meaning |
|---|---|
| `evidence_artifact_id`, `mission_id`, `task_id`, `checkpoint_id` | Scope and semantic attachment. |
| `kind` | `evidence` or `artifact`. |
| `type` | `diff`, `test_report`, `preview`, `walkthrough`, `receipt`, `build`, or another approved type. |
| `uri` | Relative workspace/object-store reference; never an unbounded local path. |
| `sha256` | Content hash for integrity and deduplication. |
| `summary` | Concise description of what the item proves or provides. |
| `produced_by` | `runtime`, `controller`, `owner`, or `system`. |
| `verification_method` | Test command, evaluator, user review, hash check, or other method. |
| `status` | `DECLARED`, `ATTACHED`, `VERIFIED`, `REJECTED`, or `SUPERSEDED`. |
| `sensitivity` | Retention/access classification; secrets are rejected from this record. |
| `created_at`, `verified_at` | Evidence lifecycle timestamps. |

The record stores metadata and a reference; large files remain in the scoped
workspace or artifact store. Raw model traces and private reasoning are not
evidence. A completion marker may create a `DECLARED` candidate, but only an
independent check can make the item `VERIFIED`.

## 4. Lifecycle states and valid transitions

Transitions are commands guarded by the controller. A caller cannot update a
status column directly. Every successful transition writes the new projection
and an event in one database transaction.

### 4.1 Mission lifecycle

The implemented mission states are the domain enum in
[`src/kora/mission/domain.py`](../src/kora/mission/domain.py). Product labels
such as context ingestion and external-action approval are future projections,
not additional control-plane states.

| From | To | Guard |
|---|---|---|
| `PROPOSED` | `ALIGNED` | The mission contract is aligned and ready for explicit owner activation. |
| `PROPOSED` | `STOPPED` or `FAILED` | The proposed mission is stopped or cannot be formed safely. |
| `ALIGNED` | `ACTIVE` | The authoritative owner explicitly accepts the mission contract and scope. |
| `ALIGNED` | `STOPPED` or `FAILED` | The aligned mission is stopped or cannot activate safely. |
| `ACTIVE` | `WAITING_FOR_USER` | A critical-path escalation, missing authority, or runtime `NEEDS_USER` result blocks progress. |
| `ACTIVE` | `VERIFYING` | Mission-level acceptance evidence is ready for verification. |
| `ACTIVE` | `STOPPED` or `FAILED` | The owner stops the mission or recovery cannot establish safe execution. |
| `WAITING_FOR_USER` | `ACTIVE` | The owner supplies the response/artifact and all preconditions pass. |
| `WAITING_FOR_USER` | `STOPPED` or `FAILED` | The owner stops or the blocked path cannot recover safely. |
| `VERIFYING` | `ACTIVE` | Verification finds a gap and corrective work is created. |
| `VERIFYING` | `COMPLETED` | All required evidence and completion guards pass. |
| `VERIFYING` | `STOPPED` or `FAILED` | The owner stops or verification/recovery fails. |

`COMPLETED`, `STOPPED`, and `FAILED` are terminal for that mission. `WAITING`
is a compatibility alias for `WAITING_FOR_USER`; `COMPLETE` is a compatibility
alias for `COMPLETED`. A new overarching objective requires a new mission after
the completed record is preserved.

### 4.2 Task lifecycle

| From | To | Guard |
|---|---|---|
| `READY` | `IN_PROGRESS` | The controller claims the task with a leased, fenced attempt and submits a scoped runtime job. |
| `READY` | `NEEDS_USER`, `BLOCKED`, or `CANCELLED` | Authority, dependency, user, or stop guards require a different state. |
| `BLOCKED` | `READY`, `NEEDS_USER`, or `CANCELLED` | The blocker resolves, becomes a user request, or the task is cancelled. |
| `IN_PROGRESS` | `NEEDS_USER` | Runtime or mission policy requires a user response. |
| `IN_PROGRESS` | `VERIFYING` | Runtime returns a candidate result and Kora begins independent verification. |
| `IN_PROGRESS` | `FAILED` or `CANCELLED` | Runtime/recovery fails or the task is stopped. |
| `NEEDS_USER` | `READY`, `BLOCKED`, `IN_PROGRESS`, `FAILED`, or `CANCELLED` | The response is applied and preflight determines the next safe state. |
| `VERIFYING` | `IN_PROGRESS` | Verification requires corrective execution. |
| `VERIFYING` | `NEEDS_USER` | Verification needs a user decision or artifact. |
| `VERIFYING` | `COMPLETED` | Acceptance evidence is independently verified and attached. |
| `VERIFYING` | `FAILED` or `CANCELLED` | Review rejects the result or the task is stopped. |
| `FAILED` | `READY` | A bounded retry or mission-consistent corrective plan is created. |

`COMPLETED` is terminal. A failed task is not silently marked complete; the
controller either retries with evidence or escalates/pauses the mission.

### 4.3 Supporting record lifecycles

| Record | States | Valid transition summary |
|---|---|---|
| Dependency | `OPEN`, `BLOCKED`, `SATISFIED`, `INVALIDATED`, `SUPERSEDED` | `OPEN -> SATISFIED` when the predecessor condition is verified; `OPEN <-> BLOCKED` as the blocker changes; `OPEN/BLOCKED -> INVALIDATED` only through an accepted decision; any replaced edge becomes `SUPERSEDED`. |
| Decision | `PROPOSED`, `ACCEPTED`, `REJECTED`, `WITHDRAWN`, `SUPERSEDED` | `PROPOSED -> ACCEPTED/REJECTED/WITHDRAWN`; an accepted decision becomes `SUPERSEDED` only when a later accepted decision explicitly replaces it. |
| Assumption | `PROPOSED`, `ACTIVE`, `VALIDATED`, `INVALIDATED`, `SUPERSEDED` | Safe inference may move `PROPOSED -> ACTIVE`; an accepted material decision may do the same; active assumptions are validated or invalidated by evidence, and replacements are superseding records. |
| Checkpoint | `PLANNED`, `REVIEW_REQUIRED`, `REACHED`, `FAILED`, `SUPERSEDED` | `PLANNED -> REVIEW_REQUIRED` when user review is needed; `REVIEW_REQUIRED -> REACHED/FAILED`; `PLANNED -> REACHED` when objective evidence is already available; a reached or failed checkpoint is superseded only by a later corrected checkpoint. |
| Escalation | `OPEN`, `ACKNOWLEDGED`, `RESOLVED`, `DECLINED`, `EXPIRED`, `WITHDRAWN` | `OPEN -> ACKNOWLEDGED` on receipt; `ACKNOWLEDGED -> RESOLVED` when the response is applied; an owner decline, expiration, or withdrawal closes the request without pretending the work succeeded. |
| Permission grant | `PROPOSED`, `ACTIVE`, `CONSUMED`, `DENIED`, `EXPIRED`, `REVOKED` | `PROPOSED -> ACTIVE` only through explicit owner approval; `PROPOSED -> DENIED/EXPIRED`; `ACTIVE -> CONSUMED` for a successful one-time action or `ACTIVE -> EXPIRED/REVOKED` when its limit or authority ends. |
| Evidence/artifact | `DECLARED`, `ATTACHED`, `VERIFIED`, `REJECTED`, `SUPERSEDED` | `DECLARED -> ATTACHED` after the reference/hash is stored; `ATTACHED -> VERIFIED/REJECTED` through verification; rejected or old items are superseded by a new record rather than edited to look valid. |
| Task attempt | `CREATED`, `RUNNING`, `VERIFYING`, `SUCCEEDED`, `FAILED`, `INTERRUPTED`, `UNKNOWN` | A fenced lease moves an attempt into execution; runtime/recovery records the outcome; `UNKNOWN` requires reconciliation before authoritative completion. |

There is no implicit transition from a runtime response to a mission or task
completion. The controller must apply the guard for the relevant record.

### 4.4 Complete legal-transition matrix

The tables above explain the guards. The following is the complete adjacency
matrix for the Portion 1 state machines: every listed `from -> to` edge is
legal, and every unlisted edge is rejected. A record may still be superseded
by a new record where the matrix says so; that preserves history instead of
editing an old fact.

| Record | Legal transitions |
|---|---|
| Mission | `PROPOSED -> ALIGNED`, `STOPPED`, or `FAILED`; `ALIGNED -> ACTIVE`, `STOPPED`, or `FAILED`; `ACTIVE -> WAITING_FOR_USER`, `VERIFYING`, `STOPPED`, or `FAILED`; `WAITING_FOR_USER -> ACTIVE`, `STOPPED`, or `FAILED`; `VERIFYING -> ACTIVE`, `COMPLETED`, `STOPPED`, or `FAILED`. |
| Task | `READY -> IN_PROGRESS`, `NEEDS_USER`, `BLOCKED`, or `CANCELLED`; `BLOCKED -> READY`, `NEEDS_USER`, or `CANCELLED`; `IN_PROGRESS -> NEEDS_USER`, `VERIFYING`, `FAILED`, or `CANCELLED`; `NEEDS_USER -> READY`, `BLOCKED`, `IN_PROGRESS`, `FAILED`, or `CANCELLED`; `VERIFYING -> IN_PROGRESS`, `NEEDS_USER`, `COMPLETED`, `FAILED`, or `CANCELLED`; `FAILED -> READY`. |
| Task attempt | `CREATED -> RUNNING` or `INTERRUPTED`; `RUNNING -> VERIFYING`, `FAILED`, `INTERRUPTED`, or `UNKNOWN`; `VERIFYING -> SUCCEEDED`, `FAILED`, `INTERRUPTED`, or `UNKNOWN`; `UNKNOWN -> FAILED`, `INTERRUPTED`, or `VERIFYING`. |
| Dependency | `OPEN -> BLOCKED`, `SATISFIED`, `INVALIDATED`, or `SUPERSEDED`; `BLOCKED -> OPEN`, `INVALIDATED`, or `SUPERSEDED`; `SATISFIED -> SUPERSEDED`; `INVALIDATED -> SUPERSEDED`. |
| Decision | `PROPOSED -> ACCEPTED`, `REJECTED`, or `WITHDRAWN`; `ACCEPTED -> SUPERSEDED`. |
| Assumption | `PROPOSED -> ACTIVE`, `INVALIDATED`, or `SUPERSEDED`; `ACTIVE -> VALIDATED`, `INVALIDATED`, or `SUPERSEDED`; `VALIDATED -> SUPERSEDED`; `INVALIDATED -> SUPERSEDED`. |
| Checkpoint | `PLANNED -> REVIEW_REQUIRED`, `REACHED`, `FAILED`, or `SUPERSEDED`; `REVIEW_REQUIRED -> REACHED`, `FAILED`, or `SUPERSEDED`; `FAILED -> PLANNED` or `SUPERSEDED`; `REACHED -> SUPERSEDED`. |
| Escalation | `OPEN -> ACKNOWLEDGED`, `DECLINED`, `EXPIRED`, or `WITHDRAWN`; `ACKNOWLEDGED -> RESOLVED`, `DECLINED`, `EXPIRED`, or `WITHDRAWN`. |
| Permission grant | `PROPOSED -> ACTIVE`, `DENIED`, or `EXPIRED`; `ACTIVE -> CONSUMED`, `EXPIRED`, or `REVOKED`. |
| Evidence/artifact | `DECLARED -> ATTACHED`, `REJECTED`, or `SUPERSEDED`; `ATTACHED -> VERIFIED`, `REJECTED`, or `SUPERSEDED`; `VERIFIED -> SUPERSEDED`; `REJECTED -> SUPERSEDED`. |

`COMPLETED`, `STOPPED`, `CANCELLED`, `SUCCEEDED`, `ACCEPTED`, `REJECTED`, `WITHDRAWN`, `VALIDATED`,
`RESOLVED`, `DECLINED`, `EXPIRED`, `REVOKED`, and `CONSUMED` are terminal in
their respective records unless the matrix explicitly provides an outgoing
`SUPERSEDED` edge. A stale revision, wrong mission scope, or missing guard
rejects the transition even when the state edge itself is legal.

## 5. Invariants

These are system-level rules, not model instructions. A failing invariant is a
control-plane error that must stop or quarantine the affected work.

### Scope and authority

1. **At most one non-terminal mission:** historical `COMPLETED`, `STOPPED`, and
   `FAILED` missions may be retained, but only one mission may be in any
   non-terminal state at a time.
2. **Explicit activation:** no mission enters `ACTIVE` without an explicit
   owner decision accepting its contract and scope.
3. **Mission containment:** every task, dependency, decision, assumption,
   checkpoint, escalation, grant, and evidence/artifact references exactly one
   mission; dependency endpoints share that mission.
4. **Versioned mission scope:** an active mission has an immutable approved
   `scope_version`/`scope_hash`; every task binds to that version. A proposed
   amendment cannot run until an explicit decision and re-alignment create the
   next approved version.
5. **No goal invention:** neither the model, runtime, scheduler, nor a
   connector may create or replace an overarching mission. A material scope
   change requires a new decision and re-alignment.
6. **Separate capability and authority:** a task's `required_capabilities`
   must be allowed by the runtime adapter, and the action must separately pass
   the permission-grant check. One does not imply the other.
7. **No self-granting:** models, runtime results, task workers, and Kora's
   planner cannot activate, widen, or extend a permission grant.
8. **Bounded grants:** every active grant has a connector/capability, resource
   scope, action class, mode, and applicable limit/expiry. Wildcard authority is
   rejected.
9. **One-time means one-time:** a successful action consumes an `once` grant by
   idempotency key; repeated approval does not promote it to `standing`.

### Planning and execution

10. **Acyclic and same-mission graph:** a dependency insertion that creates a
    direct or transitive cycle, or connects tasks across missions, is rejected.
11. **Only ready work runs:** the scheduler may run only a `READY` task whose
    dependencies are satisfied, authority preflight passes, workspace scope is
    valid, and no blocking escalation remains.
12. **Mission-relative priority:** next-task selection must favor work that
    advances the approved objective and current critical path; it cannot use
    unrelated activity as a tie-breaker.
13. **No silent ambiguity:** an unresolved material interpretation creates an
    escalation and blocks the affected task. A technical workaround is recorded
    and must preserve intent or await a decision.
14. **Runtime boundary:** every job carries the stored `mission_id` and
    `task_id`, uses only approved toolsets/capabilities, and executes inside the
    approved cloud root. Mutating toolsets require cloud-sandbox isolation, as
    enforced by the current adapter.
15. **No direct runtime writes to authority:** Hermes can return a result or
    permission request, but cannot write SQLite mission state or grant itself
    authority.
16. **Bounded recovery:** a crashed or timed-out attempt is recoverable; leases
    and fencing prevent stale execution from creating two authoritative
    completions for the same task attempt. An unresolved outcome becomes
    `UNKNOWN` and requires reconciliation.

### Evidence and communication

17. **Evidence before completion:** task and mission completion require the
    required evidence/artifacts to be attached and independently verified.
18. **Unstructured is not complete:** `RuntimeStatus.UNSTRUCTURED`, failure,
    timeout, or refusal never advances a task to review-ready completion.
19. **Auditability:** every consequential action has a mission/task link,
    source or decision provenance, applicable permission grant, and an audit
    event.
20. **Append-only history:** decisions, approvals, denials, state transitions,
    and evidence verification outcomes remain inspectable; no hard delete or
    in-place rewrite removes history.
21. **No sensitive internals:** semantic records do not store credentials,
    private chain-of-thought, raw model prompts, worker topology, or provider
    identity. Runtime usage telemetry, if retained for operations, lives
    outside the semantic control-plane projection.
22. **Correct stop:** a user stop, unresolved critical-path escalation, missing
    authority, unsafe workspace, or scope conflict stops the affected work and
    transitions the mission to `WAITING_FOR_USER`, `STOPPED`, or `FAILED` as
    appropriate.
23. **Exact semantic authority:** every effect-bearing action matches the
    active mission, grant, action, resource scope, limits, and idempotency key;
    a capability or connector cannot fill a missing match.
24. **Private economic routing:** route reservations enforce quality,
    concurrency, and budget constraints before execution; settlement accounts
    for actual usage or bounded failure without exposing model/provider choice.
25. **Descriptor-bound workspace:** effect-bearing runtime execution and
    verification use the captured workspace descriptor and live fence, not a
    pathname that can be redirected after authorization.
26. **Bounded workspace evidence:** verification bounds and hashes tracked,
    ignored, untracked, empty-directory, and nested-`.git` state without
    following symlinks; limits are safety controls, not optional telemetry.

## 6. SQLite persistence boundary

### 6.1 What SQLite owns

The SQLite database is the source of truth for Kora's semantic control plane:

- current mission projection and immutable mission revisions;
- task graph, dependencies, leases, and task lifecycle;
- decisions, assumptions, checkpoints, and escalations;
- permission-grant proposals, approvals, limits, use, expiry, and revocation;
- evidence/artifact metadata, hashes, verification outcomes, and attachments;
- append-only audit events and schema migrations;
- opaque references to context snapshots, source documents, runtime sessions,
  workspace paths, and external receipts.

The current database uses tables corresponding to the domain records above,
including `task_attempts`, `task_dependencies`, `artifacts`, `evidence`,
`permission_uses`, and `mission_events`, plus schema metadata/migrations. These
names are Kora's semantic records; they do not create a second authority model.

The semantic schema should keep stable fields relational and use canonical JSON
only for bounded lists/maps such as options, exclusions, limits, and source
references. A useful minimum table set is:

```text
schema_migrations
missions
tasks
task_attempts
task_dependencies
decisions
assumptions
checkpoints
escalations
artifacts
evidence
permission_grants
permission_uses
mission_events
```

An audit event minimally contains `event_id`, `mission_id`, aggregate type and
ID, event type, actor, occurred-at time, aggregate revision, and a sanitized
payload containing the relevant `from_state`/`to_state`, source references,
decision references, and causation/correlation IDs. Events are insert-only;
state projections may be rebuilt from them, and no update or delete may erase a
prior approval, denial, transition, grant use, or verification outcome.

Recommended database constraints include:

- foreign keys enabled for every mission-scoped record;
- a unique partial index that allows only one non-terminal mission;
- unique task IDs and unique dependency edges;
- checks for valid enum values, positive priorities/limits, and non-empty
  mission/task objectives;
- a cycle check in the application service before a dependency transaction
  commits;
- unique idempotency keys for consequential grant uses;
- a monotonically increasing revision on each aggregate;
- no `DELETE` path for semantic or audit records.

### 6.2 What remains outside SQLite

| Data | System of record in Portion 1 | SQLite stores |
|---|---|---|
| Source code, tests, build outputs | Approved disposable workspace under the configured cloud root | Relative scope, commit/diff reference, hash, and artifact metadata. |
| Large previews and files | Workspace or a content-addressed artifact store | URI, media/type metadata, hash, and verification state. |
| Credentials and connector tokens | A future secret/connector broker; no raw secrets in the workspace fixture | Opaque credential reference and grant scope only, when needed. |
| Model prompts, chain of thought, worker traces | Ephemeral runtime or restricted operational telemetry | Sanitized result summary and relevant evidence reference only. |
| Model/provider/token telemetry | Optional operational telemetry outside the semantic projection | No user-facing semantic record; never used as mission authority. |
| Context documents | Original source store or approved snapshot | Snapshot ID, source IDs, authority decisions, freshness, and conflict references. |

Portion 1 does not create a connector broker, cloud provisioner, or Mac bridge.
The workspace path is supplied explicitly, must exist beneath the adapter's
configured `cloud_root`, and is treated as disposable cloud-sandbox state even
when the test runs locally.

### 6.3 Transaction and recovery rules

- Configure SQLite with foreign keys, WAL mode, a bounded busy timeout, and a
  durability setting appropriate for mission state. A state change should use
  one writer transaction (`BEGIN IMMEDIATE` is sufficient for the local slice)
  that updates the projection and appends its event together.
- Mutations include an expected aggregate revision. A stale writer receives a
  conflict and must reload rather than overwrite an owner response or grant.
- If any validation, state update, event insert, or grant-use insert fails
  before commit, the whole transaction rolls back: no partial projection, task
  claim, decision, permission consumption, or audit event remains.
- A task claim creates a durable attempt with a bounded lease and fencing token
  before invoking the runtime. On restart, an expired lease is recovered or
  marked unknown based on the last known result; it is not assumed complete.
  Stale fences cannot finalize work, and the same committed rows and tie-break
  order produce the same next-task selection after restart.
- For Portion 1's local/fake action fixture, an action-use record and one-time
  grant consumption commit atomically under the same SQLite transaction. A
  duplicate use key is rejected, and a failed transaction leaves the grant
  active and unused. This does not claim atomicity across a real external
  system; external outbox/idempotency and reconciliation are follow-on
  hardening.
- State snapshots/backups use SQLite's supported backup mechanism or a safe
  copy while the database is quiescent. A backup is evidence of recoverability,
  not a new authority source.
- Schema changes are versioned through `schema_migrations`; a process refuses
  to run against an unknown future schema.

### 6.4 Follow-on hardening

The accepted local slice already has durable leases, fencing, and crash
recovery. Explicit future hardening is:

- hosted/distributed multi-worker ownership, database failover, and concurrent
  writers beyond the local coordinator;
- an external-action outbox, cross-system idempotency, delivery reconciliation,
  and retry semantics;
- a credential/secret reference broker and OAuth/token lifecycle;
- an always-on daemon/scheduler and durable external timers/signals;
- selection and validation of a tagged Hermes release plus an immutable
  container digest.

None of these follow-on systems may become a second source of truth for
mission, authority, identity, evidence, memory, or routing.

## 7. Headless control loop

The loop is an application service, not a prompt. A typical iteration is:

1. Load the one current mission and verify its state, revision, exclusions,
   authority envelope, and workspace scope.
2. If the mission is waiting, stopped, completed, failed, or verifying, perform
   only the corresponding transition/checkpoint work; do not run a task.
3. Recompute dependency readiness and preflight every candidate task.
4. Choose the highest-value ready task using a stable ordering: critical path,
   mission-relative priority, dependency depth, then creation order/ID. Store
   the selection rationale as a checkpoint or event.
5. Capture the workspace identity, create a leased/fenced attempt, reserve the
   private route budget, and construct a `RuntimeJob` from the task and
   approved authority. The current contract maps `mission_id`, `task_id`,
   `objective`, `instructions`, `workspace`, `toolsets`, `skills`,
   `capabilities`, `isolation`, and `timeout_seconds`; it does not pass the
   whole database or expose internal worker data.
6. Invoke the existing Hermes adapter. Its current boundary validates the
   descriptor-bound cloud-root workspace, known toolsets, capability
   requirements, and cloud-sandbox isolation for mutating toolsets. ACP
   permission callbacks stay deny-by-default until Kora's exact authority
   resolver selects an allowed option. Fences are refreshed and checked before
   effect-bearing work and finalization.
7. Map the sanitized `RuntimeResult`:
   - `COMPLETED`: create candidate evidence and move the task to `VERIFYING`.
   - `NEEDS_USER`: create an escalation, move the task to `NEEDS_USER`, and move
     the mission to `WAITING_FOR_USER` when the path is blocked.
   - `FAILED`: record a failure event and bounded retry/escalation decision;
     never claim completion.
   - `UNSTRUCTURED`: treat as a contract failure and require retry or review;
     the text is not evidence by itself.
8. Run an independent evaluator against task acceptance criteria. Attach test
   reports, diffs, walkthroughs, or other artifacts, then mark only verified
   evidence as `VERIFIED`.
9. Settle the private route reservation with actual or bounded failure cost.
   Complete the task only after the evidence guard and fence checks pass.
   Recompute the graph, emit the next semantic checkpoint, and either continue
   or transition to waiting, stopped, failed, or completed.
10. On every iteration, persist the projection and event before reporting a
    user-facing checkpoint.

The controller should bound the number of automatic retries and loop steps in a
single invocation. A bound is a recovery and cost guard, not a mission stop
condition; preserved state lets a later invocation continue.

## 8. Proposed CLI surface

The CLI is a thin adapter over the same application service that later surfaces
will use. It must not edit SQLite directly or expose a `--force` path around
authority checks. Names are proposed and may be adjusted during implementation
without changing the underlying contracts.

### Store and mission

```text
kora control-plane init --db PATH
kora mission create --db PATH --contract PATH --workspace PATH
kora mission show MISSION_ID --db PATH [--json]
kora mission approve MISSION_ID --db PATH --by OWNER_REF
kora mission status MISSION_ID --db PATH [--json]
kora mission pause MISSION_ID --db PATH --reason TEXT
kora mission resume MISSION_ID --db PATH --by OWNER_REF
```

`mission create` creates a contract awaiting approval. `mission approve` is an
explicit owner action and validates that the contract revision has not changed.
There is no `mission activate --force` and no CLI command that changes the
objective of an active mission in place.

### Work loop and task inspection

```text
kora loop run --db PATH --mission MISSION_ID --workspace PATH [--max-steps N]
kora task list --db PATH --mission MISSION_ID [--state STATE] [--json]
kora task show TASK_ID --db PATH [--json]
kora task next --db PATH --mission MISSION_ID [--json]
kora task retry TASK_ID --db PATH --reason TEXT
```

`loop run` is the headless autonomous entry point. It may select and execute
tasks but cannot bypass approval, dependency, authority, evidence, or stop
guards. `task next` is an inspection operation; it must return a reason when no
task is ready.

### Human responses and evidence

```text
kora escalation list --db PATH --mission MISSION_ID [--json]
kora escalation respond ESCALATION_ID --db PATH --by OWNER_REF --answer TEXT
kora decision list --db PATH --mission MISSION_ID [--json]
kora evidence list --db PATH --mission MISSION_ID [--json]
kora evidence attach --db PATH --task TASK_ID --path RELATIVE_PATH --summary TEXT
kora evidence verify EVIDENCE_ID --db PATH --method TEXT
kora checkpoint list --db PATH --mission MISSION_ID [--json]
```

An escalation response creates an owner decision or user artifact reference as
needed; it does not directly set a task to complete. Evidence attachment only
accepts a path within the approved workspace or a content-addressed artifact
reference and records a hash before verification.

### Permissions and audit

```text
kora permission list --db PATH --mission MISSION_ID [--json]
kora permission approve GRANT_ID --db PATH --by OWNER_REF --mode once|standing
kora permission deny GRANT_ID --db PATH --by OWNER_REF --reason TEXT
kora permission revoke GRANT_ID --db PATH --by OWNER_REF --reason TEXT
kora audit --db PATH --mission MISSION_ID [--after EVENT_ID] [--json]
```

The `approve` command can activate only an existing, bounded proposal and must
reject a requested mode or scope that differs from that proposal. Grant use is
recorded by the controller/action broker, not by a model or a caller-supplied
status update.

Human-readable output should be concise and coworker-like. JSON output should
include semantic state, next action, blocker, evidence summary, and event IDs,
but not prompts, model/provider identity, tokens, or raw execution traces.

## 9. Proposed application/API surface

The stable contract is an application service; HTTP is a possible transport in
later phases. Portion 1 can keep it in-process behind the CLI.

| Operation | Purpose and required guard |
|---|---|
| `create_mission(contract, workspace)` | Validate contract and workspace; create `PROPOSED`. Reject if another non-terminal mission exists. |
| `approve_mission(mission_id, owner_ref, expected_revision)` | Record an explicit accepted decision and transition to `ACTIVE`. |
| `get_mission(mission_id)` | Return semantic projection, current revision, blocker, active checkpoint, and evidence summary. |
| `select_next_task(mission_id)` | Recompute dependencies/preflight and return a deterministic ready task or a reason for waiting/pausing. |
| `start_task(task_id, expected_revision)` | Claim a lease after scope, authority, capability, and dependency checks. |
| `record_runtime_result(task_id, result, attempt_ref)` | Map `RuntimeResult`, attach candidate evidence, and transition only through task guards. |
| `record_review(task_id, findings, evidence_refs)` | Independently verify or reject the candidate result. |
| `respond_to_escalation(escalation_id, owner_response)` | Record an owner decision/artifact and reopen only the affected path if guards pass. |
| `approve_permission(grant_id, owner_ref, mode)` | Activate the existing bounded proposal; never widen its scope. |
| `revoke_permission(grant_id, owner_ref)` | Revoke future use and record an audit event. |
| `attach_evidence(record)` / `verify_evidence(id, method)` | Store metadata/hash and enforce the evidence gate. |
| `pause_mission(mission_id, reason)` / `resume_mission(...)` | Honor user stop and explicit resume with safety checks. |
| `list_events(mission_id, cursor)` | Read the append-only audit stream without exposing private runtime traces. |

If exposed as HTTP later, these operations map naturally to `/v1/missions`,
`/v1/tasks`, `/v1/escalations`, `/v1/permissions`, `/v1/evidence`, and
`/v1/events`. Mutations should require an idempotency key where they may cause
an external side effect and an expected revision for optimistic concurrency.
Transport status should distinguish invalid transition, stale revision, missing
authority, blocked dependency, unsafe workspace, and unavailable runtime.

## 10. Acceptance tests

The table below is the Portion 1 target acceptance design. The current accepted
proof is narrower and is recorded by the repository tests: the empty-repository
founder-brief dogfood in `tests/test_dogfood_acceptance.py`, the 14 tests in
`tests/test_execution_boundaries_adversarial.py`, and the 12 tests in
`tests/test_execution_boundary_review_regressions.py` (27 focused tests total).
The full suite has 168 passing tests. These results validate the implemented
local control-plane slice; they do not certify every whole-product row below.
All tests use disposable or fake workspaces and do not require live deployment,
social, payment, or personal accounts.

| ID | Scenario | Acceptance condition |
|---|---|---|
| P1-AT-01 | Create then approve | A mission is created in `PROPOSED`/`ALIGNED`; only an explicit owner decision moves it to `ACTIVE`. A model/runtime response cannot do so. |
| P1-AT-02 | Single mission guard | Creating a second non-terminal mission is rejected. A completed mission remains historical and does not lose its events. |
| P1-AT-03 | Mission containment and graph safety | A task or dependency referencing another mission is rejected; a direct or transitive dependency cycle, including a cross-mission bridge, is rejected before commit. |
| P1-AT-04 | Immutable/versioned approved contract | Attempting to mutate an active objective, definition of done, exclusion, or authority envelope fails with a re-alignment requirement; the prior `scope_version`, hash, and revision remain intact. |
| P1-AT-05 | Stale-write protection | Two writers using the same expected revision cannot both commit. The stale writer receives a conflict and cannot overwrite a newer owner decision, mission scope, task state, or grant. |
| P1-AT-06 | Deterministic next task | Given ready, blocked, and unrelated tasks, the controller selects the highest-value mission-critical ready task and explains why; it never selects a blocked or unrelated task. |
| P1-AT-07 | Headless autonomous loop | After approval, `loop run` selects a task without a new prompt, submits a scoped `RuntimeJob`, changes the disposable repository, and records a semantic checkpoint. |
| P1-AT-08 | Runtime boundary | A workspace outside `cloud_root`, unknown toolset, missing capability, or mutating toolset without cloud-sandbox isolation is rejected by the adapter/control plane. |
| P1-AT-09 | Runtime status mapping | `COMPLETED` enters `VERIFYING`, `NEEDS_USER` creates a blocking escalation, `FAILED` is retryable/escalatable, and `UNSTRUCTURED` never completes the task. |
| P1-AT-10 | Ambiguous intent | A fixture with two materially different interpretations creates an escalation and leaves the task waiting; no silent product reinterpretation is committed. |
| P1-AT-11 | Capability versus authority | A task with `workspace.write` capability but no matching active grant is blocked. Read access alone cannot authorize a write. |
| P1-AT-12 | One-time and standing grants | A one-time grant authorizes exactly one local/fake action, atomically records its use, and then becomes consumed; repeated use is rejected. A standing grant remains limited to its original scope and can expire/revoke. |
| P1-AT-13 | Evidence gate | A `KORA_TASK_COMPLETE` response without a verified diff/test/acceptance artifact cannot complete a task or mission. Rejected evidence leaves the task review-failed. |
| P1-AT-14 | Independent review | An evaluator catches a deliberately failing acceptance criterion, records the finding, and returns the task to corrective work rather than accepting the runtime claim. |
| P1-AT-15 | Blocked stop | When the critical path has no ready task and an escalation is unanswered, the mission enters `WAITING_FOR_USER` or a terminal stop/failure state with a concise blocker; no unrelated task is created or run. |
| P1-AT-16 | Restart recovery and selection | Kill and restart the coordinator between lease creation and result handling. SQLite preserves mission/task/attempt state; the expired fenced attempt is recoverable or reconciled; the same committed graph and tie-break order select the same next task; a completed attempt is not duplicated. |
| P1-AT-17 | Atomic rollback and audit | Every successful state transition has its corresponding append-only event in the same transaction. A forced failure rolls back projection, inserts, grant use, and event together, leaving no half-updated state or misleading audit record. |
| P1-AT-18 | Provenance and sanitization | Decisions, assumptions, evidence, and consequential actions include source/decision references; serialized product output omits model/provider identity, prompts, private thought, and worker topology. |
| P1-AT-19 | User stop and resume | A user stop prevents new runtime work and invalidates the live fence. Explicit resume rechecks authority, workspace, dependencies, scope version, and revision before continuing. |

The end-to-end fixture should preserve a compact run artifact containing the
mission contract, owner approval, task selection, runtime result, evidence,
review finding, checkpoint history, and final stop/completion reason. That
artifact is the proof that the loop stayed aligned, not merely that a process
executed commands.

## 11. Explicit non-goals

Portion 1 intentionally does not implement or decide:

- desktop onboarding, context ingestion, context conflict UI, Kora profile,
  skill tree, or the user-facing Kanban board;
- iMessage, phone calls, daily meeting scheduling, voice, or a dedicated phone
  app;
- persistent cloud-workspace provisioning, elastic workers, or a production
  scheduler; the test workspace is supplied and disposable;
- the restricted Mac bridge or any unrestricted local shell;
- Vercel/Supabase/provider setup, production deployment, spending, public
  posting, customer outreach, or other live external actions;
- a connector marketplace, OAuth/secret broker, billing, accounts, or monthly
  allowances;
- a Codex App Server adapter; the next live-runtime adapter is explicitly
  **NOT-YET-IMPLEMENTED**. Founder dogfood/testing may use the founder's
  ChatGPT-managed Codex subscription authentication, while production must use
  company-owned API keys/provider accounts with metering, budgets, and billing;
  tokens never enter Kora durable state or public projections;
- multiple simultaneous missions, user-created company goals, or arbitrary
  user task-manager behavior such as dragging priorities;
- automatic standing permissions, inferred authority, or a `--force` escape
  hatch;
- hosted/distributed worker ownership, database failover, external-action
  outboxes and cross-system reconciliation, credential/secret references, and
  always-on scheduling; the local slice already proves leases, fencing, and
  crash recovery;
- full Context OS graph ingestion, personalized skill compilation, or reliable
  taste imitation; Portion 1 stores references and tests the authority shape;
- exposing Hermes, models, providers, prompts, subagents, tokens, worker
  topology, or raw execution traces to the user;
- replacing Hermes or rebuilding commodity runtime infrastructure;
- desktop/mobile/iMessage/voice/connectors, cloud workspace/VM fleet, external
  actions, and the full skill-tree/self-learning UX;
- changing any normative product decision in the PRD, architecture, behavior
  contract, identity, or decision ledger.

The success condition is not that Portion 1 looks like the final Kora product.
The accepted slice is the durable, inspectable mission and authority boundary
that proves one offline dogfood work cycle, intent fidelity, bounded progress,
evidence, recovery, and correct stopping. It is not whole-product release
readiness.
