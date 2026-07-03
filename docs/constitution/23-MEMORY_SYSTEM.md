# 23 — Memory System

> Status: **NOT IMPLEMENTED.** Current state is `data/ledger.md` (manual,
> human-readable anti-duplication log) and `auto_state.json` (queue/run
> state for the listener daemon). This document specifies the target
> structured memory subsystem that supersedes both, per `01-VISION.md` v5
> ("Memory and Checkpoint subsystems support long-running, multi-session
> creative work").

## 1. Purpose

`claude-ytb` produces recurring content for a single channel/niche over an
indefinite number of sessions. Without durable memory, every `claude -p`
invocation (per `CLAUDE.md`: "mỗi lệnh chạy 1 phiên MỚI, context luôn sạch")
starts blind — it cannot know what topics were already covered, which
B-roll style worked, or which Character/Location was used in episode 3.
The Memory System is the subsystem that makes the *system* remember, so the
LLM context window doesn't have to.

This is distinct from the **Cache System** (`24-CACHE_SYSTEM.md`), which
remembers *artifacts* (deterministic outputs keyed by content hash). Memory
remembers *facts and judgments* — things a human producer would write in a
notebook, not things a render pipeline would memoize.

## 2. Memory Types

### 2.1 Working Memory (current project)

Scope: a single `Project` (one `project_id`), one production run, possibly
spanning multiple resumed sessions until publish.

Contents: research notes gathered during ideation, outline decisions,
narrative choices, which DAG nodes are done, scratch notes left by one
pipeline stage for a later stage to read (e.g., "voiceover stage flagged
segment 4 pronunciation as uncertain — render stage should not auto-caption
it").

Lifetime: created when a `Project` is created, archived (not deleted) into
episodic memory when the project reaches `PUBLISHED` or `ABANDONED` status.

### 2.2 Episodic Memory (past projects)

Scope: all completed/abandoned projects for a channel.

Contents: "topic X was covered in episode 3, published 2026-04-12, used
narrative angle Y", "B-roll style 'urban night timelapse' had high retention
in episodes 5 and 9", "title pattern 'Tại sao bạn luôn...' tested well three
times, don't overuse a fourth time in next 5 episodes."

This is the structured replacement for `data/ledger.md`. The ledger's job
(anti-duplication check before writing a new script, per `CLAUDE.md` §"Ngách
& series") becomes a query against episodic memory instead of a human
re-reading a markdown file.

### 2.3 Semantic Memory (domain knowledge)

Scope: durable, project-independent knowledge about the niche, audience,
and content rules — not tied to any one episode.

Contents: niche-gate rules (the "0c"/"0d" gates referenced in
`.claude/skills/youtube-ideation/video-quality-rules.md`), audience
preference patterns learned over time, voice/B-roll style guides, mechanism
taxonomies the channel has built up ("loss aversion," "cognitive
dissonance," etc., each with prior episode references).

This is the layer where the channel's accumulated "house style" lives —
it should outlive any single provider swap or pipeline rewrite.

## 3. Storage

| Memory type | Storage | Rationale |
|---|---|---|
| Working memory | JSON file embedded in `project.json` under `memory.working` | Travels with the project artifact; no extra moving part for the common case (single active project). |
| Episodic memory | SQLite (`data/memory.db`, table `episodic_memory`) | Structured, queryable, supports filtering by date/topic/status without loading every past `project.json`. |
| Semantic memory | SQLite (`data/memory.db`, table `semantic_memory`) + embeddings in the same DB (`sqlite-vec` or a sibling `.npy`/`.faiss` file) | Needs similarity search (§6), which JSON files cannot do efficiently. |
| Hot cache (optional) | Redis, key prefix `ytb:memory:` | Only used when the listener daemon is running continuously and repeated SQLite reads of frequently-accessed semantic facts become a measured bottleneck. Never the source of truth — SQLite always is. |

Rationale for SQLite as the structured backbone: zero external service
dependency (offline-first, per `PROJECT_VISION.md` §2.1), single file,
already a de facto standard for local-first tools on macOS, trivial backup
(copy the file).

## 4. Memory Schema

```sql
CREATE TABLE episodic_memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL,
    stage       TEXT NOT NULL,        -- e.g. 'ideation', 'voiceover', 'render', 'publish'
    key         TEXT NOT NULL,        -- e.g. 'topic', 'narrative_angle', 'broll_style'
    value       TEXT NOT NULL,        -- JSON-encoded value
    embedding   BLOB,                  -- optional: float32 vector for semantic search (§6)
    created_at  TEXT NOT NULL,        -- ISO 8601 UTC
    expires_at  TEXT                  -- ISO 8601 UTC, NULL = never expires
);

CREATE INDEX idx_episodic_project ON episodic_memory(project_id);
CREATE INDEX idx_episodic_key ON episodic_memory(key);

CREATE TABLE semantic_memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    domain      TEXT NOT NULL,        -- e.g. 'niche_rule', 'audience_pattern', 'style_guide'
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,        -- JSON-encoded value
    embedding   BLOB,
    created_at  TEXT NOT NULL,
    expires_at  TEXT
);

CREATE INDEX idx_semantic_domain ON semantic_memory(domain);
```

`project_id`, `stage`, `key`, `value`, `created_at`, `expires_at` match the
field list specified for this document; `embedding` and `domain` are
additions required to satisfy §6 (semantic retrieval) and §2.3 (semantic
memory needs a namespace orthogonal to `project_id`).

`value` is always JSON-encoded text, never a native SQLite type, so a single
schema can hold heterogeneous payloads (a string, a list of strings, a
nested narrative-angle object) without a migration per new fact shape.

## 5. Use Cases

| Use case | Query |
|---|---|
| "Was this topic already covered?" | `SELECT * FROM episodic_memory WHERE key = 'topic' AND value LIKE '%<topic>%'` plus a semantic search pass (§6) to catch paraphrases the LIKE clause misses. |
| "Which B-roll style worked well?" | `SELECT * FROM episodic_memory WHERE key = 'broll_style' ORDER BY created_at DESC` cross-referenced with retention data if/when analytics ingestion exists. |
| "What mechanism taxonomy entries exist?" | `SELECT * FROM semantic_memory WHERE domain = 'mechanism_taxonomy'` |
| "Resume this project — what do we already know?" | Load `project.json.memory.working` directly; no SQLite query needed (working memory travels with the artifact). |

## 6. Cross-Session Memory

Memory must persist between independent `claude -p` invocations and between
machine restarts. This is satisfied structurally because:

- Episodic and semantic memory live in `data/memory.db`, a file on disk, not
  in-process state — any new process opens the same file.
- Working memory lives inside `project.json`, also a file on disk.
- No memory type may live only in an in-memory Python object that dies with
  the process. This is the specific defect being fixed: today, anything not
  written to `data/ledger.md` or `auto_state.json` by hand is lost the
  moment the `claude -p` session exits.

## 7. Memory Retrieval — Semantic Search

For "find similar past scripts" / "was this angle used before, even if
worded differently" queries, exact-match SQL is insufficient. Retrieval
therefore uses embedding-based similarity search:

1. On write, compute an embedding for the fact's `value` text using the
   project's configured local embedding model (consistent with
   `PROJECT_VISION.md` local-inference-priority — no cloud embedding API as
   the default path) and store it in the `embedding` BLOB column as a
   packed `float32` array.
2. On query, embed the query string with the same model, then compute
   cosine similarity against candidate rows (`domain`/`key`-filtered first
   to keep the candidate set small — SQLite has no native vector index, so
   similarity is computed in Python over a pre-filtered row set, not over
   the whole table).
3. Return top-k by similarity above a configured threshold (default `0.75`)
   ranked alongside any exact-match SQL hits, deduplicated by `id`.

This keeps the dependency footprint to "a local embedding model already
used elsewhere in the pipeline" rather than introducing a dedicated vector
database — appropriate at current data volumes (hundreds to low thousands
of episodic rows per channel). Re-evaluate (e.g., `sqlite-vec` extension or
a dedicated FAISS index file) only if retrieval latency or table size
becomes a measured problem.

## 8. Current State

- `data/ledger.md` — manual, human-edited markdown anti-duplication log.
  Read by a human/agent before writing a new script; no programmatic query
  surface, no semantic search, no expiry, no structure beyond free text.
- `auto_state.json` — queue/run state consumed by
  `src/ytb_pipeline/orchestrator/batch_cli.py` and the listener daemon.
  This is operational state (what's queued, what's running), not memory in
  the sense defined here — it is closer to `25-CHECKPOINT_SYSTEM.md`'s
  concern and should migrate there, not into `data/memory.db`.

## 9. Migration Path

1. **Phase A (additive, no behavior change).** Introduce `data/memory.db`
   with the schema in §4. Write a one-time import script that parses
   `data/ledger.md` entries into `episodic_memory` rows (`stage='ideation'`,
   `key='topic'`). Keep `data/ledger.md` as the human-readable view,
   generated *from* the DB going forward (DB becomes source of truth, the
   markdown file becomes a rendered export for human review).
2. **Phase B.** Wire ideation's anti-duplication check
   (`.claude/skills/youtube-ideation/`) to query `episodic_memory` first,
   falling back to the markdown ledger only if the DB is unavailable.
3. **Phase C.** Add embedding column population and semantic search (§6)
   once a local embedding model is already wired for another pipeline need
   (avoid introducing an embedding dependency solely for memory — reuse).
4. **Phase D.** Add `semantic_memory` population for niche-gate rules and
   style guides currently hardcoded in
   `.claude/skills/youtube-ideation/video-quality-rules.md`; the skill file
   remains the authoring surface, semantic memory becomes the queryable,
   versioned mirror.
5. **Phase E.** Retire `auto_state.json` into the checkpoint system
   (`25-CHECKPOINT_SYSTEM.md`) once that system exists, so "memory" and
   "checkpoint" stop being conflated in one ad-hoc file.

No phase requires deleting `data/ledger.md` outright — it is downgraded from
source-of-truth to generated artifact, preserving the human review habit the
project already relies on.
