# Hermes Harness Spike Report

## Outcome

Hermes is viable as Kora's replaceable initial execution harness, but it must
remain beneath a Kora-owned mission and authority boundary. It is commodity
execution infrastructure, not Kora's product foundation or source of truth.

The spike verified:

- Hermes Agent is available locally.
- Hermes ACP imports and health checks succeed.
- Hermes one-shot produces clean machine-readable output and usage accounting.
- Hermes ACP supports a persistent Kora-owned session and permission callback.
- A Kora adapter can restrict work by mission, workspace, toolset, capability, and isolation mode.
- Runtime model and provider details can be removed from Kora-facing results.
- Kora can require structured completion or escalation responses.
- The exact Hermes commit runs successfully in Kora's pinned, read-only container.

The live adapter smoke returned:

```json
{
  "mission_id": "kora-harness-spike",
  "task_id": "structured-smoke",
  "status": "completed",
  "response": "KORA_TASK_COMPLETE\nadapter contract verified",
  "exit_code": 0,
  "api_calls": 1,
  "total_tokens": 2733,
  "estimated_cost_usd": 0.0
}
```

No model or provider identity is present in the Kora-facing result.

The persistent ACP smoke returned the same structured completion contract. ACP
permissions are denied unless Kora's external authority layer selects an
explicit option.

This spike is now the replaceable harness beneath an accepted Kora-owned
work-cycle proof, not a whole-product release signal. The dogfood fixture starts
with an empty repository and a founder brief and produces a functional,
zero-dependency waitlist MVP. Kora owns the durable mission, attempt,
permission, evidence, lease/fence, recovery, budget settlement, and closed
public projection around that execution.

The pinned container was built from the locked Python base digest and Hermes
commit, then verified with:

```bash
docker run --rm --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=256m \
  kora-hermes:68518c1f acp --check
```

Result: `Hermes ACP check OK`.

## Upstream pin

- Repository: <https://github.com/NousResearch/hermes-agent>
- Inspected target commit: `68518c1f9bca11d9f5dbdf59ecf7e024cce057ba`
- License: MIT
- Pinned metadata: [KORA_RUNTIME_LOCK.json](./KORA_RUNTIME_LOCK.json)

The already installed local Hermes used for the initial live smoke was version
`0.20.5` at upstream revision `987064ca`. The inspected target pin is newer and
has now been installed and tested in Kora's isolated runtime image. Kora does
not depend on the developer's global Hermes installation.

This exact-commit/container lock is the bootstrap-spike pin. The planned
runtime-hardening target is a tagged Hermes release plus an immutable container
image digest; that work is separate from the Kora mission-store
implementation.

## Authority boundary

Hermes supplies commodity provider/model, tool, skill, subagent, MCP, session,
and sandbox execution only behind `RuntimeAdapter`. Kora exclusively owns
durable identity and relationship state, mission state and stop conditions,
context reconciliation and provenance, semantic permissions and decision
authority, evidence and evaluation, and cloud-workspace policy.

Hermes memory, scheduler, approvals, and self-improvement state are never
authoritative. The adapter may expose a runtime result or permission request,
but Kora validates it and persists any authoritative state in Kora-owned
records. The next live-runtime slice is a **NOT-YET-IMPLEMENTED Codex App
Server adapter**. For founder dogfood/testing it is intended to use the
founder's ChatGPT-managed Codex subscription authentication; Codex owns and
refreshes credentials, tokens never enter Kora durable state or public
projections, and Kora may privately observe plan/rate-limit state. Production
uses company-owned API keys/provider accounts with metering, budgets, and
billing, never a personal Codex subscription. The transport switch must not
alter Kora's durable mission, permission, evidence, memory, or routing
contracts.

## Critical finding

Hermes one-shot mode explicitly auto-bypasses its own shell and tool approvals and resolves clarification by asking the model to make a reasonable assumption. That behavior conflicts with Kora's intent-fidelity contract if it is treated as the authority layer.

The safe integration is:

1. Kora decides whether a task and capability are authorized.
2. Kora issues a narrow runtime job with only the required toolsets.
3. Hermes executes inside an isolated cloud workspace.
4. Kora validates structured evidence before changing mission state.
5. External actions remain behind Kora's separate permission broker.

One-shot is sufficient for the bootstrap spike. Hermes ACP over stdio is the preferred persistent interface because it supports sessions, events, steering, and permission callbacks without coupling Kora to private Python APIs.

OpenHands is not a current dependency or co-equal runtime choice. It may be
evaluated only as a gated fallback if Hermes fails the concrete vertical-slice
gates for mission-scoped execution, Kora authority/stop enforcement,
structured results/evidence, and safe workspace execution through the same
adapter contract.

## Implemented boundary

`HermesRuntimeAdapter` currently enforces:

- Workspace must live beneath Kora's configured cloud root.
- Unknown Hermes toolsets are denied.
- Every toolset maps to explicit Kora capabilities.
- Mutating toolsets require cloud-sandbox isolation.
- Jobs carry immutable mission and task identifiers.
- Runtime prompts prohibit goal broadening and unsupported authority.
- Material ambiguity has a structured `KORA_NEEDS_USER` result.
- Completion requires a structured `KORA_TASK_COMPLETE` result.
- Model and provider metadata are dropped from Kora-facing results.
- Effect-bearing execution uses a descriptor-bound workspace cwd and a live
  execution fence rather than trusting a mutable path alone.

## Next engineering slice

1. Implement the **NOT-YET-IMPLEMENTED Codex App Server adapter** behind the
   same `RuntimeAdapter` and Kora-owned contracts for founder dogfood/testing.
2. Preserve exact semantic authority, descriptor-bound cwd, fenced recovery,
   budget reservation/settlement, evidence verification, and closed public
   projections across the transport switch.
3. Validate a tagged Hermes release plus immutable image digest through live
   evaluation; evaluate OpenHands only if Hermes fails the concrete gates above.
4. Later add the always-on daemon/scheduler, cloud workspace/VM fleet,
   desktop/mobile/iMessage/voice/connectors, external actions, and the full
   skill-tree/self-learning UX.

## Reproduce the spike

```bash
uv sync --no-editable
PYTHONPATH=src uv run --no-sync python -m unittest discover -s tests -v
PYTHONPATH=src uv run --no-sync kora-hermes-spike health
PYTHONPATH=src uv run --no-sync kora-hermes-spike smoke --workspace "$PWD"
PYTHONPATH=src uv run --no-sync kora-hermes-spike acp-smoke --workspace "$PWD"
docker build -t kora-hermes:68518c1f -f infra/hermes/Dockerfile .
docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=256m kora-hermes:68518c1f acp --check
```
