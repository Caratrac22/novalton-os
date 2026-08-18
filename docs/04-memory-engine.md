# Novalton OS — Memory Engine

> Version: 0.2 — 19 August 2026
>
> Status: Foundational draft

## 1. Purpose

The Memory Engine is responsible for preserving, structuring, retrieving, versioning, contextualizing, and exposing information across Novalton OS.

Its goal is not to claim perfect or literally infinite memory. Its goal is to provide **durable, traceable, scoped, temporally-aware memory** that remains useful over long periods without silently turning assumptions into facts.

Novalton OS deliberately separates machine-oriented memory from human-oriented knowledge navigation.

The selected architecture is:

```text
PostgreSQL
  -> authoritative structured memory
  -> entities
  -> relations
  -> temporal versions
  -> provenance
  -> policy metadata

Object / File Storage
  -> original documents
  -> raw source payloads
  -> large artifacts

Qdrant
  -> semantic/vector retrieval index

Full-text Search
  -> lexical/exact retrieval

Obsidian Vault
  -> human-readable knowledge layer
  -> editable Markdown notes
  -> backlinks / graph / navigation
  -> synchronized through Obsidian Bridge
```

**PostgreSQL remains the source of truth for structured memory.**

**Qdrant remains an index, not authoritative storage.**

**Obsidian is the human knowledge interface and editable mirror, not the sole authoritative database.**

---

# 2. Core principle

Novalton OS must distinguish between:

```text
WHAT WAS SAID
WHAT WAS OBSERVED
WHAT WAS INFERRED
WHAT IS CURRENTLY BELIEVED
WHAT IS NO LONGER CURRENT
```

A derived belief must never silently replace the source that created it.

Conceptually:

```text
Source Data
   |
   v
Extraction
   |
   +--> Facts
   +--> Entities
   +--> Events
   +--> Decisions
   +--> Preferences
   +--> Constraints
   +--> Assumptions
   |
   v
Structured Memory (PostgreSQL)
   |
   +--> Versioning
   +--> Confidence
   +--> Provenance
   +--> Scope
   +--> Relationships
   |
   +--> Qdrant / Full-text indexes
   |
   +--> Obsidian Bridge
             |
             v
       Human-readable Vault
```

---

# 3. Memory layers

## 3.1 Source Memory

Stores original evidence:

- user conversations;
- agent reports;
- uploaded documents;
- emails;
- calendar events;
- web research references;
- project notes;
- code review outputs;
- policy decisions;
- workflow events;
- action logs.

Source Memory is the foundation of provenance.

## 3.2 Structured Memory

Stores normalized knowledge optimized for machines and agents.

Examples:

```text
Entity: Client Dupont
Fact: preferred contact method = email
Decision: project uses PostgreSQL
Constraint: monthly API budget = 5 EUR
Event: contract reviewed on 2026-08-18
```

## 3.3 Derived Memory

Contains:

- summaries;
- embeddings;
- topic clusters;
- relationship hypotheses;
- inferred preferences;
- compressed project context;
- generated timelines.

Derived memory must preserve provenance where practical.

## 3.4 Operational Memory

Contains active workflow state, approvals, checkpoints, temporary context, and current tool results.

## 3.5 Episodic Memory

Represents significant events over time, such as project launches, failures, customer complaints, important decisions, and user corrections.

## 3.6 Semantic Memory

Represents stable facts and concepts such as project architecture, client identity, recurring constraints, company rules, and user preferences.

## 3.7 Human Knowledge Layer

The Obsidian vault exposes a curated human-readable representation of relevant memory.

It may contain:

- client pages;
- project pages;
- decision logs;
- meeting notes;
- timelines;
- architecture notes;
- operational lessons;
- manually written notes;
- links between related entities.

The human layer is intentionally readable and editable without requiring direct database access.

---

# 4. Memory scopes

Possible scopes:

```text
PLATFORM
WORKSPACE
USER
PROJECT
CLIENT
AGENT
TASK
WORKFLOW
SESSION
DOCUMENT_SET
```

Every retrieval and mutation must respect scope.

