# Kora v1 Product Requirements Document

## Product thesis

Kora is a persistent, model-agnostic AI coworker for AI-native solo founders and developers. She takes one product mission from a rough idea or existing PRD to a deployed, usable MVP and an approved initial customer-outreach campaign.

The founder should be able to close their laptop and work on something else. Kora keeps the product moving at approximately the founder's quality, communicates like a capable human coworker, and involves the founder only when their judgment, authority, access, taste, or physical action is genuinely required.

Kora is the product. Models, subagents, routing, prompts, tokens, VMs, and internal workflows remain invisible.

## Positioning

### Category

Persistent AI coworker / AI familiar.

### Initial promise

> Give Kora a product mission. She develops the narrow MVP, deploys it with your approval, and begins approved customer outreach while you work on something else.

### Useful shorthand

- Codex does work. Kora keeps the work moving toward the right outcome.
- You do not operate Kora. You talk to her.
- Every AI company gives you a dashboard. Kora gives you a coworker.
- Kora replaces the steering required to run an AI workforce.

## Initial customer

The first customer is an AI-native solo founder or developer who:

- Already uses coding agents such as Codex or Claude.
- Builds real products rather than isolated demos.
- Maintains PRDs, context files, skills, rules, or agent instructions.
- Repeatedly explains intent, delegates work, reviews output, restarts agents, and keeps work aligned.
- Values saved founder attention more than a low software price.
- Is comfortable granting a trusted product broad read access and scoped action authority.

Kora is not initially for teams that require procurement, enterprise governance, or extensive human management.

## Primary job to be done

> When I have a product idea or PRD, move it toward a usable, deployed MVP and initial customers at roughly my quality, without requiring me to continuously prompt, delegate, monitor, or keep my laptop open.

## First complete mission

The v1 mission is:

> Turn a rough product idea or existing PRD into a narrowly scoped, functional, deployed MVP, then prepare and execute an explicitly approved initial customer-outreach campaign.

Kora supports one active overarching mission at a time. A mission may contain many objectives, tasks, workers, decisions, and phases. Kora may create and prioritize those internal tasks, but she may not create or adopt a new overarching goal.

## Product principles

### 1. Goal aligned, not merely busy

Kora works only toward the current approved mission. If the remaining work is blocked and no other task directly advances that mission, she stops. She does not add features, optimize unrelated systems, or invent growth projects to appear productive.

### 2. Low founder effort, not low communication

Kora communicates checkpoints, evidence, decisions, ambiguity, and blockers like a human coworker. The goal is to reduce steering labor, not message count.

### 3. Initiative without an independent agenda

Kora may proactively determine and perform the work required by the approved mission. The user owns what to pursue and why. Kora owns how to move it forward effectively.

### 4. Intent fidelity over apparent autonomy

Kora must surface material ambiguity rather than silently choose an interpretation. If two plausible interpretations would produce meaningfully different outcomes, she discusses them, recommends one, and waits for agreement.

### 5. Broad context, scoped action

Kora may broadly discover and ingest user-approved computer context and connected services. Reading context does not grant authority to modify files, spend money, communicate externally, publish content, or take destructive action.

### 6. One visible coworker

Kora may create and coordinate a personalized internal workforce, but the user never sees individual models, agents, prompts, routing, token usage, or internal traces. Kora owns the result.

### 7. Consent at consequential boundaries

Spending, public identity, outreach, external commitments, important taste decisions, production changes, and destructive actions require approval unless the user has granted a sufficiently specific standing permission.

### 8. Natural interaction over workflow configuration

Internal checkpoints, state machines, routing, evaluation, and retries stay hidden. The user experiences conversations, calls, previews, decisions, and results.

### 9. Open-source first

Kora should reuse, wrap, and contribute to proven open-source infrastructure wherever that infrastructure is not the product's differentiation. The team should not rebuild model adapters, agent loops, tool systems, skills formats, memory search, messaging gateways, schedulers, sandbox backends, or generic connector plumbing when mature implementations can be safely adopted.

Such projects may provide implementation primitives only; their runtime state
cannot become Kora's source of truth. Kora's own contracts and stores govern
memory/context, scheduling, messaging, permissions, evidence, and mission
control even when an open-source component supplies a transport or execution
primitive.

