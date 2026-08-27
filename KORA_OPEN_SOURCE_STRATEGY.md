# Kora Open-Source Implementation Strategy

## Objective

Build Kora as quickly and reliably as possible by composing proven open-source systems, contributing generic improvements upstream, and reserving original engineering for the behavior that makes Kora a persistent AI coworker.

The rule is:

> Reuse commodity capabilities. Build the coworker.

Open-source reuse is an implementation strategy, not a user-facing feature. Users experience one Kora and never configure or inspect the projects, models, agents, or runtimes underneath her.

## Hermes Agent as the replaceable initial execution harness

[Hermes Agent](https://github.com/NousResearch/hermes-agent) is Kora's
replaceable initial execution harness behind `RuntimeAdapter`, not Kora's
product foundation or source of truth. Hermes supplies commodity provider/model,
tool, skill, subagent, MCP, session, and sandbox execution only.

Kora exclusively owns durable identity and relationship state, mission state and
stop conditions, context reconciliation and provenance, semantic permissions
and decision authority, evidence and evaluation, and cloud-workspace policy.
Hermes memory, scheduler, approvals, and self-improvement state are never
authoritative. Any useful runtime output must be validated and persisted by
Kora's control plane.

Hermes is currently released under the [MIT License](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE), which permits commercial use, modification, distribution, and sublicensing as long as the copyright and license notice are preserved. The license and dependency tree must be rechecked against the exact release selected for Kora.

## Runtime and authentication decision

The current Hermes path is for dogfood/testing behind Kora's adapter boundary.
The next live-runtime slice is a **NOT-YET-IMPLEMENTED Codex App Server
adapter** using the founder's ChatGPT-managed Codex subscription
authentication. Codex owns and refreshes those credentials; tokens never enter
Kora durable state or public projections. Kora may privately observe plan and
rate-limit state, but it does not expose or persist subscription tokens.

Production uses company-owned API keys and provider accounts with metering,
budgets, and billing, never a personal Codex subscription. Switching between
Hermes, Codex App Server, or another adapter must not alter Kora's durable
mission, permission, evidence, memory, or routing contracts. Hermes remains a
replaceable initial execution harness and never Kora's foundation or source of
truth.

## What to reuse from Hermes

| Hermes capability | Kora use | Integration policy |
|---|---|---|
| Provider and model execution | Run invisible model workloads. | Reuse behind `RuntimeAdapter`; Kora owns routing policy and hides provider selection. |
| Tool and agent-loop execution | Execute Kora's private work plans. | Reuse only behind the adapter; Kora supplies mission-scoped instructions and capabilities. |
| Skills execution and compatible format | Materialize private task skills. | Adopt compatible skill files where useful; Kora owns provenance, approval, hierarchy, and the public skill tree. |
| Subagents and parallel execution | Power Kora's hidden workforce. | Reuse internally; workers and models are never user-visible or authoritative. |
| Tools and MCP support | Bootstrap bounded tool execution. | Reuse protocol/tooling behind Kora's capability and authority checks. |
| Session protocol and transport | Maintain a runtime session for a Kora task. | Kora owns relationship, mission, memory, and recovery state; Hermes session state is disposable execution state. |
| Container and sandbox execution | Run work away from the user's Mac. | Reuse cloud/container primitives; Kora owns cloud-workspace policy and isolation requirements. |

Hermes may expose memory, scheduling, approval, or self-improvement features,
but Kora does not use those runtime records as product authority. Messaging,
identity, scheduling, permissions, and context continuity are Kora-owned or
remain behind a future Kora-owned adapter.

## What Kora must build

These layers should not be delegated to the harness because they constitute Kora's product and trust model:

### Persistent coworker identity

- One stable Kora across desktop, iMessage, phone, email, and cloud work.
- One authoritative owner in v1.
- Coherent personality, relationship history, and responsibility for output.

### Context and intent OS

- Broad source ingestion and context receipt.
- Typed source authority, freshness, provenance, and contradiction detection.
- Approved context snapshots.
- Intent-fidelity checks before consequential work.
- A learned operating model of the user's judgment, taste, and working style.

### Mission control

- One active overarching mission.
- Definition of done, exclusions, and evidence requirements.
- Goal-relative prioritization and strict stop conditions.
- No invention of new goals.
- Reciprocal delegation to the user.

### Authority engine

- Separation of technical access from decision authority.
- Approve-once and narrowly scoped persistent permissions.
- Bounded mandates for campaigns, budgets, and external actions.
- System-level prevention of catastrophic local actions.

### Coworker experience

- Five-to-ten-minute desktop onboarding.
- Kora profile, Markdown knowledge, and personalized skill tree.
- Semantic Kanban observability.
- Natural escalations rather than an approval queue.
- Daily Kora-initiated phone meetings.
- Mobile-friendly previews and approvals.

### Evaluation and evidence

- PRD-derived acceptance criteria.
- Requirement coverage.
- Independent adversarial review.
- Harsh self-scoring and uncertainty disclosure.
- Proof attached to semantic work items.

### Runtime selection gate

The planned pinning target is a tagged Hermes release plus an immutable
container image digest. The current exact-commit/container lock supports the
bootstrap spike; it is not a reason to couple Kora's control plane to Hermes.

OpenHands is only a gated fallback, not a co-equal current runtime choice. It
may be evaluated only if Hermes fails the concrete vertical-slice gates for
mission-scoped execution, Kora authority and stop enforcement, structured
results/evidence, and safe workspace execution through the same
`RuntimeAdapter` contract. A fallback must preserve Kora's identity, mission,
context, authority, evidence, and cloud-workspace ownership.

## Integration architecture

```text
Kora product surfaces
        |
Kora identity, context, mission, authority, and evidence control plane
        |
HermesRuntimeAdapter
        |
Hermes execution harness
        |
Provider/model, tools, skills, subagents, MCP, sessions, and sandbox execution
```

The adapter is responsible for:

- Translating Kora mission tasks into runtime jobs.
- Supplying only task-scoped context and capabilities.
- Receiving structured events and artifacts.
- Preventing the runtime from directly granting permissions or changing missions.
- Normalizing upstream failures into Kora-owned recovery behavior.
- Making runtime upgrades testable and replaceable.

## Fork and contribution policy

### Prototype phase

Use the current Hermes spike lock only to prove the vertical slice. Keep
Kora-specific logic outside the harness whenever possible.

### Product phase

- Isolate all runtime integration behind `HermesRuntimeAdapter`.
- Target a tagged Hermes release plus an immutable container image digest, with
  a reproducible lockfile and preserved license notices.
- Rebase or merge upstream deliberately rather than automatically.
- Contribute generic bug fixes, connector improvements, reliability work, and broadly useful skills upstream.
- Keep Kora's proprietary mission, intent, authority, relationship, and user-interface layers in the Kora repository.
- Avoid changing an upstream interface unless the adapter cannot solve the problem.

This captures community improvements without allowing Kora to become an unmaintainable renamed fork.

## Open-source discovery policy

Before implementing any commodity subsystem, search for established open-source options. Evaluate each candidate on:

- License compatibility and attribution requirements.
- Active maintenance and community adoption.
- Security posture and dependency hygiene.
- Test quality and documented interfaces.
- Ease of isolating it behind a Kora adapter.
- Operational reliability under unattended use.
- Whether reuse saves meaningful time without constraining Kora's product behavior.

Candidate categories include connector frameworks, browser automation, sandbox runtimes, voice transport, local indexing, encrypted sync, observability storage, OAuth brokers, and evaluation harnesses. Specific projects should be adopted only after the same license, security, and integration review used for Hermes.

## Security and supply-chain requirements

Open source accelerates Kora but also expands the attack surface. Required controls:

- Pin source releases/commits, dependency versions, and container image
  digests.
- Verify release provenance and checksums where available.
- Generate a software bill of materials.
- Maintain `THIRD_PARTY_NOTICES` with required copyright and license text.
- Scan dependencies and container images continuously.
- Run upstream code in least-privilege cloud sandboxes.
- Never allow an upstream runtime to access raw long-lived credentials directly.
- Route connector secrets through Kora's scoped credential broker.
- Keep the restricted Mac bridge outside the general agent runtime.
- Require Kora's authority engine for every consequential action, regardless of upstream approval behavior.
- Run contract, regression, and adversarial tests before upgrading the harness.

Reusing Hermes's execution primitives does not mean delegating Kora's product
state or safety boundaries. Kora may be direct and non-paternalistic while
still enforcing consent, authority, recovery, and local-device protection at
the system level.

## Build sequence

The harness spike and Kora-owned local control-plane proof are accepted for the
current work-cycle slice. The sequence below records what follows; it is not a
claim of whole-product release readiness.

### 1. Harness spike (accepted bootstrap)

- The current spike runs a bounded product-development task through
  `RuntimeAdapter` using Hermes's provider/model, tool, skill, subagent, MCP,
  session, and sandbox execution primitives.
- The result records which Kora requirements can be satisfied without
  modifying Hermes.
- The `HermesRuntimeAdapter` contract is the replaceable boundary.

### 2. Kora control plane (accepted local slice)

- Mission state, authority policy, event log, stop conditions, durable attempts,
  leases/fencing, recovery, and evidence live outside Hermes.
- The accepted dogfood proof shows that the runtime cannot change those records
  directly and that one founder brief in an empty repository becomes a verified
  functional waitlist MVP.
- Context receipt, broad context ingestion, and the user-facing product
  surfaces remain future work.

### 3. Next live-runtime adapter

- Implement the **NOT-YET-IMPLEMENTED Codex App Server adapter** behind the
  same `RuntimeAdapter` boundary for founder dogfood/testing.
- Preserve Kora's exact semantic authority, durable attempts and recovery,
  evidence gate, private workforce/model routing, and closed projections.
- Keep founder subscription authentication separate from production's
  company-owned API keys, provider accounts, metering, budgets, and billing.

### 4. Runtime hardening and fallback gate

- Select and validate a tagged Hermes release plus an immutable container image
  digest.
- Re-run the concrete vertical-slice gates after the pin is selected.
- If Hermes fails those gates, evaluate OpenHands only as a gated fallback
  behind the same adapter and Kora-owned state/authority contracts.

### 5. Personalized skills

- Ingest the user's existing Markdown instructions and workflows.
- Compile them into adapter-compatible private execution skills.
- Generate separate user-readable Kora skill documents with provenance and version history.
- Verify that a user correction changes later work without exposing runtime prompts.

### 6. Cloud continuity

- Place the pinned runtime inside Kora's persistent logical cloud workspace.
- Keep the restricted Mac bridge separate.
- Verify productive work continues while the user's Mac is offline.

### 7. Product surfaces

- Implement onboarding, Kora profile, skill tree, semantic Kanban, messages, calls, previews, and approvals over the control-plane APIs.
- Remove all runtime-specific language and configuration from the user experience.

### 8. Upstream discipline

- Identify generic changes worth contributing to Hermes.
- Maintain attribution and third-party notices.
- Automate compatibility tests against planned upstream updates.

## Acceptance criteria

The open-source strategy succeeds when:

1. Kora can complete the first mission without building a new generic agent harness.
2. Hermes is replaceable behind `RuntimeAdapter`; a runtime upgrade cannot alter Kora's identity, relationship, mission, authority, context, evidence, or cloud-workspace policy.
3. Users never encounter Hermes, model, provider, prompt, worker, or token configuration.
4. Hermes memory, scheduler, approvals, and self-improvement state are never authoritative.
5. User workflow documents become personalized Kora skills rather than being ignored.
6. Generic improvements can be contributed upstream without publishing Kora's proprietary control plane.
7. Every shipped dependency has a recorded source, version, license, and security review.
8. A tagged Hermes release and immutable container digest pass the concrete vertical-slice gates, or OpenHands passes them only after Hermes fails and only behind the same adapter contract.
9. The accepted local work-cycle proof begins with an empty-repository founder
   brief and produces a verified functional waitlist MVP without exposing
   provider, model, worker, prompt, token, or raw runtime details.
10. A transport change cannot alter Kora's durable mission, permission,
    evidence, memory, or routing contracts.
