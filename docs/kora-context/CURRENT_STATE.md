# Current Repository State

**Snapshot:** 2026-08-27

**Canonical code commit:** `1754168ed09692ed1b5a611ad6b06a220b42543b`

**Review verdict:** Sol High **ACCEPT** (accepted slice review, not whole-product release certification)

**Repository:** `natecl/Kora`  
**Visibility:** Private

This file prevents future agents from confusing the designed Kora experience
with the code that currently exists. The accepted implementation is a bounded
Kora-owned work cycle, not whole-product release readiness. The repository
passes 27 focused acceptance/regression tests and 168 tests in the full suite;
no P0/P1/P2 findings were identified in the implemented verified work-cycle
slice.
The accepted but staged technology target is
[`../KORA_TECHNOLOGY_STACK.md`](../KORA_TECHNOLOGY_STACK.md); selected target
services are not evidence that those components are implemented.

## Implemented

- Kora runtime job and result contracts.
- Explicit capability declarations.
- Read-only and cloud-sandbox isolation modes.
- Workspace boundary enforcement.
- Approved Hermes toolset mapping.
- Rejection of mutating toolsets outside cloud-sandbox mode.
- A Hermes one-shot adapter for bootstrap testing.
- A persistent Hermes ACP adapter.
- Deny-by-default ACP permission handling.
- Sanitized product-facing results that omit model and provider identity.
- Structured completion, escalation, failure, and unstructured-result states.
- A Kora-owned SQLite mission store and service with typed mission, task,
  dependency, task-attempt, decision, assumption, checkpoint, escalation,
  artifact, evidence, permission-grant/use, and append-only audit-event records.
- Explicit mission and task transition matrices, one active overarching mission
  guard, dependency blocking, cross-mission and transitive-cycle rejection, and
  deterministic priority/creation/id next-task selection.
- Mission revision checks that reject stale writes, transaction rollback for
  failed multi-record writes, and atomic one-time permission consumption.
- Durable attempt leases, fencing tokens, stop invalidation, unknown-outcome
  recovery, and atomic verified finalization.
- Exact semantic authority checks that bind mission, grant, action, resource,
  limits, and idempotency key; capabilities and connector access alone do not
  authorize an action.
- A private generalized workforce compiler and deterministic model router with
  quality/reliability floors, expected-cost routing, bounded concurrency, and
  budget reservation/settlement. Route/provider/model details are not public
  semantic state.
- Closed Kora-facing result and artifact projections that omit provider/model
  identity, prompts, tokens, worker topology, and raw runtime text.
- Descriptor-bound workspace cwd execution and an independent bounded verifier
  covering tracked, ignored, untracked, empty-directory, and nested-`.git`
  evidence without following symlinks.
- Mission-control tests covering persistence, lifecycle, dependency, revision,
  rollback, audit, and permission boundaries, in addition to the runtime
  boundary tests.
- Developer CLI commands for `mission-create` and `mission-status` alongside
  the runtime health and smoke commands.
- A pinned Hermes container definition.
- A locked Hermes commit, Python base-image digest, uv version, and license
  record.
- A successful Hermes ACP health check inside a read-only container with
  ephemeral runtime state.

The mission package intentionally has no dependency on Hermes. Kora's mission,
authority, evidence, and stop state remain authoritative even when the runtime
harness is replaced.

## Configured locally, not owned by Kora

The active developer Hermes installation currently resolves to:

- model: `gpt-5.6-sol`;
- provider: `openai-codex`;
- reasoning effort: `xhigh`;
- fallback providers: none.

This is a developer-machine configuration, not Kora's permanent brain or
product policy. The pinned Kora container contains no baked-in inference
credentials and no mandatory foundation model. Production Kora is intended to
route models invisibly at runtime.

## Documented but not implemented

- The accepted staged technology-stack target and its hosted beta services;
  see [`../KORA_TECHNOLOGY_STACK.md`](../KORA_TECHNOLOGY_STACK.md).
- The next live-runtime **Codex App Server adapter**. It is explicitly
  NOT-YET-IMPLEMENTED. Founder dogfood/testing is intended to use the founder's
  ChatGPT-managed Codex subscription authentication; Codex owns and refreshes
  credentials, tokens never enter Kora durable state or public projections,
  and Kora may privately observe plan/rate-limit state.
- Context OS and versioned knowledge graph.
- Context ingestion, reconciliation, provenance, and conflict resolution.
- Kora identity persistence and personalized skill compilation.
- The full product-facing context, identity, and authority UX beyond the
  current verified local records and fixtures.
- Persistent cloud workspace provisioning.
- Elastic worker or VM orchestration.
- Restricted Mac bridge.
- Desktop onboarding.
- Connector marketplace.
- Kanban observability UI.
- User-visible Kora profile, skills, and Markdown knowledge editor.
- iMessage communication.
- Phone calls and daily meetings.
- Voice and wake-word interaction.
- Deployment, provider setup, and customer-outreach workflows.
- Always-on daemon/scheduler and proactive wakeups.
- Production authentication, billing, monthly allowances, or hosted routing.
- Agent-to-agent communication, external AI identity, appointments, or
  purchasing.
- Runtime hardening against a tagged Hermes release plus an immutable container
  image digest; OpenHands evaluation is permitted only as a gated fallback if
  Hermes fails the concrete vertical-slice gates.
- Desktop/mobile/iMessage/voice/connectors, external actions, and the full
  skill-tree/self-learning UX.

## What Kora can do today

A developer can create and inspect Kora-owned mission records, exercise their
explicit lifecycle and dependency rules, select the deterministic next task,
and run health checks and safe runtime smoke tests. The accepted dogfood test
also runs an empty-repository founder brief through a deterministic adapter to
produce a functional, zero-dependency waitlist MVP, verifies the workspace and
evidence, and finalizes the mission. Kora can constrain capabilities, enforce
exact authority, reserve/settle a private route, use descriptor-bound execution,
recover fenced attempts, deny ACP permission by default, and emit a closed
semantic result. Hermes memory, scheduler, approvals, and self-improvement
state are never authoritative.

Kora cannot yet take an arbitrary real PRD through deployment and approved
outreach, provide the desktop/phone/cloud/connector product, perform external
actions, or run an always-on production runtime. Production must use
company-owned API keys/provider accounts with metering, budgets, and billing,
never a personal Codex subscription.

## Recommended next engineering slice

1. Implement the **NOT-YET-IMPLEMENTED Codex App Server adapter** behind the
   existing `RuntimeAdapter` and preserve the accepted Kora contracts.
2. For founder dogfood/testing, use the founder's ChatGPT-managed Codex
   subscription authentication with Codex-owned credential refresh; never put
   tokens in Kora durable state or public projections.
3. Keep production authentication on company-owned API keys/provider accounts
   with metering, budgets, and billing, never a personal Codex subscription.
4. Later validate a tagged Hermes release plus an immutable container image
   digest; consider OpenHands only if Hermes fails the concrete vertical-slice
   gates and only through the same adapter contract.
5. Productize the desktop, mobile/iMessage/voice, cloud workspace/VM fleet,
   connectors, external actions, always-on scheduling, and full skill-tree/
   self-learning UX.

The accepted dogfood slice proves the core control-plane boundary; the work
above is required before the complete Kora experience is ready.
