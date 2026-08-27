# Kora v1 Technical Architecture

## Architectural objective

Build one persistent, cloud-resident AI coworker that can understand a founder's product context, agree on one mission, create and operate a personalized internal workforce, communicate naturally, request authority at consequential boundaries, and produce verifiable progress without requiring the user's Mac to remain online.

The architecture must make Kora feel like one coherent person while enforcing goal alignment and safety outside the model.

## System invariants

1. The user sees one Kora. Internal models and workers are never user-visible.
2. Kora may create tasks and subgoals only inside an approved overarching mission.
3. Unsupported material judgment requires conversation and agreement.
4. Technical access never implies decision authority.
5. Broad read access never implies unrestricted local execution.
6. Destructive local operations cannot be authorized solely by model output.
7. Every consequential action has provenance, permission, and an audit event.
8. Kora stops rather than inventing unrelated work when the mission is blocked.
9. Persistent memory and mission state do not depend on a single model context window.
10. Model routing, compaction, retries, and compute infrastructure remain invisible.

## High-level system

```text
Phone / iMessage / Calls        macOS Desktop App
            |                         |
            +------ Kora API --------+
                         |
              Identity + Conversation
                         |
              Mission Control Plane
              /        |          \
       Context OS   Authority OS   Work OS
           |             |            |
       Memory graph  Permission     Workforce compiler
       Source map    policy engine   Task planner/router
       Intent model  action broker   Evaluator/recovery
           \             |            /
              Persistent Cloud Workspace
                         |
           Connectors / Browser / Repos / Providers
                         |
              Restricted Mac Bridge
```

## Replaceable open-source execution harness

Kora is the product and control plane. Proven open-source projects may supply
commodity execution, but none is Kora's product foundation or source of truth.
The detailed adoption policy is in
[KORA_OPEN_SOURCE_STRATEGY.md](./KORA_OPEN_SOURCE_STRATEGY.md).

