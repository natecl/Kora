# Kora

Kora is a persistent, model-agnostic AI coworker. Her first wedge is the
AI-native solo founder or developer: she takes one product mission from a
rough idea or PRD toward a deployed MVP and approved initial customer
outreach while the founder works on something else. The founder wedge is not
the product boundary; Kora's control plane is generalized for professional
roles and she is not a coding agent.

Kora owns intent fidelity, identity and relationship state, mission control and
stop conditions, context and provenance, semantic permissions and decision
authority, evidence and evaluation, and cloud-workspace policy. Hermes Agent is
the replaceable initial execution harness behind Kora's runtime adapter; it
provides invisible commodity provider/model, tool, skill, subagent, MCP,
session, and sandbox execution only.

## Current status

The accepted implementation slice is a Kora-owned work cycle, not whole-
product release readiness. At canonical code commit
`1754168ed09692ed1b5a611ad6b06a220b42543b`, the slice has a high-confidence
Sol review verdict of **ACCEPT** and passes 27 focused acceptance/regression
tests plus 168 tests in the full suite. It proves the control-plane boundary
and no P0/P1/P2 findings were identified in the implemented verified work-cycle
slice. It does not claim that the desktop, phone,
cloud, connector, external-action, or production-runtime product is ready.

The repository contains:

- The v1 product requirements and technical architecture.
- A canonical Kora context pack covering identity, founder context, behavior,
  source influences, product decisions, and current implementation state.
- Kora's open-source implementation strategy.
- A persistent, SQLite-backed Kora mission control plane with typed records,
  guarded lifecycle transitions, durable task attempts, lease/fencing and
  crash-recovery state, dependency safety, revision protection, atomic audit
  events, and one-time permission consumption.
- Exact semantic authority checks that bind each action to its mission, grant,
  action, resource, limits, and idempotency key.
- A private, profession-agnostic workforce compiler and deterministic model
  router with quality/reliability floors, expected-cost routing, bounded
  concurrency, and budget reservation/settlement. These are hidden
  operational state, not user-facing controls.
- Closed Kora-facing projections that omit provider/model identity, prompts,
  token details, worker topology, and raw runtime text.
- A capability-gated Hermes one-shot adapter.
- A persistent Hermes ACP adapter with deny-by-default permissions.
- Descriptor-bound workspace execution and verification.
- Bounded Git evidence that covers tracked changes plus ignored, untracked,
  empty-directory, and nested-`.git` state without following symlinks.
- A reproducible pinned Hermes container definition.
- Boundary tests for workspace, toolset, isolation, permission, and output
  sanitization behavior.

The current exact Hermes commit and container lock are a bootstrap/dogfood
harness, not Kora's product foundation. Hermes is replaceable behind
`RuntimeAdapter`; its memory, scheduler, approval, and self-improvement state
are never authoritative. The next live-runtime slice is a
**NOT-YET-IMPLEMENTED Codex App Server adapter** using the founder's
ChatGPT-managed Codex subscription authentication for dogfood/testing. Codex
owns and refreshes those credentials; tokens never enter Kora durable state or
public projections. Production must use company-owned API keys/provider
accounts with metering, budgets, and billing, never a personal Codex
subscription. The transport switch must not alter Kora's durable mission,
permission, evidence, memory, or routing contracts.

The planned Hermes runtime-hardening target is a tagged release plus an
immutable container image digest, followed by live evaluation. OpenHands is
only a gated fallback if Hermes fails concrete vertical-slice gates; it is not
a current stack decision.

## Development

```bash
uv sync --no-editable
PYTHONPATH=src uv run --no-sync python -m unittest discover -s tests -v
PYTHONPATH=src uv run --no-sync kora-hermes-spike health
PYTHONPATH=src uv run --no-sync kora-hermes-spike acp-smoke --workspace "$PWD"
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

The next live-runtime slice is the Codex App Server adapter described above.
After that, the approved sequence productizes desktop/context UI,
cloud/phone continuity, and finally deployment/outreach. See the [Portion 1
roadmap](./docs/PORTION_1_ROADMAP.md) and the [mission control-plane
design](./docs/PORTION_1_MISSION_CONTROL_PLANE.md) for the current scope and
acceptance boundary.

Explicit future gaps are: the Codex App Server adapter; tagged/pinned Hermes
plus immutable-image live evaluation; an always-on daemon/scheduler; a cloud
workspace/VM fleet; desktop/mobile/iMessage/voice/connectors; external
actions; and the full skill-tree/self-learning UX.
