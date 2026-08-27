# Kora Technology Stack

**Status:** Accepted decision; staged for implementation
**Decision date:** 2026-08-26
**Base commit:** `78dace0`
**Scope:** V1 through the hosted beta

This is Kora's canonical technology-stack decision. It chooses implementation
boundaries and migration gates; it does not claim that a selected component is
already implemented. The product and system invariants remain authoritative in
[`KORA_V1_PRD.md`](../KORA_V1_PRD.md) and
[`KORA_TECHNICAL_ARCHITECTURE.md`](../KORA_TECHNICAL_ARCHITECTURE.md).

## Decision in one page

Kora keeps a Python control plane and does not rewrite its core to TypeScript,
Go, or Rust. FastAPI and Pydantic v2 are the future HTTP/configuration/DTO
boundary; Kora's frozen domain records remain framework-independent. SQLite is
the right current store for the single-controller Portion 1. A
`MissionStore` protocol and unit-of-work boundary must come before a move to
managed PostgreSQL, with Supabase Postgres as the preferred beta provider.

Kora owns an `ExecutionCoordinator` now and keeps Hermes behind
`RuntimeAdapter`. Temporal Cloud is adopted only at the first real durability
trigger. Temporal executes attempts and schedules recovery; it never owns
Kora's mission truth, permissions, evidence, provenance, or completion. Agent
frameworks are worker implementation details, not the control plane.

The Mac client is native Swift with SwiftUI and AppKit. Phone availability is a
cloud communication gateway using Twilio SMS/MMS and voice; iMessage is only a
founder-only Mac relay experiment. The beta uses a small managed cloud surface
and avoids Kubernetes, Kafka, Redis, a separate vector database, and
self-hosted ClickHouse.

## Adoption horizons

| Horizon | Decision |
|---|---|
| **Adopt now** | Python 3.11 compatibility, framework-independent domain/service layer, `MissionStore` and `ExecutionCoordinator` boundaries, SQLite for Portion 1, Hermes through `RuntimeAdapter`, FastAPI/Pydantic at the next API slice, native Swift desktop direction, and Kora-owned semantic events/evidence. |
| **Design for** | Supabase-managed PostgreSQL, SQLAlchemy 2 Core, psycopg3, Alembic, Temporal Cloud, external-action outbox, distributed leases/fencing, OpenTelemetry, cloud sandboxes, Twilio continuity, direct connectors, and a small Swift local bridge. |
| **Defer** | Language rewrites; LangGraph or Mastra as the mission engine; OpenAI Agents SDK as the product orchestrator; Tauri or Electron; iMessage as a cloud primitive; Kubernetes, Kafka, Redis, a separate vector database, self-hosted ClickHouse, and multiple overlapping durability systems. |

## Ownership boundaries

- **Kora control plane:** owns identity, mission/task state, scope, context
  provenance, authority, permissions, evidence, stop conditions, semantic
  events, and user-visible projections.
- **Mission store:** persists authoritative projections and append-only
  semantic events. Every consequential mutation is transactional and
  idempotent.
- **ExecutionCoordinator:** selects eligible Kora tasks, performs authority
  preflight, creates attempts, invokes a runtime adapter, validates results,
  and records evidence or escalation.
- **RuntimeAdapter/Hermes/agent SDKs:** execute bounded work and return
  untrusted results. Runtime sessions, prompts, model/provider identity,
  internal worker topology, and harness approvals are never Kora authority.
- **Temporal:** when adopted, owns durable workflow execution history,
  timers, signals, retries, and worker replacement mechanics. Kora remains the
  semantic source of truth. An approval may wake a Temporal workflow, but the
  approval is first recorded by Kora.
- **Connectors and sandboxes:** provide scoped technical capabilities only.
  They cannot grant decision authority, broaden mission scope, or mark work
  complete.
- **Observability:** technical traces and metrics explain execution. Kora's
  semantic event/evidence log proves what was authorized and completed.

## Backend and persistence

### Python control plane

Python remains the primary language. Keep the current Python 3.11 baseline for
V1 and test newer supported versions before changing the minimum. The control
plane is I/O- and state-bound, so Python's iteration speed and agent ecosystem
outweigh the deployment advantages of a rewrite.

