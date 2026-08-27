# Hermes Harness Spike Report

## Outcome

Hermes is viable as Kora's initial execution harness, but it must remain beneath a Kora-owned mission and authority boundary.

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

## Critical finding

Hermes one-shot mode explicitly auto-bypasses its own shell and tool approvals and resolves clarification by asking the model to make a reasonable assumption. That behavior conflicts with Kora's intent-fidelity contract if it is treated as the authority layer.

The safe integration is:

1. Kora decides whether a task and capability are authorized.
2. Kora issues a narrow runtime job with only the required toolsets.
3. Hermes executes inside an isolated cloud workspace.
4. Kora validates structured evidence before changing mission state.
5. External actions remain behind Kora's separate permission broker.

One-shot is sufficient for the bootstrap spike. Hermes ACP over stdio is the preferred persistent interface because it supports sessions, events, steering, and permission callbacks without coupling Kora to private Python APIs.

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

## Next engineering slice

1. Replace the static toolset table with capability manifests discovered from the pinned runtime and reviewed into a Kora allowlist.
2. Add a Kora mission-state store and permission broker outside Hermes.
3. Execute a real read/write task against a disposable sample repository.
4. Attach diff, tests, and artifacts as completion evidence.

## Reproduce the spike

```bash
uv sync --no-editable
uv run --no-sync python -m unittest discover -s tests -v
uv run --no-sync kora-hermes-spike health
uv run --no-sync kora-hermes-spike smoke --workspace "$PWD"
uv run --no-sync kora-hermes-spike acp-smoke --workspace "$PWD"
docker build -t kora-hermes:68518c1f -f infra/hermes/Dockerfile .
docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=256m kora-hermes:68518c1f acp --check
```
