# Kora

Kora is a persistent, model-agnostic AI coworker for AI-native solo founders
and developers. She takes one product mission from a rough idea or PRD to a
deployed MVP and approved initial customer outreach while the founder works on
something else.

Kora owns intent fidelity, identity and relationship state, mission control and
stop conditions, context and provenance, semantic permissions and decision
authority, evidence and evaluation, and cloud-workspace policy. Hermes Agent is
the replaceable initial execution harness behind Kora's runtime adapter; it
provides invisible commodity provider/model, tool, skill, subagent, MCP,
session, and sandbox execution only.

## Current status

The repository contains:

- The v1 product requirements and technical architecture.
- A canonical Kora context pack covering identity, founder context, behavior,
  source influences, product decisions, and current implementation state.
- Kora's open-source implementation strategy.
- A persistent, SQLite-backed Kora mission control plane with typed records,
  guarded lifecycle transitions, dependency safety, revision protection,
  atomic audit events, and one-time permission consumption.
- A capability-gated Hermes one-shot adapter.
- A persistent Hermes ACP adapter with deny-by-default permissions.
- A reproducible pinned Hermes container definition.
- Boundary tests for workspace, toolset, isolation, permission, and output
  sanitization behavior.

The current exact Hermes commit and container lock are a bootstrap spike, not
Kora's product foundation. The planned runtime-hardening target is a tagged
Hermes release plus an immutable container image digest. OpenHands is only a
gated fallback if Hermes fails concrete vertical-slice gates; it is not a
current stack decision.

## Development

```bash
uv sync --no-editable
uv run --no-sync python -m unittest discover -s tests -v
uv run --no-sync kora-hermes-spike health
uv run --no-sync kora-hermes-spike acp-smoke --workspace "$PWD"
```

## Canonical context

Start with the [Kora Context Pack](./docs/kora-context/README.md). It defines
the source hierarchy and links Kora's identity, behavior contract, founder
context, conversation synthesis, decision ledger, source context, and honest
implementation snapshot.

The normative product and system specifications remain
[KORA_V1_PRD.md](./KORA_V1_PRD.md) and
[KORA_TECHNICAL_ARCHITECTURE.md](./KORA_TECHNICAL_ARCHITECTURE.md).
The accepted, staged technology-stack decision is
[docs/KORA_TECHNOLOGY_STACK.md](./docs/KORA_TECHNOLOGY_STACK.md); it records
target choices and migration gates without implying that deferred components
are implemented.

## Next engineering slice

The approved sequence starts by proving a headless autonomous development loop,
then productizes desktop/context UI, cloud/phone continuity, and finally
deployment/outreach. See the [Portion 1 roadmap](./docs/PORTION_1_ROADMAP.md)
and the [mission control-plane design](./docs/PORTION_1_MISSION_CONTROL_PLANE.md)
for the current scope and acceptance boundary.
