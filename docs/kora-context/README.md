# Kora Context Pack

**Version:** 1.0  
**Approved:** 2026-08-26  
**Purpose:** Preserve the durable product, founder, behavioral, and historical
context behind Kora so future humans and agents do not have to reconstruct her
from a chat transcript.

This directory is Kora's canonical context pack. It complements the product
requirements and technical architecture; it does not replace them and it does
not grant runtime authority.

## Authority order

When sources conflict, use this order:

1. The user's latest explicit instruction.
2. The active mission, definition of done, and current approval scope.
3. [`KORA_V1_PRD.md`](../../KORA_V1_PRD.md) for approved product behavior.
4. [`KORA_TECHNICAL_ARCHITECTURE.md`](../../KORA_TECHNICAL_ARCHITECTURE.md)
   for system invariants and technical boundaries.
5. [`BEHAVIOR_CONTRACT.md`](./BEHAVIOR_CONTRACT.md) and
   [`KORA_IDENTITY.md`](./KORA_IDENTITY.md) for Kora's durable operating style.
6. [`FOUNDER_CONTEXT.md`](./FOUNDER_CONTEXT.md) for personalization and
   interpretation.
7. [`PRODUCT_DECISION_LEDGER.md`](./PRODUCT_DECISION_LEDGER.md) and
   [`SOURCE_CONTEXT.md`](./SOURCE_CONTEXT.md) for historical rationale.

Historical context can explain a decision. It cannot approve spending,
publishing, outreach, account changes, destructive computer actions, or a new
mission.

## Contents

- [`KORA_IDENTITY.md`](./KORA_IDENTITY.md): who Kora is and is not.
- [`FOUNDER_CONTEXT.md`](./FOUNDER_CONTEXT.md): the founder's relevant goals,
  tastes, behavior, strengths, and constraints.
- [`BEHAVIOR_CONTRACT.md`](./BEHAVIOR_CONTRACT.md): how Kora acts, asks, stops,
  escalates, communicates, and learns.
- [`CONVERSATION_SYNTHESIS.md`](./CONVERSATION_SYNTHESIS.md): the full product
  discovery narrative distilled from the conversation.
- [`PRODUCT_DECISION_LEDGER.md`](./PRODUCT_DECISION_LEDGER.md): accepted,
  rejected, deferred, and unresolved product decisions.
- [`SOURCE_CONTEXT.md`](./SOURCE_CONTEXT.md): source videos, product references,
  the Allie Miller desiderata, and the founder's future thesis.
- [`CURRENT_STATE.md`](./CURRENT_STATE.md): what exists in code today and what
  remains conceptual.
- [`manifest.json`](./manifest.json): machine-readable index and authority
  metadata.

## Interpretation rules

- Preserve the founder's meaning, not speech disfluencies or exact phrasing.
- Treat personal anecdotes as evidence of needs, not blanket authorization.
- Do not infer permission from enthusiasm, trust, prior behavior, or a product
  aspiration.
- Do not store passwords, credentials, private messages, chain-of-thought, or
  unnecessary sensitive anecdotes in this pack.
- Kora may be candid and human without pretending to be legally human or
  removing safety boundaries.
- The final approved product decisions outweigh abandoned brainstorms.
- Unknowns stay explicit. Do not silently convert them into product decisions.

## Updating the pack

A material correction should:

1. update the applicable canonical document;
2. add or amend a decision in the ledger;
3. record the date and reason;
4. identify any PRD, architecture, skill, or implementation that is now stale;
5. require approval before a behavior-changing interpretation becomes active.

This pack is designed to become an input to Kora's future Context OS. The
current repository does not yet ingest it automatically.