A Developer working on Project A must not automatically receive unrelated Client B context merely because the vector similarity is high.

---

# 5. Knowledge states

Suggested states:

```text
CONFIRMED_FACT
OBSERVED_FACT
INFERENCE
HYPOTHESIS
DISPUTED
OBSOLETE
UNKNOWN
```

A user-edited Obsidian note does not automatically convert every sentence inside it into `CONFIRMED_FACT`.

The ingestion pipeline must classify what changed and preserve provenance.

---

# 6. Provenance

Every significant memory should answer:

> Where did this come from?

Possible provenance types:

```text
USER_STATEMENT
TOOL_OBSERVATION
DOCUMENT
EMAIL
WEB_SOURCE
AGENT_RESULT
SYSTEM_EVENT
DERIVED_FROM_MEMORY
MANUAL_EDIT
OBSIDIAN_EDIT
OBSIDIAN_NOTE
```

A derived memory may reference several sources.

An Obsidian edit must retain:

- note path;
- note revision/hash;
- editor identity when available;
- timestamp;
- affected structured memories;
- whether the change was automatically accepted or required validation.

---

# 7. Temporal memory and corrections

When information changes, previous values normally remain in history.

Example:

```text
Old value
  -> valid_to set
  -> OBSOLETE

New value
  -> valid_from set
  -> ACTIVE
```

Corrections should preserve the correction relationship rather than silently destroying the old record.

If a user modifies an Obsidian note from:

```text
Preferred contact: email
```

to:

```text
Preferred contact: phone
```

Novalton should detect the semantic change and prepare a structured memory mutation rather than blindly rewriting unrelated records.

---

# 8. Contradiction handling

Contradictions are preserved and surfaced.

The system should:

1. detect possible conflict;
2. preserve both sources;
3. determine whether one supersedes the other;
4. mark `DISPUTED` if unresolved;
5. ask for clarification when consequences are important.

An Obsidian edit can therefore create a contradiction rather than automatically winning.

Example:

```text
Email source: launch Friday
Obsidian note: launch Monday

=> conflict detected
=> ask whether the note intentionally supersedes the email-derived memory
```

---

# 9. Memory ingestion pipeline

```text
New Source / Tool Result / Obsidian Edit
   |
   v
Source Storage
   |
   v
Parsing
   |
   v
Candidate Extraction
   |
   +--> entities
   +--> facts
   +--> events
   +--> decisions
   +--> preferences
   +--> constraints
   +--> assumptions
   |
   v
Validation / Classification
   |
   v
Deduplication / Conflict Detection
   |
   v
Structured Storage (PostgreSQL)
   |
   +--> Full-text index
   +--> Qdrant embeddings
   +--> Obsidian projection update
```

LLMs may propose candidate memories, but high-impact facts must not become authoritative merely because an LLM emitted confident prose.

---

# 10. Memory write authority

Agents and Obsidian edits may propose memory changes.

Conceptual validator output:

```text
ACCEPT
ACCEPT_AS_INFERENCE
REQUIRE_REVIEW
REJECT
```

Examples:

```text
User manually changes project title in a managed Obsidian field
→ likely ACCEPT

User writes "Client probably hates long meetings"
→ ACCEPT_AS_INFERENCE or REQUIRE_REVIEW

Agent claims legal status without a reliable source
→ REQUIRE_REVIEW
```

The Policy Engine may require confirmation for sensitive or high-impact memory changes.

---

# 11. Obsidian Bridge

The **Obsidian Bridge** synchronizes Novalton Memory with an Obsidian vault.

Its purpose is to provide a human-readable second-brain interface without sacrificing structured memory integrity.

Conceptually:

```text
              Novalton Memory Engine
               /                \
              /                  \
     PostgreSQL                 Obsidian Bridge
         |                           |
         |                           v
         |                      Markdown Vault
         |                           |
         +<----- validated edits ----+
```

The bridge has two directions.

## 11.1 Novalton -> Obsidian

Novalton may create or update Markdown notes from structured memory.

Examples:

```text
Clients/Dupont.md
Projects/Novalton OS.md
Decisions/ADR-like decision notes
People/Alex.md
Lessons/Developer.md
```

Generated notes should contain stable machine identifiers in frontmatter.

Example:

```yaml
---
novalton_entity_id: client_123
novalton_type: client
workspace_id: ws_default
managed_by: novalton
last_sync: 2026-08-19T00:30:00Z
---
```

This allows renames and folder moves without losing entity identity.

## 11.2 Obsidian -> Novalton

When a managed note changes, the bridge detects the diff and classifies it.

Possible outcomes:

```text
Formatting-only change
→ no structured memory change

Free-form note addition
→ ingest as source memory

Managed factual field changed
→ propose structured mutation

Large ambiguous rewrite
→ require review / simulation

Deletion
→ do not automatically destroy structured memory unless policy allows
```

The bridge must never use Markdown text as an unrestricted direct database write API.

---

# 12. Managed vs free-form Obsidian content

To avoid synchronization chaos, notes may distinguish:

```text
MANAGED CONTENT
FREE-FORM CONTENT
```

Example:

```markdown
# Client Dupont

## Novalton Summary
<!-- novalton:managed:start -->
Preferred contact: email
Active project: Website redesign
<!-- novalton:managed:end -->

## My Notes
Called him Tuesday. Mentioned a possible mobile app later.
```

Managed sections may be regenerated by Novalton.

Free-form sections belong to the user and should not be overwritten by automatic sync.

Free-form content may still be indexed as source memory.

---

# 13. Obsidian sync conflicts

The bridge must detect concurrent edits.

Example:

```text
PostgreSQL value changed at T2
Obsidian note independently changed from stale T1 state at T3
```

The system should not silently choose one.

Possible resolution:

```text
AUTO_MERGE_SAFE
KEEP_DATABASE
KEEP_OBSIDIAN
MANUAL_REVIEW
```

For important facts, the default should be `MANUAL_REVIEW` when intent is ambiguous.

---

# 14. Obsidian as source memory

Human-written Obsidian notes are legitimate memory sources.

They may be indexed through:

- full-text search;
- embeddings;
- entity links;
- extracted facts;
- timestamps;
- tags;
- backlinks.

However, raw notes remain distinct from structured facts derived from them.

This preserves the foundational rule:

> Source and interpretation are separate.

---

# 15. Backlinks and relationships

Obsidian links such as:

```markdown
[[Client Dupont]]
[[Project Website Redesign]]
```

may inform entity relationships.

They should be treated as user-authored relationship evidence, not magical ground truth.

Novalton may also generate backlinks based on known structured relations.

No graph database is required for V1; relationships can remain in PostgreSQL while Obsidian provides a useful visual graph for the human.

---

# 16. Retrieval architecture

A context request may combine:

1. structured PostgreSQL lookup;
2. entity lookup;
3. full-text search;
4. Qdrant semantic search;
5. temporal lookup;
6. relationship traversal;
7. relevant Obsidian free-form notes;
8. policy filtering;
9. reranking.

The output is a minimal structured context package, not a dump of the entire vault.

---

# 17. Context packages

Example:

```json
{
  "summary": "The project uses FastAPI and PostgreSQL.",
  "facts": [],
  "decisions": [],
  "constraints": [],
  "relevant_events": [],
  "relevant_notes": [],
  "sources": [],
  "contradictions": [],
  "operational_lessons": []
}
```

Obsidian notes may appear in `relevant_notes`, while promoted structured facts appear separately.

---

# 18. General Personal Context

The Personal Assistant receives broad synthesized context, not a raw vault dump.

It may include:

- active projects;
- priorities;
- deadlines;
- relevant preferences;
- recent decisions;
- unresolved issues;
- selected long-term context.

The Obsidian vault can contribute to this summary, subject to scope and sensitivity rules.

---

# 19. Summarization and compaction

Long-running projects use layered summaries while preserving source data.

```text
Raw events / notes
   |
Daily summaries
   |
Project summaries
   |
Current state
```

