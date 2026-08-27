# Product Decision Ledger

**Status:** Historical rationale and approved decisions  
**Updated:** 2026-08-26

Statuses:

- **Accepted:** part of the approved Kora direction.
- **Rejected:** intentionally not the current company or wedge.
- **Deferred:** potentially valuable later, but outside the initial slice.
- **Open:** requires evidence or a later decision.

## Accepted decisions

| ID | Decision | Rationale |
|---|---|---|
| K-001 | Build Kora as an AI familiar expressed as a coworker. | This combines a human relationship, persistent identity, and real work rather than companionship alone. |
| K-002 | Use **Kora** as the default name. | A stable identity matters more than naming configuration in v1. |
| K-003 | Target AI-native solo founders and developers first. | Direct founder need, high willingness to experiment, accessible workflows, and existing design partners. |
| K-004 | Start with one overarching product mission. | Goal fidelity and reliable completion matter more than breadth. |
| K-005 | Make “develop the narrow MVP” the first mission. | It is the strongest founder pain and the clearest test of replacing operational product work. |
| K-006 | Define completion as functional, usable, and PRD-complete. | Generated code or visible activity is not a finished product. |
| K-007 | Make Kora proactive within an approved goal. | The product fails if the founder must continuously prompt and choose tasks. |
| K-008 | Let Kora challenge but never independently override the user. | Coworker initiative must not become independent authority. |
| K-009 | Have Kora choose the highest-value unblocked task on the critical path. | Prevents busywork and preserves mission progress. |
| K-010 | Stop when the critical path is blocked and no approved work advances it. | Goal alignment is more important than appearing always busy. |
| K-011 | Let Kora delegate unavoidable human work back to the user. | Some judgment, identity, physical, access, and taste tasks cannot be automated safely. |
| K-012 | Communicate through semantic checkpoints and natural conversation. | The user wants coworker alignment, not tool logs or workflow configuration. |
| K-013 | Hold one daily alignment meeting during active missions. | Maintains shared context with low founder involvement. |
| K-014 | Use iMessage and calls for normal operation; desktop for onboarding and observability. | The laptop should remain closed unless the user must perform work. |
| K-015 | Present a Kanban-style semantic work view. | Users need to know what Kora is doing without seeing internal agents. |
| K-016 | Keep models, prompts, subagents, routing, compaction, and topology hidden. | Users buy one coworker and should not manage infrastructure. |
| K-017 | Give Kora her own private personalized workforce. | The user's best practices should transfer without preserving manual orchestration. |
| K-018 | Build a user-readable skill tree and Markdown knowledge files. | Users need to inspect and correct what Kora has learned. |
| K-019 | Begin onboarding with “What are you working on?” | A natural conversation is easier and more magical than role or workflow configuration. |
| K-020 | Keep onboarding near five to ten minutes and start useful work immediately. | A passive observation period would fail the first-use experience. |
| K-021 | Request broad read access, then separate action authority. | Context breadth helps understanding, but access must never imply permission. |
| K-022 | Offer a large connector marketplace. | Users should connect their environment quickly rather than configure integrations one by one over time. |
| K-023 | Support approve-once and approve-indefinitely. | Consequential actions require consent without forcing repeated low-value approval forever. |
| K-024 | Require approval for money, publishing, outreach, consequential messages, providers, accounts, production changes, destructive actions, and unlearned taste. | These boundaries contain the highest user and reputational risk. |
| K-025 | Use one logical cloud computer and invisible elastic workers. | Keeps the laptop closed and hides infrastructure complexity. |
| K-026 | Use Hermes Agent as Kora's replaceable initial execution harness behind `RuntimeAdapter`; keep Kora's control plane independent. | Speeds development without making an execution harness the source of truth for Kora's identity, relationship, mission, authority, context, evidence, or cloud-workspace policy. |
| K-027 | Keep Kora model-agnostic. | Quality, cost, and model leadership will change; Kora's relationship and context should persist. |
| K-028 | Launch with a unified premium monthly allowance around $250–$300. | Hide models and tokens, prioritize quality, and match the complete coworker value. |
| K-029 | Preserve a candid, human, non-condescending personality. | The relationship should feel like a coworker, not an aligned corporate chatbot. |
| K-030 | Retain strong consent and safety despite natural language. | Human tone cannot become a route around permission, truth, or computer safety. |
| K-031 | Treat a tagged Hermes release plus an immutable container image digest as the planned runtime-hardening pin; evaluate OpenHands only as a gated fallback if Hermes fails concrete vertical-slice gates. | Reproducibility and a credible replacement path are both required without broadening the current technology decision or coupling mission state to a harness. |
| K-032 | Adopt the staged technology stack in [`KORA_TECHNOLOGY_STACK.md`](../KORA_TECHNOLOGY_STACK.md): Python control plane, SQLite now/PostgreSQL beta, Kora-owned coordination with Temporal Cloud at the durability trigger, native Swift macOS, Twilio phone continuity, and a small managed cloud surface. | Preserves Kora's model-agnostic, authority-first architecture while deferring rewrites and infrastructure whose cost is not yet justified. |

## Rejected initial directions

