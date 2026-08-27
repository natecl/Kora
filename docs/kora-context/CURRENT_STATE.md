# Current Repository State

**Snapshot:** 2026-08-26  
**Repository:** `natecl/Kora`  
**Visibility:** Private

This file prevents future agents from confusing the designed Kora experience
with the code that currently exists.

## Implemented

- Kora runtime job and result contracts.
- Mission and task identifiers.
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
- Eight tests covering core runtime and permission boundaries.
- A pinned Hermes container definition.
- A locked Hermes commit, Python base-image digest, uv version, and license
  record.
- A successful Hermes ACP health check inside a read-only container with
  ephemeral runtime state.

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

- Persistent mission state and next-task planning.
- Context OS and versioned knowledge graph.
- Context ingestion, reconciliation, provenance, and conflict resolution.
- Kora identity persistence and personalized skill compilation.
- Authority and permission broker outside Hermes.
- Evaluation and evidence engine.
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

## What Kora can do today

A developer can run health checks and safe runtime smoke tests. Kora can submit
one mission-scoped prompt to Hermes, constrain the requested capabilities, use
a persistent ACP session, deny permission by default, and interpret a
structured result.

Kora cannot yet take a real PRD and independently run a company or produce a
complete deployed MVP. The repository is a product specification plus a
validated execution-boundary spike.

## Recommended next engineering slice

1. Add a persistent mission-state store.
2. Add a Kora-owned semantic permission broker.
3. Define one disposable sample product mission and authority envelope.
4. Run the pinned container against a writable disposable repository.
5. Have Kora choose and implement the next task.
6. Attach diff, tests, artifacts, decisions, and unresolved risks as evidence.
7. Stop or escalate on a deliberately ambiguous requirement.

That slice should prove the core magical moment before desktop, iMessage, or
large connector work begins.
