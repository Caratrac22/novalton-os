# Novalton OS — Memory Engine

> Version: 0.1 — 19 August 2026
>
> Status: Foundational draft

## 1. Purpose

The Memory Engine is responsible for preserving, structuring, retrieving, versioning, and contextualizing information across Novalton OS.

Its purpose is not to claim perfect or literally infinite memory.

Its purpose is to provide **durable, traceable, scoped, temporally-aware memory** that remains useful over long periods without silently turning assumptions into facts.

The Memory Engine must support:

- raw source preservation;
- structured facts and entities;
- temporal versioning;
- provenance;
- confidence and uncertainty;
- contradiction handling;
- semantic retrieval;
- full-text retrieval;
- relationship-aware retrieval;
- project/user/client scoping;
- summarized context;
- operational lessons;
- archival and compaction;
- auditability.

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
Structured Memory
   |
   +--> Versioning
   +--> Confidence
   +--> Provenance
   +--> Scope
   +--> Relationships
   |
   v
Indexes / Summaries / Embeddings
   |
   v
Context Retrieval
```

---

# 3. Memory layers

The Memory Engine is divided into logical layers.

## 3.1 Source Memory

Source Memory stores the original evidence from which later memory may be derived.

Examples:

- user conversations;
- agent reports;
- project notes;
- uploaded documents;
- emails;
- calendar events;
- web research references;
- code review outputs;
- policy decisions;
- workflow events;
- action logs.

Source data should be preserved whenever legally and technically appropriate.

Source Memory is the foundation of traceability.

## 3.2 Structured Memory

Structured Memory stores normalized knowledge extracted from sources.

Examples:

```text
Entity: Client Dupont
Fact: preferred contact method = email
Decision: project uses PostgreSQL
Constraint: monthly API budget = 5 EUR
Preference: user prefers concise status updates
Event: contract draft reviewed on 2026-08-18
```

Structured memory is optimized for reasoning and retrieval.

## 3.3 Derived Memory

Derived Memory contains information generated from one or more sources.

Examples:

- summaries;
- embeddings;
- topic clusters;
- relationship hypotheses;
- inferred preferences;
- compressed project context;
- generated timelines.

Derived memory must retain provenance wherever practical.

## 3.4 Operational Memory

Operational Memory supports active workflows.

Examples:

- current workflow state;
- current task state;
- active approvals;
- active checkpoints;
- temporary agent context;
- current tool results.

Operational Memory may have shorter retention than durable business memory.

## 3.5 Episodic Memory

Episodic Memory represents significant events over time.

Examples:

- a project launch;
- a failed deployment;
- a customer complaint;
- a successful workflow;
- an important decision;
- a user correction.

Episodic Memory helps the system reason about history, sequence, and recurrence.

## 3.6 Semantic Memory

Semantic Memory represents stable facts and concepts.

Examples:

- project architecture;
- client identity;
- preferred tools;
- company policies;
- recurring constraints;
- user preferences.

---

# 4. Memory scopes

Every memory item belongs to one or more scopes.

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

Scope prevents unrelated agents and workflows from receiving irrelevant or sensitive context.

Example:

```yaml
scope:
  workspace_id: ws_default
  project_id: novalton-os
  user_id: user_alex
```

The Memory Engine should prefer the narrowest scope that still preserves future usefulness.

---

# 5. Memory item model

A conceptual memory record may contain:

```yaml
memory_id: mem_01JABC
memory_type: fact
scope:
  workspace_id: ws_default
  project_id: novalton-os
subject: project.database
predicate: uses
value: PostgreSQL
status: active
confidence:
  level: high
provenance:
  - source_id: src_123
    relation: directly_stated
valid_from: 2026-08-18T14:20:00Z
valid_to: null
created_at: 2026-08-18T14:20:05Z
updated_at: 2026-08-18T14:20:05Z
```

The exact schema will be designed later.

---

# 6. Knowledge states

Novalton OS must explicitly distinguish knowledge states.

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

## 6.1 Confirmed fact

A fact explicitly provided by an authoritative source or directly confirmed by the user.

## 6.2 Observed fact

A fact directly observed by a trusted tool or system.

Example:

> GitHub reports that the default branch is `main`.

## 6.3 Inference

A conclusion produced from one or more facts.

Example:

> The client probably prefers short meetings because the last three meetings ended early.

This must not be stored as a confirmed preference unless validated.

## 6.4 Hypothesis

A weaker proposition requiring verification.

## 6.5 Disputed

Two credible memories or sources conflict.

## 6.6 Obsolete

The information was once valid but is no longer current.

---

# 7. Provenance

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
```

