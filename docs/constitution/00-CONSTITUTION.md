# 00 — CONSTITUTION

## Purpose

This directory (`docs/constitution/`) is the authoritative, version-controlled
specification of what `claude-ytb` is, why it is built the way it is, and how
its parts must fit together. It exists because a four-stage AI pipeline
touching LLMs, TTS, rendering, and platform publishing accumulates implicit
decisions fast — this is where those decisions are made explicit, so that
contributors (human or AI) make consistent choices without re-deriving the
architecture from scratch every session.

`PROJECT_VISION.md` (repo root) is the single immutable source of *intent*.
Everything in this directory **implements** that vision; nothing here may
contradict it. If a document in this directory and `PROJECT_VISION.md`
disagree, `PROJECT_VISION.md` wins and the document here is a bug to be fixed.

## Scope

This constitution covers:

- What the system's vision and success criteria are (`01-VISION.md`)
- What engineering and content principles govern every decision
  (`02-PRINCIPLES.md`)
- How the system is structured into layers, ports, and adapters
  (`03-ARCHITECTURE.md`)
- What the domain objects are and how they relate (`04-DOMAIN.md`)
- How work flows through the DAG, with checkpoint/resume semantics
  (`05-WORKFLOW.md`)

It does **not** cover day-to-day operational instructions (setup, deploy,
running commands) — that remains in the repo root `README.md` and `CLAUDE.md`.
This is architecture and intent, not an operations runbook.

## How to Use This Document Set

- **Before starting any non-trivial change**, read the document(s) relevant
  to the layer you're touching. Touching a `Provider` adapter → read
  `03-ARCHITECTURE.md` (ports/adapters) and `02-PRINCIPLES.md` (decision
  framework for local vs cloud). Touching a domain object → read
  `04-DOMAIN.md` first, then check `PROJECT_VISION.md` for immutability
  constraints (frozen dataclasses, platform independence).
- **Before adding a pipeline stage or modifying DAG behavior**, read
  `05-WORKFLOW.md` in full — checkpoint and resume semantics are
  load-bearing and must not be broken by a "quick" stage addition.
- **When a decision feels architecturally significant** (new provider type,
  new domain object, new pipeline node), update the relevant constitution
  document in the same change set as the code. Documentation drift here is
  treated as a defect, the same as a failing test.
- **When in doubt about precedence**: `PROJECT_VISION.md` > this constitution
  set > `CLAUDE.md` (session/operational notes) > inline code comments.

## Amendment Process

1. Propose the change as a diff to the relevant numbered document, with a
   rationale paragraph explaining why the existing principle/architecture is
   insufficient.
2. If the change conflicts with a Non-Negotiable Decision in
   `PROJECT_VISION.md`, it must be proposed there first, as a dated
   Amendment Log entry, before any constitution document can be updated to
   match.
3. Once accepted, update the document directly (this is version-controlled
   documentation, not a change-request ledger) and note the date in the
   document's own changelog section if one exists.
4. Constitution documents are never silently rewritten to match code drift —
   if code has drifted from a documented architecture, that is a bug to fix
   in code, or a deliberate amendment to propose, not a reason to quietly
   edit the document to "catch up."

## Document Index

| Document | One-line description |
|---|---|
| `00-CONSTITUTION.md` | This file — purpose, scope, hierarchy, amendment process |
| `01-VISION.md` | What "AI Native Creative OS" means, target users/platforms, success metrics, v1→v5 milestones |
| `02-PRINCIPLES.md` | Engineering principles (SOLID/Clean Architecture), AI-native principles, content quality principles, local-vs-cloud decision framework |
| `03-ARCHITECTURE.md` | Layered + hexagonal architecture diagram, ports/adapters, data flow across all four stages, extension points |
| `04-DOMAIN.md` | Full domain model — every object, its fields (as frozen dataclasses), and its relationships |
| `05-WORKFLOW.md` | The full DAG specification — every node's inputs/outputs/failure modes/retries, checkpoint and resume protocol |
