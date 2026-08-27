# Conversation Synthesis

**Status:** Historical synthesis  
**Coverage:** Product-discovery conversation and implementation reconciliation through 2026-08-27

This document preserves the path from an open-ended startup search to Kora.
It exists because the rejected paths and founder motivations explain the final
product. It is not a raw transcript and does not override approved product
requirements.

## 1. The search began with a future-facing consumer startup

The original request was not simply to generate ideas. The founder wanted to
discover a domain that felt personally compelling, futuristic, culturally
visible, technically interesting, and capable of reaching roughly $1 million
ARR as a solo or very small company.

The founder's strongest product references were Wispr Flow, Space, Soar
Flights, ElevenLabs, Orchid, Granola, and Manus. Across them, the admired
pattern was not one industry. It was a simple and immediately understandable
capability made magical through execution:

- dictation good enough to replace typing;
- voice generation good enough to create a category;
- effectively infinite computer space;
- a vertical workflow completed in seconds;
- agents entering a controversial part of human life;
- an ordinary behavior such as notes made into a beloved product;
- agents that act rather than merely answer.

The founder ranked the desired company experience approximately as:

1. build a product people use many times per day;
2. create a beloved consumer brand;
3. replace an old experience with something radically better;
4. build futuristic infrastructure others depend on;
5. build an agent that completes real-world actions.

The unifying aspiration was to **live in the future and fill in what is missing
from the present**, particularly at the edge of AI.

## 2. The initial future was phone-first delegation

The founder imagined a world where people rarely open laptops. They talk to an
AI from a phone, possibly through a wake word, and the AI searches, organizes,
remembers, plans, purchases, fills forms, operates websites, manages apps, and
coordinates with other people's agents.

Examples included appointments, groceries, fitness, meals, school systems,
documents, messages, email, calendars, social relationships, and purchases.
The important capability was not real-time voice by itself. Speech-to-text was
useful, but the deeper interest was:

- reliable real-world transactions;
- agents operating websites and computers;
- systems that understand personal taste;
- agents that can use money, identity, inboxes, tools, and data.

An early voice operating-system direction was rejected because Apple's
platform made universal app control a difficult entry point and because voice
alone did not feel like the core value.

## 3. Fintech and agent wallets were explored

The founder became interested in a universal agent wallet: give an agent a
budget, allow it to spend autonomously below a limit, protect the underlying
card details, verify transactions, and eventually support agent-to-agent
commerce. Initial use cases included groceries and ordinary Amazon purchases,
with a default low-value threshold such as $25.

The category was attractive because of its economics and the possibility of a
percentage of agent transactions. It became less attractive because:

- existing card and payment companies could expose similar controls;
- regulation, licensing, trust, and liability made bootstrapping difficult;
- incumbents were already validated and well positioned;
- the founder wanted a beautiful consumer or prosumer product with faster
  iteration.

The agent-wallet thesis remains a possible future Kora capability, not the
initial company wedge.

## 4. Productivity ideas did not feel futuristic enough

The founder identified real personal problems around startup ideation,
capturing ideas across their head and Codex tasks, choosing which ideas deserve
attention, making roadmaps, and steering AI agents. A startup-idea evaluation
or productivity product could have been useful, but the founder rejected it
because it did not feel like building the future.

This distinction mattered: a real pain was insufficient if the resulting
product felt like a conventional tracker or assistant.

## 5. Cloud computers for agents were explored

Another direction imagined humans using phones while their agents owned cloud
computers. Instead of upgrading a laptop, a person would upgrade the agent's VM
or temporarily attach clusters. This came from a direct pain: running many
subagents and long Codex tasks caused the founder's M4 Max laptop to struggle.

Metered cloud compute could be cost-effective and immediately helpful for
heavy AI users. The direction was rejected as the main startup because most
people already own computers, the consumer replacement cycle may be long, and
the founder did not love the infrastructure product enough. The insight was
retained inside Kora: the laptop should stay closed and Kora should use an
invisible persistent cloud workspace with elastic compute.

## 6. The founder's deeper motivation was examined

The conversation moved from markets to motivation. The founder is unusually
absorbed by competition, public rank, rapid improvement, and visible progress.
This appears across sports, fitness, games, debate, learning, and startup
ambition. The desired victory includes money, recognition, and being seen by
ordinary people as the builder of something impressive, futuristic, or
controversial.

The founder prefers the fastest credible route to a visible win and is willing
to enter a validated category, out-execute an existing product, or win through
distribution. Building for its own sake has not produced a strong emotional
reward. Operating sophisticated AI workflows, optimizing productivity, and
getting better at a competitive process have been more intrinsically
engaging.