Example:

```json
{
  "memory_id": "mem_42",
  "value": "PostgreSQL",
  "provenance": [
    {
      "source_id": "msg_184",
      "type": "USER_STATEMENT",
      "relation": "direct"
    }
  ]
}
```

A derived memory may point to several source memories.

---

# 8. Temporal memory and versioning

Memory is not timeless.

When information changes, Novalton OS should preserve history.

Example:

```text
2026-08-01
Project hosting = local only

2026-09-15
Project hosting = local + cloud
```

The old value should normally become `OBSOLETE`, not be physically erased.

Conceptually:

```text
Memory Version 1
valid_from = T1
valid_to = T2
status = obsolete

Memory Version 2
valid_from = T2
valid_to = null
status = active
```

This allows questions such as:

- What is true now?
- What was true last month?
- When did this decision change?
- Who changed it?
- Why?

---

# 9. Contradiction handling

Contradictions must be preserved and surfaced, not silently flattened.

Example:

```text
Source A: Client wants launch Friday
Source B: Client asks to postpone until Monday
```

The Memory Engine should:

1. detect possible conflict;
2. store both sources;
3. determine whether one supersedes the other;
4. mark disputed state if unresolved;
5. ask for clarification when important.

Conceptual representation:

```yaml
status: disputed
conflicts_with:
  - mem_102
  - mem_118
```

The Orchestrator may be informed when a retrieved context contains unresolved contradictions.

---

# 10. Corrections

User corrections have high importance.

If the user says:

> No, that is wrong. The client prefers phone calls.

Novalton OS should not merely append another sentence.

It should:

- preserve the old memory and its source;
- mark it as corrected/obsolete or disputed as appropriate;
- create the new memory;
- record the correction relationship;
- reduce future retrieval priority of the incorrect memory.

Correction events should be valuable training signals for Operational Lessons.

---

# 11. Memory ingestion pipeline

A typical ingestion pipeline:

```text
New Source
   |
   v
Source Storage
   |
   v
Content Parsing
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
Structured Storage
   |
   v
Indexing / Embeddings / Search
```

LLMs may help extract candidates, but they are not trusted to silently write high-confidence facts without validation rules.

---

# 12. Write policy

Not every sentence deserves long-term memory.

The Memory Engine should classify candidate memories by expected future utility.

Possible retention classes:

```text
EPHEMERAL
SESSION
SHORT_TERM
DURABLE
CRITICAL
```

Examples:

```text
"The build is currently running"
→ EPHEMERAL

"Project X uses FastAPI"
→ DURABLE

"Never send customer emails without confirmation"
→ CRITICAL / Policy Engine
```

Policies themselves belong to the Policy Engine but may be indexed in memory for contextual awareness.

---

# 13. Memory importance

Memory ranking should not depend solely on semantic similarity.

Candidate scoring may consider:

- scope match;
- semantic relevance;
- explicit importance;
- recency;
- frequency of use;
- source authority;
- confidence;
- current/obsolete state;
- relationship to active entities;
- user pinning;
- task relevance.

Conceptually:

```text
Retrieval Score
= semantic relevance
+ scope relevance
+ temporal relevance
+ authority
+ importance
- obsolescence penalty
- contradiction penalty
```

Exact weights should remain implementation details and tunable.

---

# 14. Retrieval pipeline

A context request may include:

```json
{
  "query": "What does the Developer need to know about authentication?",
  "workspace_id": "ws_default",
  "project_id": "novalton-os",
  "agent_id": "developer.default",
  "task_id": "task_456",
  "max_context_tokens": 12000
}
```

The Memory Engine may combine:

1. exact structured lookup;
2. entity lookup;
3. full-text search;
4. semantic/vector search;
5. timeline search;
6. relationship traversal;
7. source-quality filtering;
8. policy-based filtering;
9. reranking.

