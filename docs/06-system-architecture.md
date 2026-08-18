# Novalton OS — System Architecture

> Version: 0.1 — 19 August 2026
>
> Status: Foundational draft

## 1. Purpose

This document defines how the major Novalton OS components fit together at runtime.

The architecture must support the current single-user local-first deployment while remaining structurally compatible with a future multi-user SaaS product.

The system should prioritize:

- clear trust boundaries;
- explicit authorization;
- observable workflows;
- replaceable AI providers;
- durable state;
- low operating cost;
- local-first development;
- future SaaS isolation;
- simple deployability;
- graceful degradation.

The goal is not to create the maximum possible number of services.

The goal is to separate responsibilities clearly enough that the system can evolve without becoming tightly coupled.

---

# 2. High-level architecture

Conceptually:

```text
                        USER
                         |
               Web / Desktop / Voice UI
                         |
                         v
                  API / Gateway Layer
                         |
                         v
                    Orchestrator
                  /      |       \
                 /       |        \
                v        v         v
        Policy Engine  Memory    Model Router
                         |            |
                         |            v
                         |       Model Providers
                         |       /      |      \
                         |   OpenRouter APIs   Voice Local
                         |
                         v
                   Agent Runtime
                  /     |      \
                 v      v       v
             Developer  QA    Other Agents
                 |
                 v
              Tool Layer
        /        |        |        \
     GitHub   Filesystem  Web    Other Tools

Persistence:
PostgreSQL + Qdrant + Object/File Storage + Obsidian Bridge

Runtime:
Event Bus + Worker Queue + Watchdog + Checkpoints
```

---

# 3. Architectural principle: modular monolith first

Novalton OS V1 should begin as a **modular monolith with independently bounded internal modules**, not as a large microservice mesh.

Recommended V1 deployment:

```text
Frontend
   |
Backend Application
   ├── API
   ├── Orchestrator
   ├── Policy Engine
   ├── Workflow Runtime
   ├── Agent Runtime
   ├── Model Router
   ├── Memory Service
   ├── Tool Gateway
   ├── Watchdog
   └── Event Gateway

External infrastructure
   ├── PostgreSQL
   ├── Qdrant
   ├── Redis
   ├── File/Object Storage
   └── Model / Tool providers
```

This allows clear internal boundaries without paying the operational cost of microservices before they are useful.

Modules may later be extracted into services when scaling, security, availability, or deployment constraints justify it.

---

# 4. Recommended technology direction

Initial preferred application stack:

```text
Frontend
- Next.js
- React
- TypeScript
- Tailwind CSS
- shadcn/ui or equivalent component system

Backend
- Python
- FastAPI
- Pydantic
- async I/O where useful

Primary database
- PostgreSQL

Vector retrieval
- Qdrant

Runtime coordination / cache
- Redis

Real-time transport
- WebSocket or Server-Sent Events depending on event type

Deployment
- Docker containers
- Docker Compose initially
- Proxmox host infrastructure
```

These are preferred implementation choices, not permanent product identity.

The architecture must keep business logic separated from framework-specific code where practical.

---

# 5. Frontend architecture

The frontend is the operational control surface for the user.

Primary UI areas should eventually include:

```text
Home / Command Center
Projects
Tasks / Workflows
Agents
Memory
Policies
Model Usage / Costs
Approvals
Activity / Audit
Settings
Voice
```

The frontend should never be the source of truth for workflow state or authorization.

It renders server-side state and submits user actions.

Important UI features:

- real-time run progress;
- plan visualization;
- approval cards;
- agent tree visualization;
- watchdog events;
- model escalation proposals;
- cost visibility;
- memory provenance;
- policy simulation;
- workflow pause/stop controls;
- artifact previews.

---

# 6. API and Gateway Layer

The API layer provides controlled entry into Novalton OS.

Responsibilities:

- authentication;
- authorization context construction;
- request validation;
- workspace/tenant resolution;
- rate limiting where required;
- API versioning;
- event-stream authentication;
- request correlation IDs;
- audit metadata.

The API layer must not bypass the Policy Engine merely because the request came directly from the user interface.

User authority is high, but sensitive actions should still be represented explicitly and audibly.

---

# 7. Orchestrator

The Orchestrator is the central coordination component.

It is responsible for:

