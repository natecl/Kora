# Current Repository State

**Snapshot:** 2026-08-26  
**Repository:** `natecl/Kora`  
**Visibility:** Private

This file prevents future agents from confusing the designed Kora experience
with the code that currently exists.
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
  dependency, decision, assumption, checkpoint, escalation, artifact,
  evidence, permission-grant, and append-only audit-event records.
- Explicit mission and task transition matrices, one active overarching mission
  guard, dependency blocking, cross-mission and transitive-cycle rejection, and
  deterministic priority/creation/id next-task selection.
- Mission revision checks that reject stale writes, transaction rollback for
  failed multi-record writes, and atomic one-time permission consumption.
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
- The headless loop that reconciles mission/task state with RuntimeAdapter
  jobs, evaluates results, and records evidence for a real development mission.
- Context OS and versioned knowledge graph.
- Context ingestion, reconciliation, provenance, and conflict resolution.
- Kora identity persistence and personalized skill compilation.
- The full Kora-owned semantic authority/permission broker beyond the current
  mission permission records.
- The independent evaluation and evidence workflow for real artifacts.
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
- Always-on scheduling and proactive wakeups.
- Production authentication, billing, monthly allowances, or model routing.
- Agent-to-agent communication, external AI identity, appointments, or
  purchasing.
- Runtime hardening against a tagged Hermes release plus an immutable container
  image digest; OpenHands evaluation is permitted only as a gated fallback if
  Hermes fails the concrete vertical-slice gates.

## What Kora can do today

A developer can create and inspect Kora-owned mission records, exercise their
explicit lifecycle and dependency rules, select the deterministic next task,
and run health checks and safe runtime smoke tests. Kora can submit one
mission-scoped prompt to Hermes, constrain the requested capabilities, use a
persistent ACP session, deny permission by default, and interpret a structured
result. Hermes memory, scheduler, approvals, and self-improvement state are
never authoritative.

Kora cannot yet take a real PRD and independently run a company or produce a
complete deployed MVP. The repository is a product specification plus
validated runtime and mission-control slices; the autonomous loop and broader
product surfaces remain unimplemented.

## Recommended next engineering slice

1. Connect the persistent mission/task store to the existing `RuntimeAdapter`
   boundary and add Kora-owned authority preflight.
2. Define one disposable sample product mission and authority envelope.
3. Run the current pinned container against a writable disposable repository.
4. Have Kora choose and implement the next task, then attach diffs, tests,
   artifacts, decisions, and unresolved risks as evidence.
5. Stop or escalate on a deliberately ambiguous requirement and evaluate the
   result independently.
6. Later, validate a tagged Hermes release plus an immutable container image
   digest; consider OpenHands only if Hermes fails the concrete vertical-slice
   gates and only through the same adapter contract.

That slice should prove the core magical moment before desktop, iMessage, or
large connector work begins.