The output should contain the **smallest useful context**, not the largest possible dump.

---

# 15. Context packages

Agents should receive structured context packages.

Example:

```json
{
  "summary": "The project uses FastAPI and PostgreSQL. Authentication is JWT-based.",
  "facts": [],
  "decisions": [],
  "constraints": [],
  "relevant_events": [],
  "sources": [],
  "contradictions": [],
  "operational_lessons": []
}
```

Context generation must respect agent permissions and memory scopes.

---

# 16. General Personal Context

The Personal Assistant receives a broad but synthesized context, as defined in the Agent Model.

This context may include:

- active projects;
- current priorities;
- important deadlines;
- relevant preferences;
- recent important decisions;
- unresolved issues;
- selected long-term goals.

It should not contain unrestricted raw email, files, or sensitive data unless required and allowed.

The General Personal Context should be refreshed incrementally when important information changes.

---

# 17. Summarization and compaction

Long-running projects may generate enormous histories.

The system should use layered summarization rather than deleting source data.

Example:

```text
Raw events
   |
Daily summary
   |
Weekly/project summary
   |
Current project state
```

Summaries are derived memories.

They must not become the sole copy of important information.

When a summary is generated, Novalton OS should preserve links to supporting source ranges or source IDs where practical.

---

# 18. Source retention vs active context

"Never delete source memory" is a product philosophy, not an absolute rule against all deletion.

The system may need deletion because of:

- user request;
- privacy requirements;
- legal obligations;
- storage policy;
- secret exposure;
- tenant deletion.

Therefore:

> Source information should be preserved by default while it is legitimate and useful to do so, but user and legal deletion requirements override retention.

Derived memory depending on deleted sources must be invalidated, redacted, or recomputed as appropriate.

---

# 19. Forgetting and archival

Novalton OS should distinguish **forgetting from deletion**.

Forgetting means reducing retrieval priority while preserving historical data.

Possible states:

```text
ACTIVE
LOW_PRIORITY
ARCHIVED
OBSOLETE
DELETED
```

Example:

A trivial one-year-old debugging detail may be archived and excluded from default retrieval while remaining searchable.

Critical user preferences or decisions may remain highly ranked.

---

# 20. Memory decay

Some memories naturally lose relevance over time.

Examples:

- temporary priorities;
- short-lived preferences;
- debugging state;
- transient project assumptions.

A decay policy may reduce retrieval weight over time without changing truth status.

Stable facts should not decay merely because they are old.

Decay should depend on memory type and scope.

---

# 21. User control

The user must be able to inspect and manage memory.

Future UI actions should include:

```text
View memory
View source
Correct memory
Pin memory
Mark obsolete
Archive
Delete
Change scope
Change sensitivity
```

A user should be able to ask:

> Why do you remember this?

and receive the source/provenance chain.

---

# 22. Memory confidence

Confidence should be based on evidence characteristics, not model bravado.

Potential signals:

- directly confirmed by user;
- directly observed by trusted tool;
- number of independent sources;
- source authority;
- consistency;
- recency;
- extraction certainty;
- correction history.

Suggested semantic levels:

```text
VERY_HIGH
HIGH
MEDIUM
LOW
UNKNOWN
```

The system should not pretend numerical confidence is calibrated unless it actually is.

---

# 23. Sensitive memory

Memory records may be classified by sensitivity.

Example levels:

```text
PUBLIC
INTERNAL
PERSONAL
CONFIDENTIAL
SECRET
```

Sensitivity affects:

- which agents may retrieve the memory;
- whether it may be sent to cloud models;
- whether it may appear in logs;
- whether it may be included in summaries;
- encryption and retention behavior.

The Policy Engine participates in access decisions.

---

# 24. Cloud vs local model privacy

Before context is sent to a cloud model, the system should evaluate whether the selected memory is allowed to leave the local environment.

Possible memory flags:

```yaml
model_access:
  local: allow
  cloud: allow
```

or:

```yaml
model_access:
  local: allow
  cloud: require_confirmation
```

This enables future privacy-conscious workspaces without changing agent architecture.

---

# 25. Operational Lessons integration