This clarified that the startup needed both a compelling public claim and a
product the founder would personally use heavily. Kora's claim became larger
than “AI productivity”: **AI can replace much of a person's operational role
as a persistent digital coworker.**

## 7. Personal AI use revealed the real behavior

The founder already delegates a large share of thinking to AI: product
decisions, writing, research, interpretation, recommendations, communication,
fitness, food, relationships, media, and administrative questions. The normal
pattern is to ask which option is best and then follow the recommendation.

The frustration is that the advice stops at the answer. The founder still has
to copy, reword, send, navigate, prompt another tool, make the next plan, or
operate the agent workforce. A proactive ChatGPT-like relationship combined
with Manus-like action would be used every day.

The desired relationship initially sounded like a best friend on iMessage who
knows the user deeply and can do things. Pure companionship did not create a
strong “wish I built this” reaction. The idea became more compelling when the
AI gained persistent work identity, its own tools, and the ability to perform a
role over time.

## 8. The AI familiar emerged

The decisive concept was an AI identity—or familiar—that behaves like a
persistent person on the digital internet:

- reachable by text;
- able to work while the user is away;
- proactive rather than prompt-bound;
- able to own an inbox, name, tools, and workspace;
- able to learn how the user performs a role;
- able to collaborate with other humans and agents;
- able to ask the user for help and delegate tasks back;
- capable of replacing more of the user over time.

Instead of a designer repeatedly prompting temporary design agents, the person
would teach their familiar how they design. Instead of managing a visible AI
workforce, the person would communicate with one familiar who privately
organizes whatever workers are needed.

The long-term statement became: everyone may have their own AI familiar.

## 9. The initial wedge became product development

The founder said they would pay immediately if an AI could replace them in
operating their product workflow. The high-value behavior was:

- take an idea or PRD to an MVP quickly;
- understand all relevant product and workflow context;
- create and follow the roadmap;
- choose the next high-value task without repeated prompting;
- build, review, research, deploy, and prepare growth;
- communicate decisions and checkpoints like a coworker;
- ask for taste or judgment where necessary;
- escalate external actions;
- keep working while the founder works on something else.

The product was briefly described as an AI founder or cofounder. That framing
was rejected. Kora should be generalized as a coworker who can perform a role,
not an independent founder with control, ownership, or authority. The first
marketing wedge is founders and developers because the founder is the user,
the workflow is accessible, and early design partners already exist.

The default first mission is **develop the narrow MVP**. Completion means the
MVP is functional, usable, and covers the agreed PRD—not merely that code was
generated.

## 10. Kora's work model was refined

Kora should not merely operate a user's existing multi-agent setup. She should
inspect their repositories, prompts, agent instructions, context files,
knowledge documents, memory, best practices, and corrections, then compile her
own personalized workforce. The user retains the valuable knowledge and way of
working without being forced to maintain the old orchestration.

Only Kora is visible. Her models, workers, model routing, compaction, tool
plumbing, and internal topology are completely hidden. The desktop app instead
shows semantic product state:

- a Kanban-style view of work;
- checkpoints and escalations;
- the active objective and definition of done;
- Kora's skills and knowledge;
- source provenance and contradictions;
- artifacts, previews, decisions, and evidence.

Kora's skill tree is not a resume or a generic marketplace. It is a readable
map of what she has learned from this user and how she performs their work.

## 11. Onboarding was narrowed to a magical first experience

Kora should begin in a desktop app with no more than roughly five to ten
minutes of onboarding. The first question is simply, **“What are you working
on?”**

She then:

- requests broad computer read access;
- presents a large connector marketplace;
- discovers relevant tools and sources;
- ingests repositories, PRDs, instructions, knowledge, memory, and history;
- summarizes included and excluded context;
- identifies contradictions and proposes authority order;
- shows the initial knowledge documents and skill tree;
- explains the product as she understands it;
- proposes the objective and next steps;
- asks whether that sounds good;
- starts useful work immediately after approval.

She should not ask the user to configure a stack. When technology choices are
needed, she asks about durable preferences—budget, performance, familiarity,
and trust—then recommends and configures the stack with appropriate approval.

## 12. Communication and authority were separated

The founder wanted Kora to communicate extensively enough that the pair remain
on the same wavelength, but not require approval for every implementation
detail. The resulting interaction model is:

- Kora chooses tasks and internally delegates them;
- the user manages escalations;
- safe, reversible inferences can proceed;
- material judgment is discussed;
- external or consequential action is approved;
- approvals can apply once or indefinitely;
- Kora challenges but does not override;
- Kora stops when blocked rather than broadening the mission.

Anything involving money, publishing, outreach, consequential messages,
providers, accounts, production changes, or unlearned taste normally requires
approval. The user can grant a bounded evergreen approval.

Kora may call once for an important unanswered issue. If the user does not
respond, she stops the blocked path. A daily alignment meeting is part of an
active mission.

## 13. The interface became laptop-closed and phone-first

Onboarding, deep context review, the skill tree, and observability live in the
desktop app. Normal operation should happen through iMessage and calls. There
is no dedicated phone app requirement in v1; Kora should feel like a contact.

The user should not have to keep a laptop open. Kora uses one logical cloud
computer, with hidden processes or elastic workers as necessary. The user does
not manage multiple VMs, model configurations, context windows, MCP failures,
or infrastructure.

## 14. Open source became a speed strategy

The founder explicitly wanted to use as much proven open-source work as
possible to accelerate development. Hermes Agent is the replaceable initial
execution harness behind Kora's `RuntimeAdapter`, not Kora's product foundation
or source of truth. It supplies commodity provider/model, tool, skill,
subagent, MCP, session, and sandbox execution only.

Kora's product and control-plane layer owns durable identity and relationship
state, mission state and stop conditions, context reconciliation and provenance,
semantic permissions and decision authority, evidence and evaluation,
cloud-workspace policy, reciprocal delegation, personalization, and the
phone-first experience. Hermes memory, scheduler, approvals, and
self-improvement state are never authoritative, even if the harness exposes
those capabilities.

The current exact Hermes commit and container lock support the bootstrap spike.
The planned runtime-hardening target is a tagged Hermes release plus an
immutable container image digest. OpenHands is only a gated fallback if Hermes
fails concrete vertical-slice gates, and would have to satisfy the same
adapter-owned boundary. This does not decide the broader technology stack.

The founder's current runtime decision is to dogfood/test until Kora should
default to a **NOT-YET-IMPLEMENTED Codex App Server adapter** using
founder ChatGPT-managed Codex subscription authentication. Codex owns and
refreshes credentials; tokens never enter Kora durable state or public
projections, while Kora may privately observe plan/rate-limit state. Production
must use company-owned API keys/provider accounts with metering, budgets, and
billing, never a personal Codex subscription. The transport switch must not
alter Kora's durable mission, permission, evidence, memory, or routing
contracts.

## 15. The commercial hypothesis stayed premium and unified

The founder could not imagine the average user paying much more than $300 per
month and would personally pay that only if Kora delivered the complete
high-quality vision. The working hypothesis is a $250–$300 base monthly
allowance with models, providers, and tokens hidden. Different model
configurations and internal limits can make Kora always-on, but users purchase
Kora's outcome and quality rather than inference units.

Pricing optimization is deliberately later than product quality.

## 16. Final product boundary

Kora is now defined as:

- one persistent AI coworker;
- initially for AI-native solo founders and developers;
- working on one approved overarching mission;
- using her own personalized hidden workforce;
- operating primarily in a cloud workspace;
- communicating through iMessage, calls, and a desktop observability app;
- proactive inside the mission;
- transparent about semantic decisions and checkpoints;
- conservative at external, destructive, costly, or ambiguous boundaries;
- designed to reproduce more of the user's working judgment over time.

The current repository implements an accepted Kora-owned work-cycle slice and
the initial runtime boundary. At canonical commit
`1754168ed09692ed1b5a611ad6b06a220b42543b`, the Sol High review verdict is
**ACCEPT**, with 27 focused and 168 full tests passing. The offline dogfood
fixture turns an empty-repository founder brief into a functional,
zero-dependency waitlist MVP while persisting mission, attempt, permission,
evidence, lease/fence, recovery, private route-budget, and closed-projection
state. No P0/P1/P2 findings were identified in the implemented verified
work-cycle slice. This is not whole-product release readiness.

## 17. Implementation reconciliation

The founder-first wedge remains the starting point for a generalized
professional coworker, never a decision to shrink Kora to a coding agent. The
accepted slice proves the control-plane boundary and dogfood work cycle; the
desktop, mobile/iMessage/voice, cloud workspace/VM fleet, connectors, external
actions, always-on daemon/scheduler, and full skill-tree/self-learning UX remain
future gaps. Tagged/pinned Hermes plus immutable-image live evaluation is also
future hardening, and Hermes remains a replaceable execution harness rather
than Kora's foundation or source of truth.