- understanding user objectives;
- proposing workflow plans;
- selecting agents/capabilities;
- coordinating domain managers;
- evaluating structured agent outputs;
- modifying workflow plans visibly;
- consulting the Policy Engine;
- consulting the Model Router;
- requesting user approval when required;
- handling agent disagreements;
- reacting to watchdog events;
- deciding whether to continue, retry, adapt, or stop.

The Orchestrator may use an LLM, but deterministic system rules remain outside that LLM.

The Orchestrator must persist enough state that a backend restart does not destroy an active workflow.

---

# 8. Workflow Runtime

The Workflow Runtime executes approved plans.

It manages:

- workflow state;
- steps;
- dependencies;
- parallel branches;
- agent runs;
- worker creation;
- checkpoints;
- retries;
- cancellation;
- pause/resume;
- compensation/rollback metadata;
- budget counters;
- plan revisions.

A workflow is modeled as a durable directed graph rather than a transient chain of prompts.

Example:

```text
Research
   |
   v
Architecture
   |
   +--------+
   |        |
   v        v
Backend   Frontend
   |        |
   +---+----+
       |
       v
       QA
       |
       v
   User Review
```

---

# 9. Agent Runtime

The Agent Runtime creates and supervises Agent Runs from stable Agent Definitions.

Responsibilities:

- prepare task context;
- retrieve scoped memory;
- request model routing;
- construct prompts;
- expose allowed tools;
- validate structured outputs;
- emit runtime events;
- collect token/cost metrics;
- persist run history;
- create bounded child workers when approved;
- submit proposed actions to the Policy Engine.

Agent code should never directly contain provider API assumptions where avoidable.

---

# 10. Policy Engine

The Policy Engine is the authorization boundary for actions.

It evaluates:

```text
subject
+ action
+ resource
+ scope
+ user rules
+ workspace rules
+ agent permissions
+ workflow approval state
+ risk
+ temporary grants
+ expiration
```

Possible outputs:

```text
ALLOW
ALLOW_WITH_LOG
REQUIRE_CONFIRMATION
BLOCK
```

The Policy Engine should remain deterministic wherever practical.

LLMs may propose or parse policies, but they do not become the security boundary.

---

# 11. Model Router

The Model Router chooses models using the live Model Catalog Service.

Inputs include:

- requested capabilities;
- task difficulty;
- context requirement;
- privacy constraints;
- model availability;
- provider health;
- historical performance;
- remaining budget;
- latency requirements;
- structured output/tool support.

Routing priority:

```text
Sufficient quality
>
Cost
>
Speed
>
Provider preference
```

Free model candidates are restricted by configuration.

Current free candidates may include approved entries such as DeepSeek V4 Flash Free and NVIDIA Nemotron 3 Ultra Free while they remain present and valid in the live catalog.

The system must never depend on static model names remaining available forever.

---

# 12. Model Catalog Service

The Model Catalog Service maintains the current model inventory.

Each entry may include:

```yaml
model_id: provider/model
provider: ...
status: available
pricing:
  input: ...
  output: ...
context_window: ...
capabilities:
  - reasoning
  - coding
  - tool_use
  - structured_output
privacy_class: cloud
last_verified_at: ...
```

Catalog data may come from:

- provider APIs;
- provider metadata endpoints;
- trusted manually configured overrides;
- benchmark/performance history.

A model unknown to the active catalog cannot be selected for execution merely because an LLM mentioned it.

---

# 13. Memory Engine

The Memory Engine is the knowledge layer defined in `04-memory-engine.md`.

It coordinates:

- source memory;
- structured memory;
- derived memory;
- episodic memory;
- operational lessons;
- memory scopes;
- provenance;
- temporal versions;
- contradictions;
- retrieval;
- context package construction.

The Memory Engine should be accessible through a service interface rather than direct database queries from agents.

This preserves access control and future implementation flexibility.

---

# 14. PostgreSQL role

PostgreSQL is the initial authoritative data store for structured Novalton state.

It may store:

- users;
- workspaces;
- projects;
- tasks;
- workflows;
- workflow steps;
- approvals;
- policies;
- agent definitions;
- agent runs;
- model catalog metadata;
- model execution history;
- budgets;
- entities;
- structured memories;
- provenance;
- temporal versions;
- audit events;
- checkpoints metadata.

PostgreSQL should be treated as a durable system-of-record, not merely a cache.

---

# 15. Qdrant role

Qdrant is a semantic retrieval index.

It may contain embeddings for:

- memory chunks;
- documents;
- agent lessons;
- project notes;
- user notes;
- summaries.

Qdrant is **not** the authoritative source of truth.

If Qdrant becomes unavailable, Novalton OS should continue with reduced retrieval quality using PostgreSQL/full-text/source indexes.

---

# 16. Redis role

Redis may support temporary/runtime concerns such as:

- queues;
- distributed locks;
- event fan-out;
- short-lived cache;
- rate counters;
- provider health state;
- concurrency leases;
- workflow wakeups.

Durable business state should not live only in Redis.

A Redis loss must not erase the authoritative workflow record.

---

# 17. File and Object Storage

Large and raw artifacts should not necessarily live directly inside PostgreSQL.

Examples:

- uploaded PDFs;
- source documents;
- screenshots;
- large tool outputs;
- generated reports;
- audio recordings when retention is allowed;
- workflow artifacts;
- archived logs.

V1 may use filesystem-backed storage on the local server.

The storage abstraction should later allow S3-compatible object storage for SaaS deployment.

Database records should retain metadata, ownership, sensitivity, and provenance references.

---

# 18. Obsidian Bridge

Obsidian is the human-readable second-brain layer, not the canonical structured database.

Architecture:

```text
                   Memory Engine
                  /             \
                 v               v
          PostgreSQL          Qdrant
                 |
                 v
          Obsidian Bridge
             /       \
            v         v
     Managed Notes   User Notes
            \         /
             v       v
           Obsidian Vault
```

The bridge supports:

- export of structured knowledge to Markdown;
- import/indexing of user-written notes;
- stable memory/entity IDs in frontmatter;
- controlled edits to managed fields;
- conflict detection;
- change previews;
- memory simulation;
- provenance preservation.

Manual Obsidian edits that would alter authoritative structured memory must pass validation and applicable policy checks.

Obsidian being offline must not prevent core Novalton workflows from operating.

---

# 19. Tool Gateway

Agents do not call arbitrary integrations directly.

All action-capable tools should be exposed through a Tool Gateway or equivalent abstraction.

Examples:

```text
GitHub
Filesystem
Terminal
Web search
Browser
Email
Calendar
Documents
Databases
External SaaS APIs
```

The Tool Gateway handles:

- tool registration;
- capability metadata;
- authentication references;
- parameter validation;
- policy enforcement hooks;
- audit logging;
- timeout handling;
- idempotency metadata;
- result normalization.

Tool credentials must never be embedded directly inside agent prompts.

---

# 20. Plugin and Connector architecture

Novalton OS should support integrations through a registry rather than hard-coded direct dependencies.

Conceptually:

```text
Plugin Registry
   |
   +--> GitHub Connector
   +--> Gmail Connector
   +--> Calendar Connector
   +--> Files Connector
   +--> Custom MCP Connector
   +--> Future CRM Connector
```

A plugin definition should describe:

- identity;
- actions;
- read/write nature;
- authentication requirements;
- input/output schemas;
- risk metadata;
- version;
- provider health.

The Policy Engine remains authoritative regardless of plugin source.

---

# 21. Event Runtime

Novalton OS requires a structured event layer for real-time observability and internal coordination.

Examples:

```text
workflow.created
workflow.plan_approved
workflow.step_started
workflow.plan_changed
agent_run.started
agent_run.model_selected
agent_run.tool_started
agent_run.challenge_raised
watchdog.warning
watchdog.run_stopped
model.escalation_requested
approval.requested
approval.resolved
memory.updated
policy.blocked
workflow.completed
```

Events should have stable schemas and correlation IDs.

The UI may subscribe to event streams through WebSocket/SSE.

Events shown to the user describe operational progress, not private chain-of-thought.

---

# 22. Runtime Watchdog

The Watchdog is an independent runtime safety and quality component.

It observes Agent Runs and workflow activity for signals such as:

- repeated identical outputs;
- repeated tool calls without progress;
- repeated API errors;
- excessive duration;
- abnormal token usage;
- invalid structured outputs;
- repeated plan loops;
- stalled workers;
- recursive delegation problems;
- context incoherence;
- repeated contradictions.

The Watchdog should not rely solely on an LLM judging itself.

Signals may be derived from deterministic metrics plus optional model-based evaluation.

Possible interventions:

```text
WARN
RETRY
RESTART_FROM_CHECKPOINT
SWITCH_EQUIVALENT_MODEL
STOP_AGENT_RUN
REQUEST_MODEL_ESCALATION
ASK_USER
STOP_WORKFLOW
```

Technical recovery may occur automatically within configured limits.

Intelligence escalation to a stronger/more expensive model requires user approval according to the established model-routing policy.

---

# 23. Checkpoint architecture

Checkpoints are durable recovery points.

A checkpoint may reference:

- workflow state;
- completed steps;
- pending steps;
- agent output;
- artifacts;
- source snapshot references;
- selected model;
- tool side effects;
- budget state;
- plan version.

Checkpoints should be created at meaningful boundaries rather than after every token.

Examples:

```text
Before high-impact tool action
After worker completes a deliverable
Before model escalation
Before long parallel fan-out
After user approval
```

A restarted worker should resume from the latest safe checkpoint where practical.

---

# 24. Pause and Stop semantics

Two controls exist.

## Pause

Pause requests a safe freeze.

The runtime should:

- stop launching new steps;
- allow currently atomic operations to settle where needed;
- create a checkpoint;
- persist the paused state;
- release resources where possible.

## Stop

Stop requests termination as quickly as safely possible.

The runtime should:

- cancel cancelable model requests;
- cancel pending tasks;
- prevent new tool actions;
- attempt to stop child runs;
- persist cancellation state;
- record incomplete side effects.

External actions that already completed cannot magically be undone. Compensation/rollback must be explicit.

---

# 25. Model escalation flow

Example:

```text
Worker running on cheap/free model
        |
        v
Watchdog / Manager detects insufficient reasoning
        |
        v
Current run stopped at safe checkpoint
        |
        v
Model Router proposes stronger available model
        |
        v
Cost + reason + expected benefit shown
        |
        v
USER APPROVAL REQUIRED
        |
        +--> reject -> continue cheaper / stop / alternative
        |
        +--> approve
                |
                v
        New Agent Run from checkpoint
```

The replacement run should receive relevant previous outputs but not blindly inherit corrupted reasoning traces.

---

# 26. Context Coherence Guard

Memory compression is useful only if the model still understands the task.

A Context Coherence Guard should verify that context construction preserves:

- objective;
- current plan;
- critical constraints;
- unresolved decisions;
- relevant artifacts;
- agent responsibility;
- key assumptions;
- conflicting information;
- latest validated state.

If a context package becomes too compressed or ambiguous, the runtime should retrieve additional source context or route to a model with a larger context capacity.

The system should avoid repeatedly summarizing summaries until meaning is lost.

Source links should remain available for rehydration.

---

# 27. Voice architecture

Voice is a first-class input/output channel but not a separate authority system.

Conceptually:

```text
Microphone
   |
Wake Word / Activation
   |
Local STT
   |
Transcript
   |
Normal Novalton API / Orchestrator
   |
Policy Engine
   |
Workflow / Answer
   |
TTS
   |
Speaker
```

Local models are preferred primarily for voice processing.

Voice commands use the same policies, approvals, memory scopes, and audit rules as typed commands.

A voice command cannot bypass confirmation merely because the user spoke it.

Voice confirmation flows should protect against accidental activation and ambiguous transcription for high-risk actions.

---

# 28. Local V1 deployment on Proxmox

A sensible initial deployment may use the existing Proxmox server for persistent services.

Conceptually:

```text
Proxmox Host
|
├── Novalton App container/VM
|    ├── FastAPI backend
|    ├── workflow runtime
|    └── event gateway
|
├── PostgreSQL
|
├── Qdrant
|
├── Redis
|
└── optional storage / monitoring services
```

The development workstation may run:

- frontend dev server;
- backend dev instance;
- local voice models;
- code-generation tooling;
- debugging tools.

Production-like persistent state should preferably remain on the server rather than depending on the development laptop being powered on.

---

# 29. Networking and access

Core infrastructure services should not be exposed directly to the public internet.

Recommended pattern:

```text
Internet / LAN
      |
Reverse Proxy / Secure Access Layer
      |
Novalton Web/API
      |
Internal Network
      +--> PostgreSQL
      +--> Qdrant
      +--> Redis
```

PostgreSQL, Redis, and Qdrant should normally be reachable only from trusted internal application networks.

Future SaaS deployments may use managed equivalents while retaining the same logical boundaries.

---

# 30. Secrets architecture

Secrets require a dedicated strategy.