Operational Lessons defined in the Agent Model are stored through the Memory Engine but use a specialized schema and lifecycle.

They must include:

- scope;
- provenance;
- originating run;
- validating actor;
- confidence;
- status;
- effective period;
- supersession links.

Operational Lessons should be retrieved only when relevant to the current task.

---

# 26. Workflow checkpoints

Workflow checkpoints are stored in operational memory.

A checkpoint may contain:

```yaml
checkpoint_id: chk_123
workflow_run_id: wf_456
step_id: step_backend
agent_run_id: run_789
status: recoverable
created_at: ...
artifacts:
  - file_patch_001
context_snapshot_ref: ctx_111
```

Checkpoints allow:

- recovery after crash;
- worker replacement;
- model escalation;
- safe pause/resume;
- avoiding repeated work.

---

# 27. Deduplication

Repeated ingestion must not create endless duplicate memories.

The system should detect:

- exact duplicates;
- near duplicates;
- equivalent facts;
- repeated source imports.

Deduplication must preserve provenance from all relevant sources.

Example:

Three documents all state the same company address.

The structured fact may exist once while referencing all three sources.

---

# 28. Entity resolution

The system must determine when two references describe the same entity.

Example:

```text
"Vannes Batteries"
"VANNES BATTERIES"
"the battery company"
```

Entity resolution may use:

- exact identifiers;
- names;
- domains;
- emails;
- relationships;
- user confirmation;
- model-assisted matching.

Ambiguous merges must not happen silently when consequences are significant.

---

# 29. Relationship memory

The Memory Engine should eventually support relationships between entities.

Examples:

```text
User -> owns -> Project
Project -> belongs_to -> Workspace
Client -> requested -> Feature
Decision -> affects -> Component
AgentRun -> produced -> Artifact
Memory -> derived_from -> Source
```

A graph database is not required for V1. Relationships may initially be modeled in PostgreSQL.

The architecture should not prevent graph-style traversal later.

---

# 30. Storage architecture direction

Initial preferred architecture:

```text
PostgreSQL
  -> structured memory
  -> entities
  -> relations
  -> temporal versions
  -> provenance
  -> metadata

Object/File Storage
  -> original documents
  -> large artifacts
  -> raw source payloads where appropriate

Vector Index
  -> semantic retrieval

Full-text Search
  -> exact / lexical retrieval
```

Qdrant may be used as the initial vector store, while PostgreSQL remains the source of truth for structured memory.

The vector database must **not** become the authoritative memory store.

---

# 31. Embeddings

Embeddings are retrieval indexes, not facts.

They may be regenerated when:

- embedding model changes;
- content changes;
- source is deleted;
- indexing strategy changes.

Memory correctness must never depend on preserving one specific embedding model forever.

---

# 32. Retrieval safety

Before retrieved memory reaches an agent, the Memory Engine should enforce:

- tenant scope;
- workspace scope;
- agent scope;
- sensitivity rules;
- model privacy rules;
- source validity;
- obsolescence handling;
- contradiction flags.

A high semantic similarity score does not override access policy.

---

# 33. Memory write authority

Agents may propose memory writes, but they should not freely declare durable facts.

Conceptual flow:

```text
Agent proposes memory
       |
       v
Memory Validator
       |
       +--> classify
       +--> check provenance
       +--> check scope
       +--> detect duplicates
       +--> detect conflicts
       |
       v
ACCEPT / ACCEPT_AS_INFERENCE / REQUIRE_REVIEW / REJECT
```

High-impact memories may require user review.

---

# 34. Memory audit trail

Important memory mutations must be auditable.

Examples:

```text
memory.created
memory.corrected
memory.superseded
memory.archived
memory.deleted
memory.scope_changed
memory.sensitivity_changed
memory.user_pinned
```

Audit events should record:

- actor;
- timestamp;
- reason;
- previous state;
- new state;
- associated workflow/run when relevant.

---

# 35. Memory simulation

The simulation philosophy from the Policy Engine can also be useful for memory operations.

Before a major memory operation, Novalton OS may preview effects.

Examples:

> If I delete this document, which memories become unsupported?

> If I merge these two client entities, what records will be affected?