Obsidian may display these summaries, but generated summaries must remain linked to supporting source IDs.

---

# 20. Forgetting, archival and deletion

Possible states:

```text
ACTIVE
LOW_PRIORITY
ARCHIVED
OBSOLETE
DELETED
```

Forgetting means lowering retrieval priority, not necessarily deleting data.

User and legal deletion requirements override default retention.

Deleting an Obsidian note alone must not automatically imply legal deletion of all corresponding structured/source memory.

If the user explicitly requests true deletion, the Memory Engine handles the appropriate cascade and invalidates derived indexes.

---

# 21. Sensitive memory

Sensitivity levels may include:

```text
PUBLIC
INTERNAL
PERSONAL
CONFIDENTIAL
SECRET
```

Sensitivity affects:

- which agents may retrieve memory;
- whether content may be projected into Obsidian;
- whether content may leave the machine for cloud models;
- logging;
- summaries;
- retention;
- encryption.

Highly sensitive records may be excluded from the vault entirely or represented by a redacted placeholder.

---

# 22. Cloud vs local model privacy

Before retrieved memory is sent to a cloud model, Novalton evaluates its `model_access` policy.

Example:

```yaml
model_access:
  local: allow
  cloud: require_confirmation
```

Obsidian visibility does not automatically imply cloud-model permission.

---

# 23. Operational Lessons

Operational Lessons remain versioned structured records with provenance, scope, confidence, lifecycle, and origin run.

Relevant lessons may also be projected into human-readable Obsidian pages, for example:

```text
Lessons/Developer.md
Lessons/Project-Novalton-OS.md
```

Editing a lesson in Obsidian creates a proposed lesson revision rather than silently rewriting runtime behavior.

---

# 24. Workflow checkpoints

Checkpoints live in operational memory and are not primarily Obsidian content.

They support:

- crash recovery;
- worker replacement;
- model escalation;
- pause/resume;
- avoiding repeated work.

A human-readable workflow summary may be mirrored into Obsidian, but low-level checkpoint payloads remain machine storage.

---

# 25. Deduplication and entity resolution

Repeated ingestion must not create endless duplicates.

Entity resolution may use:

- stable IDs;
- names;
- domains;
- email addresses;
- known relationships;
- Obsidian frontmatter IDs;
- user confirmation;
- model-assisted matching.

Obsidian file names are labels, not authoritative entity identifiers.

Renaming `Dupont.md` must not create a new client if the stable ID remains unchanged.

---

# 26. Storage architecture direction

The authoritative architecture for V1 is:

```text
PostgreSQL
  authoritative structured knowledge

File/Object Storage
  original sources and large artifacts

Qdrant
  semantic retrieval index

Full-text Search
  lexical retrieval

Obsidian Vault
  human-readable/editable knowledge workspace

Obsidian Bridge
  synchronization + diff + validation + provenance
```

This avoids forcing one technology to solve every problem.

---

# 27. Embeddings

Embeddings are indexes, not facts.

They can be regenerated when models or chunking strategies change.

Obsidian notes and raw documents may be embedded, but the vector representation never becomes authoritative truth.

---

# 28. Memory simulation

Simulation applies to major memory changes.

Examples:

> If I delete this source, which memories lose provenance?

> If I merge these two client entities, what changes?

> If I accept this Obsidian edit, which structured facts will be updated?

> If I resync this vault, which files will Novalton modify?

Before a high-impact Obsidian import or sync repair, Novalton should show a preview.

Example:

```text
Obsidian Sync Simulation

12 notes unchanged
3 free-form notes will be indexed
2 structured facts will be updated
1 contradiction detected
0 deletions

[Apply] [Review changes] [Cancel]
```

---

# 29. Memory audit trail

Important events include:

```text
memory.created
memory.corrected
memory.superseded
memory.archived
memory.deleted
memory.scope_changed
memory.sensitivity_changed
obsidian.note_created
obsidian.note_changed
obsidian.sync_proposed
obsidian.sync_applied
obsidian.sync_conflict
obsidian.manual_resolution
```