Use [FastAPI](https://fastapi.tiangolo.com/features/) with Pydantic v2 for
HTTP commands/queries, authentication dependencies, configuration, API
schemas, and structured runtime envelopes. Keep `MissionService` and the
domain state machines independent of FastAPI and Pydantic. HTTP commands should
carry an expected revision and an idempotency key; response models should not
leak prompts, chain of thought, raw traces, or provider topology.

TypeScript remains a good future BFF/UI or isolated worker language, but not a
reason to split semantic authority. Go may be used for a high-concurrency
connector or sidecar. Rust may be used for a security-critical local bridge or
measured CPU bottleneck. Neither becomes the primary backend without a measured
requirement and a separately approved migration.

### SQLite now, PostgreSQL at the cloud trigger

SQLite remains the source of truth for the current single-controller Portion 1.
Use foreign keys, WAL, busy timeouts, explicit transactions, expected
revisions, and the existing append-only audit pattern. SQLite WAL permits
readers and writers to proceed together, but it still has one writer and
requires all processes to share a host. See the [SQLite WAL
documentation](https://www.sqlite.org/wal.html).

Introduce a `MissionStore` protocol and unit-of-work abstraction before adding
another database implementation. Move to managed PostgreSQL when cloud
continuity, multiple authoritative writers, phone/API concurrency, hosted
failover, or concurrent outbox claims become real. Row-level locking and
`SKIP LOCKED` are appropriate for bounded claim operations; they do not replace
Kora's state-machine guards. See [PostgreSQL locking](https://www.postgresql.org/docs/current/sql-select.html).

The preferred beta database provider is [Supabase
Postgres](https://supabase.com/docs/guides/database/overview), using:

- SQLAlchemy 2 Core rather than an ORM-centric domain model;
- psycopg3 for the PostgreSQL driver;
- Alembic for forward-only, reviewed migrations;
- relational columns for stable invariants and bounded JSONB for extension
  points; and
- one SQLite/PostgreSQL store contract suite.

The semantic event log, evidence, and authority records remain in PostgreSQL.
Do not introduce a separate vector or graph database for mission truth; add
retrieval indexes only when a measured context-retrieval problem requires
them.

## Orchestration and runtime

### Kora coordinator first

Build Kora's `ExecutionCoordinator` around the existing runtime contracts. It
must claim a task, create an attempt, bind the attempt to mission scope and
authority, invoke Hermes, validate structured output, attach evidence, and
recover safely after interruption. Add an external-action outbox,
idempotency records, leases, and reconciliation before relying on distributed
workers.

### Temporal Cloud at the first durability trigger

Adopt [Temporal Cloud](https://docs.temporal.io/) when any of the following is
real:

- a mission or attempt must outlive a process or deployment;
- Kora waits hours or days for an owner approval;
- timers, signals, retries, and worker replacement must be durable; or
- a successful model/tool side effect must not be repeated after a worker
  restart.

Use the [Temporal Python SDK](https://github.com/temporalio/sdk-python) with
deterministic workflows and activities for external calls. Map Temporal
workflow IDs to Kora mission/attempt IDs, make activity effects idempotent, and
keep secrets out of workflow history. If the durability trigger exists in the
first hosted slice, adopt Temporal there; otherwise keep Portion 1 local and
design the coordinator so Temporal can wrap it later.

### Agent frameworks stay behind the adapter

- **PydanticAI:** first framework to evaluate for typed, provider-neutral
  Python workers. Its [durable-execution guidance](https://pydantic.dev/docs/ai/capabilities/durable_execution/overview/)
  documents Temporal integrations. It does not own Kora mission state.
- **OpenAI Agents SDK:** optional provider-specific adapter for focused agents,
  handoffs/agents-as-tools, structured outputs, interruptions, and resumable
  worker state. The [official state guidance](https://developers.openai.com/api/docs/guides/agents/running-agents)
  and [result/interruption guidance](https://developers.openai.com/api/docs/guides/agents/results)
  are useful for the worker boundary. It is not Kora's authority or product
  orchestrator.
- **LangGraph:** not Kora's mission engine. Its [persistence model](https://docs.langchain.com/oss/python/langgraph/persistence)
  is appropriate only inside a bounded worker if graph-specific branching,
  interrupts, or replay demonstrably reduce implementation cost. Its
  checkpointer state must remain attempt-local and idempotent around side
  effects.
- **Mastra:** deferred. Its [workflow snapshots](https://mastra.ai/reference/workflows/snapshots)
  are viable, but adopting it now would add a TypeScript runtime and another
  state owner. Reconsider only after an explicit TypeScript-first product
  decision.

Hermes remains the replaceable initial execution harness behind
`RuntimeAdapter`. Later, pin a tagged Hermes release and immutable image
digest. Evaluate OpenHands only if Hermes fails concrete vertical-slice gates
for mission-scoped execution, Kora authority/stop enforcement, structured
results, and safe workspace behavior; use the same adapter contract.

## macOS client

Use native Swift with [SwiftUI](https://developer.apple.com/xcode/swiftui/)
for onboarding, Kanban, skills/context, and approval surfaces, and
[AppKit](https://developer.apple.com/documentation/appkit) for Mac-specific
behavior. Keep the local bridge small and explicit, using [XPC](https://developer.apple.com/documentation/xpc),
[SMAppService](https://developer.apple.com/documentation/servicemanagement/smappservice),
security-scoped bookmarks, [Keychain Services](https://developer.apple.com/documentation/security/keychain_services),
[FSEvents](https://developer.apple.com/documentation/coreservices/file_system_events),
notifications, and [App Intents](https://developer.apple.com/documentation/appintents).

Distribute the alpha with a direct Developer ID/notarized DMG using Apple's
[Developer ID](https://developer.apple.com/developer-id/) and
[notarization](https://developer.apple.com/documentation/security/notarizing_macos_software_before_distribution)
path. Add [Sparkle 2](https://sparkle-project.org/) after the release path is
stable. [Tauri 2](https://v2.tauri.app/) is a fallback only if cross-platform
demand becomes material; Electron is deferred.

## Phone continuity

The production path is a cloud communication gateway using [Twilio
SMS/MMS](https://www.twilio.com/docs/messaging) and [Twilio
Voice](https://www.twilio.com/docs/voice), so Kora continues while the Mac is
closed. The gateway must translate messages into Kora commands and semantic
checkpoints, not expose a second authority model.

iMessage is an opt-in, founder-only Mac relay experiment after SMS works. It is
never the availability guarantee or a cloud primitive. A native iOS companion
for approvals and status follows only after the phone-first workflow proves
useful.

## Hosted beta platform

| Responsibility | Default | Boundary or fallback |
|---|---|---|
| API and workers | [Railway Pro](https://railway.com/pricing) | [Fly.io](https://fly.io/docs/) where region/placement matters. |
| Semantic database | [Supabase Pro](https://supabase.com/pricing) | Keep the store contract portable. |
| Artifacts and snapshots | [Cloudflare R2](https://developers.cloudflare.com/r2/pricing/) | Keep metadata and evidence references in Kora's database. |
| Durable execution | Temporal Cloud at the trigger | Do not self-host Temporal for V1. |
| Linux sandboxes | [Daytona](https://www.daytona.io/docs/en/) after isolation, pause/resume, and egress trials | [E2B](https://e2b.dev/pricing) for higher-risk workloads; [Modal](https://modal.com/docs) for burst/GPU only. |
| Technical telemetry | OpenTelemetry Collector + [Langfuse](https://langfuse.com/docs) internal traces | Kora's semantic evidence log stays separate; redact prompts and secrets. |
| Secrets | [Infisical](https://infisical.com/docs) or a cloud KMS | Store references and scoped grants, never raw credentials in mission state. |
| Connectors | Direct implementations for the first 2–3 | Introduce [Nango](https://nango.dev/docs) around connector 4–5 if it reduces maintenance without obscuring authority. |

V1 does not need Kubernetes, Kafka, Redis, a separate vector database, or
self-hosted ClickHouse. Add a component only when a concrete reliability,
scale, isolation, or product requirement cannot be met by the selected beta
surface.

## Migration and replacement gates

| Change | Trigger | Required proof before changing |
|---|---|---|
| SQLite → PostgreSQL | A second authoritative writer, phone/API concurrency, hosted failover, or concurrent outbox claims. | Store contract passes on both backends; deterministic export/import; row counts, checksums, event ordering, and rollback snapshot verified. |
| Coordinator → Temporal Cloud | Long-lived waits, approvals, timers, retries, or worker replacement. | Attempt IDs, idempotent effects, outbox/reconciliation, workflow replay tests, and a recovery drill. |
| Hermes → another runtime | Hermes fails a concrete vertical-slice gate or blocks required structured/tool behavior. | Same adapter contract, same authority tests, same evidence gate, and an A/B mission evaluation. |
| Add LangGraph or Mastra | A bounded worker has graph/snapshot needs that reduce code materially. | Worker-local state is non-authoritative, side effects are idempotent, and the framework does not duplicate mission truth. |
| Python → TypeScript, Go, or Rust | A measured team, deployment, security, or performance constraint outweighs migration cost. | Benchmark or security evidence, API/schema compatibility plan, and no split ownership of mission semantics. |
| iMessage → production path | Only if reliability, account safety, consent, and availability gates pass. | SMS remains an independent fallback and cloud path. |
| Daytona → E2B or another sandbox | Isolation, pause/resume, egress, or workload-risk trial fails. | Reproducible workspace, secret isolation, network policy, recovery, and cost evidence. |

## Bootstrap cost estimate

This is research-derived planning guidance, not a vendor quote. Based on public
pricing checked on 2026-08-26—[Supabase](https://supabase.com/pricing),
[Railway](https://railway.com/pricing), [Temporal Cloud](https://temporal.io/get-cloud/aws-marketplace),
[R2](https://developers.cloudflare.com/r2/pricing/), [Twilio SMS](https://www.twilio.com/en-us/sms/pricing/us),
[Twilio Voice](https://www.twilio.com/en-us/voice/pricing/us), and metered
[Daytona](https://www.daytona.io/docs/en/billing/) or [E2B](https://e2b.dev/pricing)—use
these ranges:

- **Hosted alpha before Temporal:** approximately **$75–$250/month** for API/
  worker hosting, Supabase Pro, small R2 usage, one phone number with modest
  SMS/voice volume, telemetry, and light sandbox use.
- **Temporal-enabled beta:** approximately **$175–$500/month** for the same
  surface plus Temporal Cloud and more recurring sandbox/observability use.
- **Budget guardrail:** reserve **$500+/month** for test-heavy months with
  frequent sandboxes, long calls, or burst compute.

These estimates exclude model tokens, heavy GPU workloads, high-volume
telephony, taxes, and future team/enterprise plans. Model and sandbox spend
must have Kora-owned budgets, per-mission limits, and an explicit stop path.

## Risks and controls

1. **Two durable systems drift.** Keep Kora's database authoritative and map
   every runtime execution to a Kora attempt; use idempotency and reconciliation.
2. **Framework churn creates accidental rewrites.** Keep agent frameworks
   behind `RuntimeAdapter` and prefer narrow contract tests over framework APIs
   in the domain.
3. **Cloud execution leaks authority or secrets.** Separate capability from
   decision authority, use scoped credentials, enforce egress policy, and keep
   raw prompts/secrets out of traces and workflow history.
4. **Apple messaging becomes a hidden availability dependency.** Make Twilio
   the cloud path and keep iMessage relay opt-in and disposable.
5. **Sandbox costs and recovery failures grow silently.** Require pause/resume,
   crash, egress, secret-isolation, and cost trials before a default sandbox
   provider is promoted.
6. **SQLite migration loses semantic history.** Use expand/contract migrations,
   deterministic imports, checksums, event-order checks, and an immutable
   read-only SQLite rollback snapshot.

## Consequences for the current repository

This decision requires no source, test, dependency, or implementation changes
by itself. The next implementation slice should:

1. preserve the current domain state machines and Hermes adapter contracts;
2. add `MissionStore`/unit-of-work protocols before a second database;
3. add Kora-owned attempts, leases, outbox, idempotency, causation, scope
   version, and evidence-verification records;
4. implement `ExecutionCoordinator` and the crash/recovery acceptance tests;
5. add FastAPI/Pydantic only at the API boundary; and
6. add a SQLite/PostgreSQL contract suite before selecting a hosted database.

The accepted stack is therefore a staged platform decision, not evidence that
PostgreSQL, Temporal, the desktop app, phone gateway, cloud sandboxes, or
production authentication already exist.