| ID | Direction | Why it was rejected as the company wedge | Retained insight |
|---|---|---|---|
| R-001 | Universal agent wallet or debit card | Incumbents, regulation, liability, trust, and bootstrap difficulty. | Kora may eventually receive bounded purchasing authority. |
| R-002 | Agent transaction network or marketplace | Too infrastructure-heavy and less personally compelling as an initial product. | Agent-to-agent commerce may become part of the familiar ecosystem. |
| R-003 | Generic cloud laptop or VM clusters for agents | Timing and consumer replacement story felt weak; founder did not love the standalone product. | Kora should run on a hidden cloud computer and burst compute when needed. |
| R-004 | Startup idea evaluator | Real pain, but felt like conventional productivity rather than the future. | Kora should help reason about products as part of her coworker role. |
| R-005 | Generic goal tracker or roadmap manager | Previously explored and insufficiently compelling. | Explicit goals and mission state are core internal Kora infrastructure. |
| R-006 | Voice-first operating system | Apple platform constraints and voice itself was not the primary fascination. | Voice, calls, dictation, and a wake word remain interface directions. |
| R-007 | Pure AI best friend or companion | The relationship was appealing, but action and role replacement created the real willingness to pay. | Kora should feel familiar and human while remaining tool-first. |
| R-008 | AI founder or cofounder positioning | Implies independent agenda, control, and ownership inconsistent with the desired authority model. | Kora can perform founder work as a coworker under the user's mission. |
| R-009 | Operating the user's existing workforce unchanged | Preserves complexity and makes implementation dependent on arbitrary workflows. | Ingest the knowledge and compile Kora's own personalized workforce. |
| R-010 | Many visible specialist familiars | Weakens the persistent relationship and exposes orchestration. | Keep one Kora with hidden specialists. |

## Deferred directions

| ID | Direction | Condition for reconsideration |
|---|---|---|
| F-001 | Kora's own email, phone, inbox, and social identity | After legal, abuse, consent, and external-identity boundaries are proven. |
| F-002 | Autonomous purchasing and agent wallet | After external-action authority and financial risk controls are reliable. |
| F-003 | Appointments and general life administration | After the founder/developer wedge proves persistent action quality. |
| F-004 | Wake word and dedicated mobile application | When iMessage and calls expose a meaningful interface limitation. |
| F-005 | Agent-to-agent communication and group chats | After single-user identity, permissions, and provenance work reliably. |
| F-006 | Familiar fusion or multiplayer Kora | After ownership, privacy, conflicting authority, and memory merging are defined. |
| F-007 | Multiple simultaneous overarching missions | After one-mission goal fidelity is consistently strong. |
| F-008 | Consumer expansion beyond founders | After a repeatable wedge and operational cost model exist. |
| F-009 | Kora-created independent goals | Only with a separately approved governance model; not implied by proactivity. |
| F-010 | Public model or provider controls | Only if hidden routing materially harms trust or quality. |

## Open decisions

| ID | Question | Evidence needed |
|---|---|---|
| O-001 | What is the smallest product-development task that produces the first magical moment? | Dogfood missions and two developer design partners. |
| O-002 | Which native macOS implementation details and distribution gates should the alpha use? | Prototype speed, permissions, security, visual quality, and notarized distribution. |
| O-003 | What reliability, consent, and account-safety gates must an iMessage relay experiment pass? | Apple platform constraints, delivery reliability, founder setup, and an independent SMS fallback. |
| O-004 | Which voice UX, consent, and daily-meeting details should sit on the initial Twilio path? | Latency, cost, identity, recording consent, and naturalness. |
| O-005 | How should the selected beta cloud services provision, isolate, pause, and recover workspaces? | Real read/write mission tests, egress and secret-isolation trials, cost measurements, and recovery exercises. |
| O-006 | What semantic permission schema feels simple enough for users? | Usability testing across deployment, outreach, provider setup, and spending. |
| O-007 | Which models and routing policy achieve founder-level product quality within the allowance? | Task-level evaluations and actual cost traces. |
| O-008 | How should Kora store and update the user's operating model? | Context conflict tests, correction propagation, privacy, and retrieval quality. |
| O-009 | What portion of design and taste can be learned reliably? | Repeated artifact review and correction outcomes. |
| O-010 | Is $250–$300 economically viable and compelling? | End-to-end task cost and willingness-to-pay interviews after real value exists. |

## Change log

- **2026-08-26:** Initial ledger created from the startup and product-discovery
  conversation. No historical brainstorm was promoted into an active direction
  unless it was explicitly accepted in the PRD or later product decisions.
- **2026-08-26:** Aligned the Hermes decision with the replaceable
  `RuntimeAdapter` boundary. Kora owns durable product and control-plane state;
  Hermes runtime memory, scheduling, approvals, and self-improvement state are
  never authoritative. Added the later tagged-release/digest hardening target
  and gated OpenHands fallback condition.
- **2026-08-26:** Accepted the staged technology-stack decision in
  [`docs/KORA_TECHNOLOGY_STACK.md`](../KORA_TECHNOLOGY_STACK.md), including
  Python, SQLite/PostgreSQL, Temporal-at-trigger, native Swift, Twilio phone
  continuity, beta cloud defaults, and explicit replacement gates.