> If I mark this preference obsolete, which workflows may change behavior?

Simulation should be required for high-impact bulk memory changes.

---

# 36. Memory integrity checks

The system should periodically detect memory problems.

Possible checks:

- memories without provenance;
- active facts whose source was deleted;
- unresolved contradictions;
- duplicate entities;
- invalid scopes;
- stale summaries;
- orphaned embeddings;
- unsupported Operational Lessons;
- references to deleted tenants/projects.

Integrity checks should produce repair proposals rather than silently rewriting large amounts of memory.

---

# 37. Memory quality metrics

Future observability may track:

- retrieval precision;
- correction rate;
- contradiction rate;
- source coverage;
- stale-memory rate;
- unsupported-memory rate;
- duplicate rate;
- average retrieval context size;
- memory hit usefulness;
- user correction frequency.

These metrics may improve retrieval and extraction over time.

---

# 38. Memory and SaaS isolation

Every durable memory record must be tenant/workspace aware from the beginning.

A future SaaS system must enforce strict tenant isolation at:

- database query level;
- vector index level;
- object storage level;
- cache level;
- logs;
- retrieval layer;
- background jobs.

Cross-tenant retrieval is never allowed merely because two records are semantically similar.

---

# 39. Failure behavior

If the Memory Engine cannot confidently resolve context, it should degrade safely.

Examples:

```text
No reliable memory found
→ report missing context

Conflicting memory found
→ surface contradiction

Source unavailable
→ mark source issue

Vector index unavailable
→ fall back to structured/full-text retrieval
```

Memory failure must not automatically become hallucinated context.

---

# 40. Initial V1 scope

V1 should prioritize reliability over sophistication.

Minimum V1 capabilities:

1. PostgreSQL-backed structured memory;
2. source records with provenance;
3. memory scopes;
4. versioning and obsolete state;
5. full-text retrieval;
6. vector retrieval through Qdrant;
7. context package generation;
8. contradiction flags;
9. user correction support;
10. Operational Lessons;
11. workflow checkpoints;
12. audit logs;
13. sensitive/cloud-allowed flags;
14. basic deduplication.

Advanced graph reasoning, automated memory decay scoring, and complex entity resolution may come later.

---

# 41. Invariants

The following rules should remain true:

1. Source and derived memory are distinct.
2. A summary never becomes the only copy of important source information by default.
3. Assumptions are not facts.
4. Inferences are explicitly labeled.
5. Memory is scoped.
6. Sensitive memory access is policy-controlled.
7. Historical truth is preserved through versioning where legitimate.
8. Corrections do not silently erase history.
9. Contradictions can remain unresolved.
10. Embeddings are indexes, not authoritative storage.
11. PostgreSQL is the initial source of truth for structured memory.
12. Agents cannot grant themselves memory access.
13. Durable agent-proposed memory passes validation.
14. Retrieved context is minimized to what is useful.
15. Old information is not automatically wrong merely because it is old.
16. Obsolete information is not treated as current.
17. User/legal deletion requirements override default retention.
18. Deleted-source derived memories must be reconsidered.
19. Memory mutations are auditable.
20. Tenant isolation applies to every retrieval path.

---

# 42. Open design questions

Later specifications must decide:

- exact PostgreSQL schemas;
- chunking strategy for documents;
- embedding model selection;
- whether embeddings run locally or via API;
- Qdrant collection layout;
- full-text search implementation;
- memory extraction model and prompts;
- automatic vs reviewed fact promotion;
- conflict-resolution scoring;
- memory retention defaults;
- encryption strategy;
- secret-memory handling;
- source deletion cascade behavior;
- exact General Personal Context refresh strategy;
- user-facing memory UI;
- backup and restore strategy.

---

# 43. Next document

The next specification should define the **Model Router**.

`05-model-router.md` should cover:

- provider abstraction;
- free vs paid model tiers;
- model capability registry;
- task-aware routing;
- Developer Manager recommendations;
- Orchestrator model selection;
- fallback behavior;
- technical retry vs intelligence escalation;
- user approval for expensive escalation;
- budget integration;
- provider health;
- context-window requirements;
- local-model support;
- privacy constraints;
- model evaluation history;
- watchdog integration.