[Hermes Agent](https://github.com/NousResearch/hermes-agent), currently
published under the MIT License, is Kora's replaceable initial execution
harness behind `RuntimeAdapter`. Hermes supplies commodity provider/model,
tool, skill, subagent, MCP, session, and sandbox execution only. Kora
exclusively owns:

- durable identity and relationship state;
- mission state and stop conditions;
- context reconciliation, provenance, source authority, and conflicts;
- semantic permissions and decision authority;
- evidence, evaluation, and completion criteria;
- cloud-workspace policy, isolation, and recovery rules;
- the Kora profile, skill tree, semantic Kanban, calls, and mobile approvals.

Hermes memory, scheduler, approvals, and self-improvement state are never
authoritative. The Kora control plane communicates with Hermes only through a
versioned runtime adapter, validates runtime output, and persists authoritative
state in Kora-owned stores. Upstream model settings, agents, prompts, and tools
remain invisible to Kora users.

The planned runtime-pinning target is a tagged Hermes release plus an
immutable container image digest. The current exact-commit/container lock
supports the bootstrap spike; it does not couple the control plane to Hermes.
OpenHands is only a gated fallback: it may be evaluated through the same
adapter and ownership contract if Hermes fails concrete vertical-slice gates
for mission-scoped execution, Kora authority/stop enforcement, structured
results, and safe workspace execution.

## Major components

### 1. macOS desktop app

Responsibilities:

- Five-to-ten-minute onboarding.
- Full connector marketplace.
- Explicit operating-system permission requests.
- Local source discovery and ingestion review.
- Context-alignment receipt and contradiction resolution.
- Read-mostly Kanban observability.
- Deep conversation with Kora.
- Permission and mandate management.
- External-action audit log.
- Restricted local bridge lifecycle and health.

The desktop app is required for setup but optional during normal work.

### 2. restricted Mac bridge

The bridge provides narrowly defined capabilities rather than arbitrary remote shell access.

Initial capabilities:

- Enumerate approved filesystem metadata.
- Read files for ingestion.
- Watch approved sources for changes.
- Create versioned project snapshots.
- Synchronize explicitly scoped project changes.
- Open a local preview or artifact when requested.
- Move approved deletions to recoverable trash.

The bridge must reject:

- Recursive deletion of broad paths.
- Raw shell commands from cloud models.
- Access to unapproved secrets, cookies, or credential stores.
- Writes outside an approved project/action scope.
- Privilege escalation initiated by Kora.

### 3. persistent cloud workspace

Each Kora has one durable logical workspace containing:

- Active repository clones and branches.
- Approved knowledge snapshot and retrieval indexes.
- Generated artifacts and previews.
- Mission state.
- Decision and correction history.
- Scoped connector credential references.
- Worker execution environment.

The v1 user mental model remains one cloud computer. Parallel work may use isolated processes or containers inside the service, but no VM topology is exposed. Later, burst runners may elastically attach to the same logical workspace without changing the product model.

### 4. context OS

The context system is not a flat vector store. It maintains typed, versioned knowledge with provenance.

Core records:

- `Source`: file, connector object, conversation, decision, or artifact.
- `Claim`: normalized fact or instruction derived from a source.
- `Authority`: user-confirmed precedence and applicable scope.
- `Conflict`: incompatible claims with materiality and resolution state.
- `ContextSnapshot`: approved set of sources and resolved claims for a mission.
- `Correction`: change made by the user to Kora's interpretation or behavior.
- `Preference`: learned working or taste preference with confidence and evidence.
- `Skill`: a personalized capability Kora has compiled from user practice, instructions, corrections, and outcomes.
- `SkillDocument`: a versioned, user-readable Markdown description of how Kora performs a skill.

Required behavior:

- Detect duplicate and similarly named sources.
- Track freshness and last modification.
- Separate facts, preferences, goals, instructions, and historical artifacts.
- Detect conflicts before they influence consequential work.
- Generate a human-readable context receipt.
- Generate user-readable knowledge and context Markdown with source provenance.
- Retrieve context by task, mission, source authority, and recency.
- Preserve working context across model compaction and provider changes.

### 5. intent and role model

Kora maintains an explicit operational model of the user:

- Approved mission and definition of done.
- User-owned decisions.
- Kora-owned responsibilities.
- Quality and taste preferences.
- Communication preferences.
- Approval and escalation boundaries.
- Standing permissions and bounded mandates.
- Corrections and decision outcomes.

For every planned consequential action, Kora must be able to answer internally:

1. Which mission requirement does this advance?
2. Which sources support the interpretation?
3. Is the action safely inferred or does it require unsupported judgment?
4. Does technical permission exist?
5. Does decision authority exist?
6. What evidence will prove completion?

### 6. mission control plane

The mission controller is a durable state machine outside any individual model session.

Core states:

- `INGESTING`
- `ALIGNING_CONTEXT`
- `AWAITING_MISSION_APPROVAL`
- `ACTIVE`
- `AWAITING_USER`
- `READY_FOR_REVIEW`
- `AWAITING_EXTERNAL_ACTION_APPROVAL`
- `PAUSED`
- `COMPLETE`

The controller owns:

- The single active overarching mission.
- Definition of done and exclusions.
- Internal objectives and task dependency graph.
- Blockers and user-delegated tasks.
- Evidence requirements.
- Mission-relative prioritization.
- Stop conditions.

The controller may create new tasks inside the mission but cannot create a new overarching mission without explicit agreement.

### 7. personalized workforce compiler

The compiler converts user knowledge into Kora's private execution system.

Inputs:

- Best-practice and instruction files.
- Existing agent definitions and skills.
- Style and quality rules.
- Repository conventions.
- User corrections and past decisions.
- Mission requirements.

Outputs:

- Task-specific worker instructions.
- Tool and connector selection.
- Review rubrics.
- Escalation policies.
- Memory retrieval policy.
- Retry and fallback policy.
- Versioned, user-readable Markdown skill documents.
- A personalized skill graph with capability relationships and source provenance.

Kora does not operate the user's existing workforce directly in v1. She learns from it and creates a personalized internal workforce that she can change without exposing implementation details.

The first implementation should compile Kora's private workforce into
adapter-compatible skill, tool, subagent, and session requests wherever those
primitives fit. Kora owns scheduling, memory, mission state, and authority
state; those records must remain outside Hermes so an upstream runtime cannot
silently broaden goals or permissions. Hermes memory, scheduler, approvals, and
self-improvement state may be observed as runtime inputs, but are never
authoritative.

The compiler separates two representations:

- **Public operating representation:** concise Markdown skills, knowledge files, provenance, confidence, and version history that explain Kora's learned behavior.
- **Private execution representation:** prompts, model routes, worker topology, retries, and runtime state that remain completely hidden.

The public representation must be behaviorally faithful without leaking chain-of-thought, secrets, internal prompts, or provider implementation details.

### 7a. Kora profile and skill registry

The skill registry powers the user-facing **Kora** view in the desktop app.

Each skill record contains:

- Stable skill identifier and human-readable name.
- Parent and child relationships for the visual skill tree.
- Scope and intended outcomes.
- Versioned Markdown operating guide.
- Source documents and applicable authority order.
- Confidence and freshness.
- Required tools, knowledge, and permissions at a semantic level.
- Evidence of successful use.
- Unresolved conflicts or missing knowledge.
- Correction history and pending behavior-changing diffs.

Skill lifecycle:

1. Ingestion identifies repeated workflows, best practices, rubrics, and instructions.
2. The compiler proposes a normalized Kora skill.
3. Kora links every material behavior to its sources.
4. The user reviews the initial skill tree during context alignment.
5. Approved skills become available to mission planning.
6. Corrections and outcomes refine the skill over time.
7. Material changes appear as a diff and require user confirmation before becoming authoritative.

The tree describes Kora's competence, not her workforce implementation. A user may see **Develop the narrow MVP → Review implementation → Verify PRD coverage**, but never the workers or models used to perform those skills.

### 8. invisible model router

The router selects models based on capability, reliability, latency, context size, and cost. Users never choose or see models.

Routing policy and provider substitution are Kora-owned. Hermes supplies only
the replaceable provider/model execution layer behind the adapter; a Hermes
route, fallback, or session state cannot change Kora's mission, authority, or
identity.

Logical workloads may include:

- Always-available conversation and monitoring.
- Planning and consequential judgment.
- Coding and tool execution.
- Research and browser operation.
- Voice calls and transcription.
- Independent evaluation.

Routing policies must support automatic fallback and provider substitution. Kora should report a provider problem only if it changes timing, quality, cost, or requires help.

### 9. evaluation and evidence engine

Kora must not use the same generation pass as the sole judge of completion.

The evaluation engine produces:

- PRD-derived acceptance tests.
- Requirement-coverage maps.
- Automated test results.
- User-like end-to-end walkthroughs.
- Visual and interaction checks where applicable.
- Independent adversarial review.
- Harsh quality scores with uncertainty.
- A disclosure of degraded or incomplete requirements.

Evidence attaches to semantic Kanban cards and completion messages. Internal evaluator identities remain hidden.

### 10. authority and permission engine

The engine separately evaluates technical capability and user authority.

Permission grant fields:

- User and Kora identity.
- Connector or local capability.
- Project/resource scope.
- Action class.
- One-time or persistent duration.
- Budget or action count.
- Expiration.
- Revocation state.

Bounded mandates additionally include:

- Approved objective.
- Audience or counterparty.
- Content constraints.
- Financial ceiling.
- External-action ceiling.
- Escalation conditions.

No model can directly manufacture, widen, or persist a permission grant.

### 11. connector broker

The broker presents a large user-facing connector marketplace while normalizing services internally.

Connector classes:

- Knowledge: Drive, Notion, Obsidian, email, Slack, Codex/Claude history.
- Development: GitHub, Vercel, Supabase, Figma, issue trackers.
- Communication: iMessage, email, Slack, social networks.
- Action: deployment, browser operation, outreach, provider configuration.

Requirements:

- Read access at initial connection.
- Just-in-time elevation for write actions.
- Health checks and contract tests.
- Token refresh and reconnection handling.
- Idempotent action execution where possible.
- Fallback paths for broken connectors.
- Human-readable failure summaries.

### 12. communication gateway

The gateway supports:

- One stable Kora identity with a dedicated phone endpoint and email/inbox.
- iMessage conversations.
- Kora-initiated phone calls.
- Daily meeting transcription and memory updates.
- Mobile-friendly approval and preview links.
- Desktop conversation continuity.

All surfaces share one conversation and mission state. Users should never reconcile separate threads manually. Conversations are automatically named and grouped by mission and event.

The identity service binds Kora to one authoritative owner in v1. Messages from other people may be admitted by policy, but cannot mutate the mission, grant authority, or create commitments unless the owner has explicitly delegated that capability. Kora identifies herself transparently as an AI coworker when the distinction is relevant.

### 13. observability projection

The desktop app exposes two semantic projections rather than the internal runtime.

#### Work projection

The Kanban board is a semantic projection of mission state, not the internal task runtime.

Columns:

- Working.
- Next.
- Waiting on you.
- Ready for review.
- Done.

Visible details:

- User-facing work description.
- Mission relevance.
- Source context.
- Artifacts and evidence.
- Decisions and permissions.
- User-relevant blockers.

Hidden details:

- Model and provider names.
- Prompts and token accounting.
- Internal workers and routing.
- Chain-of-thought or raw execution traces.
- Internal retry topology.

#### Kora projection

The Kora profile shows:

- Stable identity, role, personality, and current authority boundaries.
- Visual personalized skill tree.
- Derived Markdown skill files.
- Derived knowledge and context Markdown.
- Source provenance, authority, freshness, and confidence.
- Version and correction history.
- Behavior-changing diffs awaiting confirmation.

It must not expose:

- Chain-of-thought.
- Internal prompts.
- Models or providers.
- Worker identities or topology.
- Raw private execution traces.
- Secrets embedded in source documents.

## Core execution sequence

### Onboarding to active mission

1. User describes what they are working on.
2. Desktop app obtains broad read access and connectors.
3. Local and connected sources are discovered.
4. Context OS extracts claims, authority candidates, freshness, and conflicts.
5. Kora presents the context-alignment receipt.
6. Kora presents her compiled knowledge documents and initial personalized skill tree.
7. User resolves material contradictions and confirms behavior-changing skill interpretations.
8. Kora proposes the immediate mission and definition of done.
9. User approves.
10. Mission controller enters `ACTIVE`.
11. Workforce compiler creates the private execution configuration.
12. Kora begins work in the cloud workspace.

### Consequential action

1. Kora identifies an action required by the mission.
2. Intent engine resolves supporting sources and material ambiguity.
3. Authority engine checks technical permission and decision authority separately.
4. If both exist, Kora acts and records evidence.
5. If judgment or permission is missing, Kora explains the recommendation naturally.
6. The user approves once, approves persistently within scope, corrects Kora, or declines.
7. The decision updates mission state and the user's operating model.

### Blocked work

1. Kora attempts safe retries and mission-consistent alternatives.
2. If user action is required, Kora explains the request and affected path.
3. Kora continues only non-conflicting work that directly advances the mission.
4. If no such work exists, Kora enters `AWAITING_USER` and stops execution.
5. If appropriate and unanswered, Kora calls once.
6. Work resumes from preserved state after the user responds.

## Learning loop

Kora learns tacit operating behavior from:

- Proposed decision versus actual user choice.
- User explanation or correction.
- Context that affected the choice.
- Outcome after execution.
- Later approval to reduce escalation.

Learned preferences begin as low-confidence suggestions. Kora may recommend a standing rule after repeated evidence, but the user alone approves persistent authority.

The long-term proprietary asset is the user's versioned operating model and the system that learns when to act, when to ask, and how to reproduce the user's judgment without violating consent.

## Allie Miller alignment matrix

This matrix converts the relevant parts of Allie Miller's post into explicit product commitments.

| Want from the post | Kora interpretation | v1 commitment |
|---|---|---|
| Voice-enabled everything | Kora should be reachable without typing or opening a laptop. | Daily Kora-initiated calls, voice conversation, call transcription, and mobile approvals. A true wake word is later because of OS constraints. |
| More proactive | Kora should create and execute the work required by an approved mission without repeated prompting. | Core invariant, constrained by goal alignment and authority. |
| Manage escalations rather than delegation | The user manages exceptions; Kora manages her workforce. | Core interaction model. Kora also delegates human-only work back to the user. |
| Nicely designed escalations, not boring chat | Escalations should carry context, recommendation, evidence, impact, and a clear response path while sounding human. | Natural iMessage/call conversation plus mobile preview links and desktop evidence. No formal approval-queue UI. |
| Do not keep the laptop open | Kora must continue from a persistent cloud environment. | Core v1 requirement after desktop onboarding. |
| Local Mac should not fail under AI workloads | Heavy execution should happen remotely. | Cloud workspace owns worker execution; Mac bridge is lightweight and restricted. |
| Hundreds of VMs on demand | Compute should elastically meet workload without user operations. | v1 uses one durable logical workspace with hidden parallel execution. Elastic burst runners are a later scaling implementation, never a user-facing VM product. |
| More goal-oriented | Activity should trace to an approved outcome and stop when blocked. | Mission controller, goal hierarchy, task provenance, and explicit stop rules are core. |
| Smarter routing | Different work should use the best available capability automatically. | Invisible provider/model/tool routing with fallback. |
| Never think about compaction | Kora's memory should survive context-window limits and model changes. | Externalized versioned memory, context snapshots, retrieval, and mission state are core. |
| Non-condescending emails and designs | Kora must learn and follow the user's tone and taste. | Built-in concise personality, imported style rules, correction learning, and output rubrics. |
| Avoid repetitive AI phrases and formulaic design | Kora should not leak generic model habits into user-facing work. | Style linting, negative pattern rules, user taste memory, and independent review. |
| Layered designs that feel visual rather than code-generated | Generated products must meet a user-approved visual quality bar. | Ingest design references, request taste judgment, perform visual review, and require preview approval. Full taste imitation improves over time. |
| Better conversation names | Conversations should organize themselves around work. | Automatic mission- and event-based naming; no manual thread hygiene. |
| Use cases beyond meal prep and travel | Demonstrate AI performing consequential professional work. | Initial flagship use case is taking a real product from idea/PRD to deployed MVP and outreach. |
| Reliable appointment booking | A familiar should eventually act in the real world. | Not part of the founder/developer v1; a later general-familiar capability. |
| Replies should not be six paragraphs when one line is enough | Communication should minimize attention cost. | Concision is a core communication policy; details live behind links in observability. |
| MCPs should stop breaking | Connector failures should be absorbed by the product. | Connector health, retries, idempotency, contract tests, fallback, and user-relevant failure reporting. |
| Wake word | Kora should feel immediately present from the phone. | Later platform feature. v1 uses calls, voice, and iMessage without requiring a dedicated phone app. |
| AI should score itself harshly | Kora must produce evidence and disclose uncertainty. | Independent evaluation engine, acceptance tests, adversarial review, and explicit gap reporting. |
| AI should want to make things fun | Kora should feel like a compelling coworker rather than enterprise middleware. | Built-in playful, direct personality and human conversational rhythm, without distracting from the mission. |
| More multiplayer AI | One coherent coworker should be able to coordinate many capabilities and collaborate with people. | Kora's private workforce is multiplayer internally; owner-only authoritative assignment in v1. Broader human collaboration comes later. |
| Blend one person's agent with another's | Personal AI operating models should eventually collaborate without losing identity or authority. | Later familiar-to-familiar collaboration. v1 architecture keeps identity, authority, and context portable enough to support it eventually. |

## Intentional departures from the post

- Kora does not expose hundreds of VMs; she hides infrastructure behind one persistent coworker.
- Kora does not expose model fusion, model selectors, or internal multiplayer agents.
- Kora does not begin as a general appointment or life-management assistant.
- Kora does not maximize proactivity by inventing goals. She is proactive only within user-approved intent.
- Kora does not make escalations into a bureaucratic dashboard. The supporting evidence is designed, but the interaction remains a human conversation.

## Recommended build slices

### Slice 0: intent-fidelity dogfood

- Establish a pinned Hermes runtime adapter and preserve upstream license notices.
- Ingest one real PRD, repository, and existing context folder.
- Produce context receipt and mission contract.
- Compile the user's existing instructions and workflow into a visible Markdown skill tree.
- Create internal task graph.
- Operate one existing coding-agent workflow from the cloud.
- Generate semantic Kanban state.
- Measure user corrections before writing substantial code.

### Slice 1: unattended MVP development

- Persistent cloud workspace.
- Private workforce compiler and router.
- Branch-based implementation.
- Acceptance tests and independent review.
- Natural checkpoint conversations.
- Working mobile-friendly preview.

### Slice 2: permissioned deployment

- Vercel and Supabase connectors.
- Read-versus-write capability separation.
- Approve-once and scoped persistent permissions.
- Production preview and deployment approval.
- External action log.

### Slice 3: phone-first coworker

- iMessage continuity.
- Kora-initiated daily phone call.
- Meeting transcription into mission memory.
- Mobile approvals and Kanban projections.
- Laptop-off reliability testing.

### Slice 4: approved customer outreach

- ICP and positioning research.
- Campaign artifact generation.
- Bounded outreach mandate.
- Approved X posting and outreach execution.
- Response monitoring and evidence reporting.

## Architecture acceptance tests

The v1 architecture is valid only if it can demonstrate:

1. A user completes onboarding in ten minutes or less.
2. Kora identifies duplicate or conflicting context before acting.
3. Kora begins meaningful mission work without observing a prior session.
4. Kora continues when the user's Mac is offline.
5. Kora cannot execute an unrestricted local shell command.
6. Kora cannot widen her own permission scope.
7. Kora stops when blocked rather than generating unrelated work.
8. Kora discusses material intent ambiguity before implementation.
9. Kora builds a usable preview and proves PRD coverage.
10. The user can understand Kora's current work from the Kanban board without seeing internal agents or models.
11. The user can inspect Kora's synthesized skills and knowledge, trace them to source documents, and correct them without seeing internal agents or models.
12. A confirmed correction to a Kora skill changes her next applicable execution plan without requiring the user to edit prompts or workers.
13. The user can approve a bounded external campaign without approving every action individually.
14. A daily phone meeting updates persistent mission state without manual notes.
15. The user can complete most reviews and approvals from the phone.
16. Internal provider or worker failure is absorbed unless it materially affects the user.
17. The system prevents broad destructive local actions even when requested by a model.
18. Replacing or upgrading the pinned Hermes runtime does not change Kora's mission, authority, context, or user-facing identity contracts.
