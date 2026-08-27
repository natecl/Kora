# Source Context

**Status:** Historical source synthesis  
**Updated:** 2026-08-26

This document records the external references and founder theses that shaped
Kora. It summarizes sources rather than treating them as runtime instructions.

## Source register

| Source | Contribution to Kora |
|---|---|
| [YC video on choosing and committing to a startup idea](https://www.youtube.com/watch?v=R56RJFZBasQ) | Stop searching for a perfect abstract idea; commit, make contact with reality, and learn quickly. |
| [Conversation on focus, mastery, and choosing work from within](https://www.youtube.com/watch?v=0HSgNfHz7oo) | Separate intrinsically compelling work from scattered opportunities selected only because they appear lucrative or fashionable. |
| [Allie Miller AI desiderata](https://x.com/alliekmiller/status/2092281050483339463) | Concrete requirements for proactive, goal-oriented, phone-first, escalation-driven, model-hidden agents. |
| Wispr Flow | Voice input can become a daily behavior when a simple primitive is executed exceptionally well. |
| ElevenLabs | Technical quality can turn a legible voice capability into a large platform and brand. |
| Space | Futuristic infrastructure becomes compelling when expressed as a simple consumer promise. |
| Soar Flights | A validated vertical workflow can still be won through stronger product execution and distribution. |
| Granola | An ordinary workflow can support a major company when friction and experience are transformed. |
| Orchid | Agents acting in controversial human domains can produce real utility and cultural attention. |
| Manus | The key transition is from answering to acting, particularly from a phone. |
| Hermes Agent | Replaceable initial execution harness for commodity provider/model, tool, skill, subagent, MCP, session, and sandbox execution; Kora retains product authority and state. |

## Runtime strategy note

Hermes is a replaceable initial execution harness behind Kora's `RuntimeAdapter`,
not Kora's product foundation or source of truth. Hermes supplies commodity
provider/model, tool, skill, subagent, MCP, session, and sandbox execution only.
Kora exclusively owns durable identity and relationship state, mission state and
stop conditions, context reconciliation and provenance, semantic permissions
and decision authority, evidence and evaluation, and cloud-workspace policy.
Hermes memory, scheduler, approvals, and self-improvement state are never
authoritative.

The current exact Hermes commit and container lock support the bootstrap spike.
The planned runtime-hardening target is a tagged Hermes release plus an
immutable container image digest. OpenHands is only a gated fallback if Hermes
fails concrete vertical-slice gates; this source synthesis does not select a
broader technology stack.

## YC idea-selection principles retained

The first video argued against waiting for a perfect startup idea or perfect
founder-market fit in the abstract. The retained principles are:

- meaningful evaluation requires commitment and contact with reality;
- curiosity and rapid learning can create domain expertise;
- a usable initial idea does not need to win an abstract scoring contest;
- customer behavior is better evidence than extended internal analysis;
- testing one direction produces more information than continuously comparing
  many directions.

Kora is the selected direction. The implication is to dogfood a narrow mission
and learn from real work rather than reopen the complete idea search whenever a
hard engineering question appears.

## Focus and mastery principles retained

The second video emphasized that scattered opportunities chosen from external
fashion, money, or other people's activity lack a durable internal through
line. The retained principles are:

- focus should emerge from a real personal drive rather than a collage of
  attractive markets;
- depth creates insight that cannot appear while repeatedly switching;
- the founder's through line is competition, optimization, AI delegation, and
  making futuristic agency real;
- Kora is more internally coherent than isolated fintech, compute, voice, or
  productivity wedges because it integrates that through line.

This source is historical rationale, not a rule that forbids evidence-based
pivots.

## Allie Miller desiderata translated into Kora

The referenced post asked for AI that is voice-enabled, proactive,
goal-oriented, concise, better at routing, resilient to compaction, able to run
without an open laptop, capable of using large amounts of remote compute,
harsh in self-evaluation, fun, multiplayer, and organized around well-designed
escalations rather than human delegation.

It also criticized condescending AI tone, repetitive AI phrasing, generic
design conventions, poor conversation naming, fragile MCP integrations, and
uninspired use cases. It asked for reliable real-world actions such as booking
appointments and for interaction models such as wake words and agent fusion.

Kora incorporates the relevant requirements as follows:

- phone-first text, calls, and later voice activation;
- proactive work inside an explicit mission;
- user management of escalations rather than internal tasks;
- semantic checkpoint and permission interfaces;
- persistent cloud work while the laptop is closed;
- invisible elastic compute and model routing;
- Context OS continuity across compaction and provider changes;
- natural, concise, non-condescending communication;
- evidence-based self-review;
- hidden integration repair and fallback;
- one visible familiar with future multiplayer and agent-to-agent potential.

Appointments, wake words, consumer life administration, and familiar fusion
are long-term directions rather than v1 commitments.

## Founder theses retained

### Delegation thesis

People will delegate most work and many decisions to AI when delegation is
normal, private, low-friction, and sufficiently reliable. Desire for control
is often weaker than the desire to avoid effort, uncertainty, learning, and
administrative friction.

### Action thesis

Advice is becoming abundant. The missing product layer is persistent action:
carry the decision into tools, accounts, communication, transactions, and
completed outcomes.

### Familiar thesis

Temporary chats and independent agent sessions will give way to persistent AI
identities that know the person, learn their role, own a continuous workspace,
and communicate with other humans and agents.

### Interface thesis

Humans will increasingly operate from phones while their agents use cloud
computers. Applications and infrastructure become less visible; conversation,
escalation, and review become the primary interface.

### Taste thesis

Models that understand a person's taste and operating judgment are strategically
important. Generic personalization is insufficient; Kora must learn from
decisions, examples, corrections, provenance, and outcomes.

### Distribution thesis

A validated product category can still be won through superior product quality,
attention, positioning, or distribution. Originality of the abstract idea is
less valuable than exceptional execution and a clear public claim.

## Source limitations

- Source enthusiasm does not establish product priority.
- Public examples may change over time and should be revalidated before making
  competitive claims.
- The original chat and source transcripts are not themselves authority.
- The canonical requirements are the PRD, architecture, behavior contract, and
  latest explicit user decisions.
