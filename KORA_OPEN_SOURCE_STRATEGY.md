# Kora Open-Source Implementation Strategy

## Objective

Build Kora as quickly and reliably as possible by composing proven open-source systems, contributing generic improvements upstream, and reserving original engineering for the behavior that makes Kora a persistent AI coworker.

The rule is:

> Reuse commodity capabilities. Build the coworker.

Open-source reuse is an implementation strategy, not a user-facing feature. Users experience one Kora and never configure or inspect the projects, models, agents, or runtimes underneath her.

## Hermes Agent as the initial harness

[Hermes Agent](https://github.com/NousResearch/hermes-agent) is the preferred initial foundation. Its current official repository describes:

- A model-agnostic provider layer.
- A closed learning loop that creates and improves skills.
- Persistent memory, user modeling, and session search.
- Context files and compatible agent skills.
- Messaging gateways and cross-platform conversation continuity.
- Scheduled unattended automation.
- Parallel subagent delegation.
- Tools and MCP integration.
- Local, container, SSH, Modal, Daytona, and Vercel Sandbox execution backends.
- Command approval and container-isolation foundations.

Hermes is currently released under the [MIT License](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE), which permits commercial use, modification, distribution, and sublicensing as long as the copyright and license notice are preserved. The license and dependency tree must be rechecked against the exact pinned commit before each release.

## What to reuse from Hermes

| Hermes capability | Kora use | Integration policy |
|---|---|---|
| Agent loop and tool execution | Execute Kora's private work plans. | Reuse behind `HermesRuntimeAdapter`; do not expose its loop to users. |
| Provider and model abstraction | Route different workloads invisibly. | Reuse adapters; Kora owns routing policy and hides provider selection. |
| Skills system | Materialize Kora's compiled personalized skills. | Adopt compatible skill files where useful; Kora owns provenance, approval, hierarchy, and the public skill tree. |
| Persistent memory and session search | Bootstrap recall and cross-session retrieval. | Reuse storage/search primitives; Kora owns typed source authority, conflicts, mission snapshots, and correction history. |
| User modeling foundations | Seed Kora's learned operating model. | Reuse selectively; Kora owns the decision-learning and authority semantics. |
| Messaging gateway | Bootstrap text continuity and delivery. | Reuse transport adapters; Kora owns iMessage/contact identity, message style, mobile approvals, and conversation state. |
| Cron and scheduled automation | Daily calls, monitoring, and proactive mission work. | Reuse scheduler; Kora's mission controller determines whether scheduled work is authorized. |
| Subagents and parallel work | Power Kora's private workforce. | Reuse internally; workers and models are never user-visible. |
| Tools and MCP support | Bootstrap integrations and tool execution. | Reuse protocol/tooling; wrap with connector health, scoped permissions, and action audit. |
| Terminal and sandbox backends | Run work away from the user's Mac. | Reuse cloud/container backends; Kora presents one persistent logical workspace. |
| Approval and isolation foundations | Accelerate execution safety. | Reuse primitives only; Kora's external authority engine remains the final policy boundary. |
| Self-improving skill loop | Learn procedural improvements from experience. | Reuse mechanisms; Kora requires provenance, versioning, and confirmation for material behavior changes. |

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

## Integration architecture

```text
Kora product surfaces
        |
Kora identity, context, mission, authority, and evidence control plane
        |
HermesRuntimeAdapter
        |
Pinned Hermes runtime
        |
Providers, tools, skills, subagents, gateways, schedulers, and sandboxes
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

Use a pinned internal Hermes fork if that is the fastest path to the first end-to-end demonstration. Keep Kora-specific logic outside the fork whenever possible.

### Product phase

- Isolate all runtime integration behind `HermesRuntimeAdapter`.
- Track the exact upstream commit and maintain a reproducible lockfile.
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

- Pin source commits and dependency versions.
- Verify release provenance and checksums where available.
- Generate a software bill of materials.
- Maintain `THIRD_PARTY_NOTICES` with required copyright and license text.
- Scan dependencies and container images continuously.
- Run upstream code in least-privilege cloud sandboxes.
- Never allow an upstream runtime to access raw long-lived credentials directly.
- Route connector secrets through Kora's scoped credential broker.
- Keep the restricted Mac bridge outside the general agent runtime.
- Require Kora's authority engine for every consequential action, regardless of upstream approval behavior.
- Run contract, regression, and adversarial tests before upgrading upstream commits.

Reusing Hermes's autonomy or self-learning mechanisms does not mean removing Kora's safety boundaries. Kora may be direct and non-paternalistic while still enforcing consent, authority, recovery, and local-device protection at the system level.

## Build sequence

### 1. Harness spike

- Pin a Hermes commit.
- Run one product-development task using its provider, tools, skills, memory, and subagent primitives.
- Record which Kora requirements can be satisfied without modifying Hermes.
- Create the first `HermesRuntimeAdapter` contract.

### 2. Kora control plane

- Add context receipt, mission state, authority policy, event log, and stop conditions outside Hermes.
- Prove the runtime cannot change these records directly.
- Translate one mission task into a Hermes job and collect structured evidence.

### 3. Personalized skills

- Ingest the user's existing Markdown instructions and workflows.
- Compile them into Hermes-compatible private execution skills.
- Generate separate user-readable Kora skill documents with provenance and version history.
- Verify that a user correction changes later work without exposing runtime prompts.

### 4. Cloud continuity

- Place the pinned runtime inside Kora's persistent logical cloud workspace.
- Keep the restricted Mac bridge separate.
- Verify productive work continues while the user's Mac is offline.

### 5. Product surfaces

- Implement onboarding, Kora profile, skill tree, semantic Kanban, messages, calls, previews, and approvals over the control-plane APIs.
- Remove all runtime-specific language and configuration from the user experience.

### 6. Upstream discipline

- Identify generic changes worth contributing to Hermes.
- Maintain attribution and third-party notices.
- Automate compatibility tests against planned upstream updates.

## Acceptance criteria

The open-source strategy succeeds when:

1. Kora can complete the first mission without building a new generic agent harness.
2. A Hermes runtime upgrade cannot alter Kora's mission or permission state.
3. Users never encounter Hermes, model, provider, prompt, worker, or token configuration.
4. Kora can replace the underlying runtime without losing identity, memory, mission, permissions, or skill provenance.
5. User workflow documents become personalized Kora skills rather than being ignored.
6. Generic improvements can be contributed upstream without publishing Kora's proprietary control plane.
7. Every shipped dependency has a recorded source, version, license, and security review.