Examples:

- provider API keys;
- GitHub tokens;
- email OAuth credentials;
- webhook secrets;
- database passwords.

Requirements:

- never store secrets in prompts;
- never place secrets in normal memory;
- encrypt secrets at rest;
- scope secret access;
- expose credentials to tools only at execution time;
- log secret references, not values;
- support key rotation.

V1 may use environment/secrets files protected by deployment controls, but the architecture should later support a proper secrets manager.

---

# 31. Authentication and identity

Even a single-user V1 should model identity explicitly.

Core entities should include at least:

```text
User
Workspace
Membership
Role
Service Identity
Agent Identity
```

This avoids having to redesign every table when SaaS multi-user support arrives.

Agents and automated components should have service identities distinct from human users in audit records.

---

# 32. SaaS-ready tenant isolation

Future SaaS support requires tenant isolation from the beginning.

Every tenant-owned durable record should carry a tenant/workspace identifier.

Isolation must apply to:

- SQL queries;
- vector retrieval;
- object/file paths;
- Redis keys;
- tool credentials;
- event streams;
- audit logs;
- background jobs;
- memory retrieval;
- agent context construction.

The user interface must never be relied upon as the isolation boundary.

---

# 33. Observability

Novalton OS should have first-class operational observability.

Metrics may include:

- active workflows;
- agent run duration;
- model tokens;
- estimated and actual cost;
- retry rate;
- watchdog interventions;
- model escalation rate;
- provider errors;
- tool errors;
- policy blocks;
- memory retrieval latency;
- queue depth;
- API latency.

Logs should use structured records and correlation IDs.

Sensitive payload logging should be minimized.

---

# 34. Audit architecture

Audit records should answer:

```text
Who?
What?
When?
Why?
Under which workflow?
Under which policy version?
Using which agent/model/tool?
What was the result?
```

Important actions include:

- user approvals;
- policy changes;
- model escalations;
- external writes;
- memory mutations;
- secret access;
- workflow cancellations;
- watchdog stops;
- tool failures.

Audit records should be append-oriented and difficult for normal agents to modify.

---

# 35. Failure domains and graceful degradation

Novalton should remain useful when optional components fail.

Examples:

```text
Qdrant unavailable
→ use PostgreSQL/full-text retrieval

Obsidian unavailable
→ core memory continues

One model provider unavailable
→ Model Router considers another approved provider

Redis unavailable
→ fail safe, reconstruct runtime state from PostgreSQL where possible

One worker fails
→ parent manager/orchestrator handles retry or replacement

Frontend disconnects
→ workflow may continue if policy allows; state remains durable
```

Loss of an optional component should not silently weaken policy enforcement.

---

# 36. Background jobs

Some work does not require direct request/response execution.

Examples:

- memory indexing;
- Obsidian synchronization;
- embedding generation;
- model catalog refresh;
- provider health checks;
- integrity scans;
- stale summary refresh;
- scheduled workflows;
- cleanup and archival.

These should use a background job mechanism with durable job state where important.

Jobs must retain workspace context and policy boundaries.

---

# 37. API boundaries between modules

Even inside the modular monolith, internal modules should communicate through explicit interfaces.

Examples:

```text
Orchestrator -> WorkflowService
Orchestrator -> PolicyService
AgentRuntime -> MemoryService
AgentRuntime -> ModelRouter
AgentRuntime -> ToolGateway
Watchdog -> RuntimeControlService
ObsidianBridge -> MemoryService
```

Agents must not reach directly into PostgreSQL tables or bypass services to save implementation effort.

That shortcut is cheap for a week and expensive for the following three years.

---

# 38. Repository structure direction

A possible monorepo structure:

```text
novalton-os/
├── apps/
│   ├── web/
│   └── api/
│
├── packages/
│   ├── schemas/
│   ├── ui/
│   └── shared-types/
│
├── backend/
│   ├── orchestrator/
│   ├── workflows/
│   ├── agents/
│   ├── policy/
│   ├── memory/
│   ├── models/
│   ├── tools/
│   ├── watchdog/
│   ├── events/
│   └── infrastructure/
│
├── integrations/
│   ├── obsidian/
│   └── connectors/
│
├── infra/
│   ├── docker/
│   └── migrations/
│
├── docs/
└── tests/
```

The exact layout may change once implementation begins.

The important rule is responsibility separation, not folder aesthetics.

