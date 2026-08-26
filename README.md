# Kora

Kora is a persistent, model-agnostic AI coworker for AI-native solo founders
and developers. She takes one product mission from a rough idea or PRD to a
deployed MVP and approved initial customer outreach while the founder works on
something else.

Kora owns intent fidelity, mission control, authority, memory, evidence, and
the coworker relationship. Proven open-source runtimes such as Hermes Agent
provide invisible model, tool, skill, and worker infrastructure underneath.

## Current status

The repository contains:

- The v1 product requirements and technical architecture.
- Kora's open-source implementation strategy.
- A capability-gated Hermes one-shot adapter.
- A persistent Hermes ACP adapter with deny-by-default permissions.
- A reproducible pinned Hermes container definition.
- Boundary tests for workspace, toolset, isolation, permission, and output
  sanitization behavior.

## Development

```bash
uv sync --no-editable
uv run --no-sync python -m unittest discover -s tests -v
uv run --no-sync kora-hermes-spike health
uv run --no-sync kora-hermes-spike acp-smoke --workspace "$PWD"
```

Start with [KORA_V1_PRD.md](./KORA_V1_PRD.md) and
[KORA_TECHNICAL_ARCHITECTURE.md](./KORA_TECHNICAL_ARCHITECTURE.md).