Audit entries record actor, timestamp, reason, before/after state, and related workflow/run where applicable.

---

# 30. Memory integrity checks

Periodic checks should detect:

- memories without provenance;
- active facts whose source vanished;
- unresolved contradictions;
- duplicate entities;
- stale summaries;
- orphaned embeddings;
- invalid scopes;
- broken Obsidian entity IDs;
- managed notes diverging unexpectedly from PostgreSQL;
- deleted vault files with still-active structured entities;
- unsupported Operational Lessons.

Repairs should be proposed, not silently perform massive rewrites.

---

# 31. SaaS isolation

Every durable memory and every Obsidian projection must be workspace/tenant aware.

A future SaaS version may provide one logical vault per workspace or an equivalent isolated knowledge export.

Cross-tenant retrieval and cross-tenant vault synchronization are forbidden.

---

# 32. Failure behavior

Examples:

```text
Qdrant unavailable
→ structured + full-text fallback

Obsidian unavailable
→ core memory continues normally

Obsidian sync fails
→ queue retry / surface conflict

PostgreSQL unavailable
→ do not treat Obsidian as automatic authoritative failover

Conflicting memory found
→ surface contradiction
```

The system must continue to distinguish human-readable mirrors from authoritative structured state.

---

# 33. Initial V1 scope

V1 should include:

1. PostgreSQL-backed structured memory;
2. source records with provenance;
3. memory scopes;
4. temporal versioning;
5. obsolete/disputed states;
6. full-text retrieval;
7. Qdrant retrieval;
8. context package generation;
9. user correction support;
10. Operational Lessons;
11. workflow checkpoints;
12. audit logs;
13. sensitivity/cloud flags;
14. basic deduplication;
15. local Obsidian vault support;
16. Novalton -> Obsidian projection;
17. Obsidian -> Novalton change detection;
18. stable frontmatter IDs;
19. managed vs free-form content separation;
20. sync simulation before high-impact changes.

Advanced graph reasoning and sophisticated auto-merge can come later.

---

# 34. Invariants

1. Source and derived memory are distinct.
2. Assumptions are not facts.
3. Inferences are explicitly labeled.
4. Memory is scoped.
5. Sensitive access is policy-controlled.
6. PostgreSQL is the authoritative structured-memory store for V1.
7. Qdrant is an index, not authoritative memory.
8. Obsidian is a human knowledge layer, not an unrestricted database write interface.
9. Obsidian free-form text remains distinct from structured facts derived from it.
10. Managed Obsidian sections may be synchronized; free-form sections must not be overwritten automatically.
11. Obsidian edits that materially change structured knowledge pass validation.
12. Important ambiguous sync conflicts require review.
13. Stable entity IDs survive note/file renames.
14. Corrections preserve history where legitimate.
15. User/legal deletion requirements override retention.
16. Retrieved context is minimized.
17. Agents cannot grant themselves memory access.
18. Memory mutations are auditable.
19. Tenant isolation applies to every retrieval and sync path.
20. Loss of Obsidian must not disable core Novalton memory.

---

# 35. Open design questions

Later specifications must decide:

- exact PostgreSQL schemas;
- exact vault folder structure;
- frontmatter schema;
- file watcher implementation;
- debounce/change batching;
- conflict-resolution UX;
- whether Obsidian sync is filesystem-based or plugin-assisted;
- backup and restore strategy;
- chunking strategy;
- embedding model selection;
- full-text implementation;
- memory extraction model;
- automatic vs reviewed fact promotion;
- encryption strategy;
- secret-memory handling;
- General Personal Context refresh strategy;
- memory UI inside Novalton itself.

---

# 36. Next document

The next specification is `05-model-router.md`.

It should define:

- provider abstraction;
- free vs paid tiers;
- model capability registry;
- task-aware routing;
- Developer Manager recommendations;
- Orchestrator model selection;
- fallback behavior;
- technical retry vs intelligence escalation;
- user approval for stronger paid escalation;
- budget integration;
- provider health;
- context-window requirements;
- local-model support;
- privacy constraints;
- model evaluation history;
- watchdog integration.