---

# 39. Testing architecture

Testing should exist at several levels.

```text
Unit tests
- policy evaluation
- routing scores
- memory classification
- workflow transitions

Contract tests
- model providers
- tools/connectors
- event schemas

Integration tests
- PostgreSQL
- Qdrant
- Redis
- workflows

Scenario tests
- user -> workflow -> agents -> tools -> result

Failure tests
- provider outage
- looping model
- tool timeout
- corrupted output
- restart recovery
- policy conflict
```

The Tester/QA agent may help generate and execute tests, but automated CI remains independent of the model's opinion that its own work is probably excellent.

---

# 40. Security boundaries

Core trust boundaries include:

```text
User input
Model output
Tool execution
External provider
Stored memory
Plugin/connector
Tenant boundary
Secret store
```

Anything generated by a model should be treated as untrusted input until validated for the operation being performed.

Structured output schemas reduce ambiguity but do not create authorization.

The Policy Engine and tool execution layer remain the enforcement boundary.

---

# 41. V1 architecture scope

V1 should implement the minimum architecture needed to validate the product:

1. Next.js/React frontend;
2. FastAPI backend;
3. PostgreSQL;
4. Qdrant;
5. Redis where runtime coordination benefits from it;
6. durable workflow engine;
7. Orchestrator;
8. Agent Runtime;
9. Policy Engine;
10. Model Router + live catalog;
11. Memory Engine;
12. Tool Gateway;
13. Watchdog;
14. WebSocket/SSE progress events;
15. checkpoints and restart recovery;
16. Obsidian Bridge MVP;
17. local voice pipeline MVP;
18. Docker deployment on Proxmox.

Features should be implemented incrementally rather than attempting the whole diagram in the first commit.

---

# 42. Suggested implementation phases

A practical order:

```text
Phase A
Core schemas + PostgreSQL + API foundation

Phase B
Workflow Runtime + events + approval system

Phase C
Model Router + Agent Runtime + one Developer agent

Phase D
Tool Gateway + GitHub/filesystem tools

Phase E
Policy Engine enforcement

Phase F
Memory Engine + Qdrant retrieval

Phase G
Watchdog + checkpoints + recovery

Phase H
QA and multi-agent delegation

Phase I
Obsidian Bridge

Phase J
Voice
```

Exact sequencing may change based on implementation discoveries.

---

# 43. Invariants

The following architectural rules should remain true:

1. The Orchestrator coordinates; it does not bypass policy.
2. The Policy Engine is not implemented only as a prompt.
3. Agents do not directly own provider credentials.
4. Agents do not directly query unrestricted memory stores.
5. PostgreSQL is the initial authoritative structured store.
6. Qdrant is an index, not truth.
7. Obsidian is a human-facing knowledge layer, not canonical structured truth.
8. Workflow state is durable.
9. Agent Runs are isolated and auditable.
10. Model providers are replaceable.
11. Model availability comes from a live catalog.
12. Model escalation to a stronger/more expensive tier requires the configured user approval.
13. Tool calls pass through authorization.
14. Real-time UI events do not expose private chain-of-thought.
15. Runtime failures must not silently weaken policy enforcement.
16. Tenant/workspace identity exists from V1.
17. Durable state is not stored only in Redis.
18. Secrets are separate from ordinary memory.
19. Context compression must preserve coherence and source rehydration paths.
20. Local AI is used primarily for voice unless future hardware/use cases justify expansion.

---

# 44. Open design questions

Later specifications should decide:

- exact authentication implementation;
- exact queue/background-job technology;
- WebSocket vs SSE split;
- database schema details;
- PostgreSQL row-level security strategy for SaaS;
- object storage implementation;
- secret manager implementation;
- connector SDK format;
- MCP support boundaries;
- exact watchdog thresholds;
- model catalog refresh interval;
- deployment backup strategy;
- production monitoring stack;
- frontend information architecture;
- voice STT/TTS models;
- remote access strategy for the local deployment.

---

# 45. Next document

The next specification should define the **user interface and interaction model**.

`07-interface.md` should cover:

- command center;
- projects/tasks;
- workflow graph;
- agents and workers;
- real-time progress;
- approvals;
- watchdog alerts;
- policy simulation;
- model escalation UX;
- memory explorer;
- Obsidian links;
- costs;
- activity/audit;
- responsive/mobile behavior;
- voice interaction surfaces.