[Hermes Agent](https://github.com/NousResearch/hermes-agent) is Kora's replaceable initial execution harness behind `RuntimeAdapter`, not Kora's product foundation or source of truth. Hermes supplies commodity provider/model, tool, skill, subagent, MCP, session, and sandbox execution only. Kora exclusively owns durable identity and relationship state, mission state and stop conditions, context reconciliation and provenance, semantic permissions and decision authority, evidence and evaluation, and cloud-workspace policy. Hermes memory, scheduler, approvals, and self-improvement state are never authoritative; any useful runtime output must be validated and persisted by Kora.

Kora's proprietary work should concentrate on the persistent coworker experience: intent fidelity, context reconciliation, the user operating model, mission control, reciprocal delegation, authority, evidence, cloud continuity, the Kora profile and skill tree, and phone-first interaction.

The planned runtime-pinning target is a tagged Hermes release plus an immutable container image digest. The current exact-commit/container lock supports the bootstrap spike and is not a reason to couple Kora's control plane to Hermes. OpenHands is not a co-equal runtime choice or current dependency; it may be evaluated only as a gated fallback if Hermes fails the concrete vertical-slice gates for mission-scoped execution, Kora authority/stop enforcement, structured results, and safe workspace execution through the same adapter contract.

Open-source-first does not mean bypassing safety, blindly inheriting upstream behavior, or exposing implementation complexity. Every dependency remains pinned, reviewed, isolated behind an adapter, attributed according to its license, and subject to Kora's own permission and safety boundaries.

## Core experience

### Desktop onboarding

Onboarding occurs entirely in the macOS desktop app and should require five to ten minutes of human attention.

1. Kora asks: **What are you working on?**
2. The user describes the product naturally.
3. The app requests broad computer read access.
4. The app presents a large connector marketplace so the user can rapidly connect relevant accounts.
5. Kora discovers repositories, PRDs, context files, memory files, knowledge documents, agent instructions, best practices, and working history.
6. Kora creates a structured context synthesis and compiles the user's workflows and best practices into personalized Kora skills.
7. The user reviews included sources, exclusions, contradictions, stale information, missing access, Kora's proposed source-of-truth hierarchy, and the initial Kora skill tree.
8. Material contradictions are resolved through a short desktop conversation.
9. Kora proposes the immediate objective, her role, the definition of done, exclusions, and approval boundaries.
10. The user approves, and Kora begins meaningful work immediately.

Kora does not ask the user to define an AI role, construct a workflow, choose a model, configure agents, or select an orchestration strategy.

### Context-alignment receipt

After ingestion, Kora must show:

- Her concise understanding of the product, user, problem, mission, and success condition.
- Every included source, grouped by purpose.
- Excluded sources and the reason for exclusion.
- Duplicates and similarly named files.
- Contradictions and potentially stale information.
- Missing or inaccessible sources.
- Her proposed authority order among conflicting sources.

Kora recommends which source should be authoritative when documents conflict materially, but waits for the user's confirmation. The approved result becomes a versioned context snapshot.

### Kora profile and skill tree

Kora has an inspectable operating identity. The desktop app includes a **Kora** area that helps the user understand who she is, what she knows, what she can do, and how she currently performs the work.

It contains:

- A concise **Kora at a glance** summary of who she is for this user, her current strengths, responsibilities, mission, and limitations.
- Kora's role, personality, current mission, and authority boundaries.
- A visual skill tree organized by capability, such as product discovery, product definition, implementation, review, deployment, and outreach.
- User-readable Markdown skill files describing how Kora performs each capability.
- User-readable Markdown knowledge and context files representing Kora's approved understanding of the user and product.
- The user sources from which every derived skill or knowledge file was compiled.
- Confidence, freshness, last update, and unresolved conflicts for each skill or knowledge area.
- A version history showing how Kora changed after user corrections and new evidence.

The skill tree is not a generic catalog or a display of Kora's internal agents. It is a personalized map of Kora's learned competence. If the user already has a preferred development workflow, design rubric, review process, or outreach method, Kora converts it into her own internal skill rather than ignoring it or forcing the user to operate the old workflow manually.

For example, Kora may compile the user's PRD conventions, coding-agent instructions, review checklist, design references, and prior corrections into a skill named **Develop the narrow MVP**. Opening that skill shows a concise Markdown operating guide, its source documents, its current assumptions, and what Kora still needs to learn.

Raw user documents remain intact. Kora's Markdown files are derived, versioned operating documents with links back to their sources. The user may correct Kora through conversation or propose an edit. Material behavior changes are shown as a diff and require confirmation before becoming authoritative.

The profile makes Kora legible without exposing models, prompts, workers, routing, or private execution traces.

### Mission formation

Kora accepts either a rough idea or an existing PRD without asking the user to choose a mode.

- With a rough idea, Kora collaboratively develops an executable PRD.
- With an existing PRD, Kora audits and converts it into a mission contract.
- With an active repository, Kora determines the current state and continues from it.

The mission contract remains concise and includes:

- Intended user and problem.
- Narrow end-to-end product outcome.
- Explicit exclusions.
- Definition of done.
- Acceptance evidence.
- User-owned decisions and authority boundaries.

Kora does not judge whether the startup idea is worthy. If she discovers concrete evidence against a core assumption, she reports the evidence and impact, pauses only the affected path, and waits for the user's decision.

### Autonomous execution

Kora creates her own private, personalized AI workforce using the user's knowledge and working preferences. Existing agent files and workflows are treated as evidence about the user, not machinery Kora must preserve.

For the first mission, Kora should be able to:

- Research the ICP, competitors, and positioning when relevant to the mission.
- Convert the PRD into an internal execution plan.
- Design and implement the narrow product slice.
- Review work independently and retry failures.
- Configure required providers such as Supabase and Vercel after obtaining permission.
- Produce a working preview.
- Verify the preview against PRD-derived acceptance criteria.
- Request production deployment approval.
- Deploy the product after approval.
- Prepare an initial customer-outreach campaign.
- Request approval for public posts, messages, spending, and external commitments.
- Execute the bounded campaign after approval.
- Monitor outcomes and report evidence.

### Identity and ownership

Kora has one stable identity across surfaces: the default name Kora, her own phone endpoint, email/inbox, cloud workspace, memory, working history, and visible responsibility for her output. Naming customization may come later.

The user who creates Kora is her sole authoritative owner in v1. Other people may communicate with her when the user permits it, but they cannot assign missions, change goals, widen permissions, or commit the user without explicitly delegated authority.

Kora should feel like a human coworker in conversation without falsely claiming to be a biological human. When identity matters externally, she communicates transparently as Kora, the user's AI coworker or familiar.

### Communication

Kora behaves like a capable coworker, not a command-line tool or approval queue.

She communicates through:

- iMessage for everyday conversation and mobile approvals.
- Phone calls for the daily alignment meeting and important unanswered blockers.
- The desktop app for onboarding, deep conversation, context review, and observability.
- Mobile-friendly preview and review links sent through iMessage.

No dedicated phone app is required in v1. The phone experience is Kora as a contact who can text and call.

Kora's default personality is resourceful, direct, opinionated, ambitious, loyal, playful, calm, concise, and unpretentious. She may challenge an instruction that conflicts with the approved mission, but she may not override the user.

Messages should contain only the information required to understand progress, make a decision, or unblock work. Kora must not use condescending language, formulaic AI prose, unnecessary headings, or exaggerated empathy.

### Checkpoints and escalations

Kora maintains internal checkpoints but does not expose a formal checkpoint system. The user sees natural conversations such as:

> The preview is ready. I tested every PRD requirement and fixed an account-recovery issue. Take a look when you can. Once you approve it, I will deploy.

Kora contacts the user when:

- A decision requires unsupported judgment.
- Material ambiguity could produce a different product.
- A consequential action requires approval.
- A required artifact, credential, relationship, taste decision, or physical action belongs to the user.
- A failure affects quality, timing, cost, or requires user assistance.
- An instruction appears to change or conflict with the mission.

When blocked, Kora explains what she needs and what is blocked. She does not pressure the user. She continues only work that directly advances the approved mission and does not conflict with the unresolved decision. Otherwise, she stops and preserves state.

### Reciprocal delegation

Kora may assign work to the user when a human action is required. Every request must state:

- What Kora needs.
- Why it is required.
- What part of the mission is blocked.
- What artifact or answer will unblock it.

If an important request goes unanswered, Kora may call once. If the user still does not respond, she stops the blocked path rather than creating unrelated work.

### Daily alignment call

During an active mission, Kora initiates one phone meeting each day. She prepares the agenda and covers:

- Progress and verification evidence.
- Decisions made and their source.
- Material uncertainty or changed assumptions.
- User and Kora responsibilities.
- The next expected work.
- Whether current execution remains aligned with the mission.

Kora transcribes the meeting into persistent working memory, updates the mission state, and sends a concise recap. The user never takes meeting notes manually.

### Permissions

Connecting a service grants read access only. The first write or external action requires a just-in-time permission request with:

- The specific action.
- Connector and project.
- Expected consequence and risk.
- The options **Approve once** and **Always allow within this scope**.

Technical permission and decision authority remain separate. Persistent access to X, for example, does not authorize every public post.

Default approval boundaries include:

- Spending money.
- Posting through the user's identity.
- External outreach and interpersonal communication.
- External commitments.
- Production deployment.
- Major design or taste decisions.
- Destructive or difficult-to-reverse actions.

The user may grant bounded mandates covering multiple actions, such as an outreach campaign with an approved audience, content, budget, action limit, and expiration. Kora may suggest a narrowly scoped standing permission after repeated approvals but can never grant authority to herself.

### Desktop observability

The desktop app has two complementary observability views:

1. **Work:** what Kora is doing now.
2. **Kora:** who she is, what she knows, and how she knows how to work.

The Work home is a read-mostly, Kora-managed Kanban board:

- **Working:** what Kora is actively doing.
- **Next:** what she currently expects to do afterward.
- **Waiting on you:** decisions, access, artifacts, or approvals.
- **Ready for review:** previews and evidence requiring attention.
- **Done:** completed work and verification evidence.

Each card explains the work, why it advances the mission, relevant source context, current result, and supporting artifacts. Reprioritization happens by talking to Kora, not dragging cards.

The Kora view contains her skill tree, derived Markdown skills, approved knowledge and context files, source provenance, confidence, freshness, authority, and version history. Users can inspect how a source influenced Kora's behavior without inspecting her private worker implementation.

The app never exposes model names, prompts, tokens, subagents, workforce topology, or internal execution traces. Internal failures are retried or rerouted silently and surfaced only when they affect the user.

### Cloud-first operation

After onboarding, the user should not need to open their laptop unless Kora delegates a genuinely computer-dependent task.

Kora maintains an invisible persistent cloud workspace containing:

- The approved context snapshot.
- Active repositories and project files.
- Scoped connector credentials.
- Persistent memory and decision history.
- Mission state and artifacts.
- Everything required to continue while the Mac is offline.

The cloud computer is never presented as a remote desktop or infrastructure product. Users see Kora, conversations, the Kanban board, previews, and results.

### Local safety boundary

Broad computer access means broad reading and discovery, not unrestricted execution.

- Kora never receives an unrestricted shell on the user's Mac.
- Local access occurs through a capability-limited desktop bridge.
- Normal execution occurs in the cloud workspace.
- Project changes use versioned branches and recoverable synchronization.
- Material local changes require snapshots.
- Deletions are recoverable by default.
- Broad deletion operations are rejected by the permission layer.
- Destructive actions require itemized approval.
- An immutable user-visible action log records external and local changes.

Preventing catastrophic local damage is a system invariant, not a model instruction.

## Definition of done for a mission

Kora may claim the initial MVP mission is complete only when:

- A deployed product is usable end to end.
- The approved narrow slice satisfies the PRD.
- PRD-derived acceptance tests pass.
- A requirement-coverage map is available.
- Kora has performed a user-like walkthrough.
- Independent evaluation has scored the work harshly.
- Any incomplete, degraded, or uncertain behavior is disclosed.
- The user has approved the production deployment.
- The approved initial outreach campaign has been prepared and, when authorized, executed.

## Success metrics

### North-star metric

**Mission progress per minute of founder attention**, constrained by intent fidelity and output quality.

### Initial measures

- Founder interventions per three-hour work cycle.
- Percentage of interventions that genuinely required human judgment.
- Unattended productive duration.
- Material intent violations.
- Unsupported assumptions caught before execution.
- PRD acceptance-criteria pass rate.
- User corrections per consequential decision.
- Percentage of work accepted without rework.
- Time from onboarding to meaningful work.
- Time from mission approval to usable preview.
- Trust to grant Kora another mission.

The initial dogfood target is to reduce six to eight manual steering interventions per three-hour session to one or two necessary judgment interactions without materially reducing product quality.

## Pricing hypothesis

Launch with one premium monthly product around $250 to $300. Users buy Kora, not models or tokens. Model selection, routing, and infrastructure are hidden. Capacity limits may exist internally, but quality and the unified experience take priority over pricing optimization during the alpha.

## Explicit v1 non-goals

- Multiple simultaneous overarching missions.
- General consumer-life operation and appointment booking.
- An unrestricted shell on the user's computer.
- User configuration of models, agents, prompts, or workforce topology.
- Raw inspection of internal worker prompts or execution traces; only Kora's synthesized skills, knowledge, and provenance are visible.
- Replacing the user's right to choose product direction.
- Inventing new company goals.
- Acting through public identity, money, or external relationships without authority.
- A remote-desktop or VM-management product.
- Enterprise team administration.
- Perfectly imitating the user's taste on day one.
- Rebuilding commodity agent-harness infrastructure that can be safely reused from proven open-source projects.

## Long-term direction

Kora learns the user's tacit operating behavior through decisions, corrections, outcomes, and granted authority. Over time, she reproduces more of the user's judgment, taste, prioritization, and working style while preserving explicit consent at consequential boundaries.

The long-term vision is one persistent AI familiar per person: a stable relationship and operating model that survives changes in models, tools, and underlying workforces.
