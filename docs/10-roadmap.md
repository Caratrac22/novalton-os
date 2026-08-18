# Novalton OS — Development Roadmap

> Version: 0.1 — 19 August 2026
>
> Status: Foundational implementation roadmap

## 1. Purpose

This document turns the Novalton OS architecture into an implementation order.

The roadmap is dependency-driven rather than feature-hype-driven.

Novalton OS should not begin by building every visible idea at once. The first objective is to create a trustworthy core that can execute one useful end-to-end workflow under policy, memory, model routing, audit, and user control.

The roadmap follows these principles:

1. build the trust/control layer before broad autonomy;
2. prove one vertical slice before multiplying agents;
3. prefer a modular monolith before distributed complexity;
4. preserve SaaS-compatible IDs/scopes from the beginning;
5. keep local/private execution possible;
6. make observability and audit first-class, not cleanup work;
7. avoid coupling the product to one model/provider;
8. add visual polish only after the underlying states are real;
9. use staged releases with explicit exit criteria;
10. keep V1 useful for a single user before building full enterprise administration.

---

# 2. Product target for V1

V1 is not the final enterprise SaaS.

V1 should be a **single-user/hybrid Novalton OS instance** capable of:

- receiving a user request in the Command Center;
- turning it into a visible workflow plan;
- selecting and running specialized agents;
- applying Policy Engine decisions;
- asking for confirmation where required;
- choosing models through the Model Router;
- tracking cost/usage;
- persisting structured memory with provenance;
- showing agent/workflow activity in real time;
- pausing/stopping workflows;
- recovering from technical failures where practical;
- maintaining an audit trail;
- supporting initial Obsidian synchronization;
- supporting a first local Voice Client after the text workflow is reliable.

V1 should already use conceptual scopes such as:

```text
tenant_id = tenant_local
workspace_id = workspace_default
user_id = user_owner
```

Full multi-user authentication is not required in V1.

---

# 3. Non-goals for initial V1

The following should **not** block the first useful release:

- full enterprise SSO;
- complete subscription billing;
- marketplace of third-party agents;
- mobile app;
- advanced graph database;
- multi-region cloud deployment;
- sophisticated speaker identification;
- dozens of agent roles;
- unrestricted autonomous action;
- complex collaborative document editor;
- production-grade public SaaS admin portal;
- perfect automatic entity resolution;
- perfect local model benchmarking across every hardware combination.

The architecture must permit these later without implementing them prematurely.

---

# 4. Roadmap overview

Recommended order:

```text
Phase 0  Repository + engineering foundation
   ↓
Phase 1  Core platform skeleton
   ↓
Phase 2  Policy + approvals
   ↓
Phase 3  Model Router + provider abstraction
   ↓
Phase 4  Agent runtime + first vertical workflow
   ↓
Phase 5  Memory Engine
   ↓
Phase 6  Reliable workflow runtime + watchdog
   ↓
Phase 7  Command Center V1
   ↓
Phase 8  Obsidian Bridge
   ↓
Phase 9  Local Node / Local Model Manager foundation
   ↓
Phase 10 Voice V1
   ↓
Phase 11 Hardening + internal alpha
   ↓
Phase 12 SaaS-ready foundations / V2 preparation
```

Phases may overlap slightly, but dependencies should remain respected.

---

# 5. Phase 0 — Repository and engineering foundation

## Goal

Create a development environment that can grow without becoming chaotic.

## Deliverables

Suggested repository shape:

```text
apps/
  web/
  api/
  node/             # Novalton Node later

packages/
  contracts/
  ui/
  sdk/

infra/
  docker/
  migrations/

scripts/

docs/
```

Initial engineering work:

- TypeScript frontend setup;
- Python/FastAPI backend setup;
- PostgreSQL development instance;
- Redis development instance;
- Qdrant development instance;
- Docker Compose for local infrastructure;
- environment configuration;
- secret handling conventions;
- structured logging;
- linting/formatting;
- backend tests;
- frontend tests;
- database migration tooling;
- CI baseline;
- shared API/event contract conventions.

## Exit criteria

Phase 0 is complete when:

- web and API boot reliably;
- API can connect to PostgreSQL/Redis/Qdrant;
- migrations run from a clean install;
- CI validates basic code quality/tests;
- developer setup is documented and repeatable.

---

# 6. Phase 1 — Core platform skeleton

## Goal

Represent the fundamental objects before implementing intelligence.

## Initial domain objects

At minimum:

```text
Tenant
Workspace
User
Project
Task
WorkflowPlan
WorkflowRun
WorkflowStep
AgentDefinition
AgentRun
ApprovalRequest
Policy
ModelDefinition
ModelRun
UsageEvent
AuditEvent
```

Even in single-user V1, objects should carry tenant/workspace scopes where applicable.

## Event layer

Define an initial event envelope:

```json
{
  "event_id": "evt_...",
  "type": "workflow.step.started",
  "tenant_id": "tenant_local",
  "workspace_id": "workspace_default",
  "timestamp": "...",
  "actor": "...",
  "payload": {}
}
```

Events must support:

- UI real-time updates;
- audit;
- debugging;
- future metering;
- runtime monitoring.

## Exit criteria

- domain entities persist;
- project/task CRUD works;
- events can be emitted and observed;
- real-time event delivery to a minimal frontend is demonstrated.

---

# 7. Phase 2 — Policy Engine and approvals

## Goal

Make authorization deterministic before agents receive meaningful power.

## Deliverables

Implement:

```text
ALLOW
ALLOW_WITH_LOG
REQUIRE_CONFIRMATION
BLOCK
```

Support initial policy scopes:

```text
TENANT
WORKSPACE
PROJECT
AGENT
TOOL
WORKFLOW
```

Implement:

- deterministic rule evaluation;
- rule priority/strictness;
- policy inheritance;
- action description input;
- approval request creation;
- approval resolution;
- expiration/cancellation;
- audit events;
- basic simulation endpoint.

Initial UI can be ugly but functional.

## Critical rule

No tool execution path should bypass Policy Engine once the tool layer exists.

## Exit criteria

A test action can be evaluated as:

```text
ALLOW
BLOCK
REQUIRE_CONFIRMATION
```

and confirmation actually gates execution rather than merely displaying a decorative popup.

---

# 8. Phase 3 — Model Router and provider abstraction

## Goal

Stop agents from depending on hard-coded model names or providers.

## Deliverables

Implement:

- provider adapter interface;
- model catalog schema;
- availability status;
- capability metadata;
- price metadata;
- context-window metadata;
- allowed/free-list policy;
- model selection request;
- model decision logging;
- usage/cost capture;
- bounded technical retry;
- provider fallback;
- user-approved intelligence escalation.

Initial free pool should follow the current product policy rather than being assumed permanently valid.

The runtime must validate candidates against the current Model Catalog before execution.

## Model evaluation history

Start collecting:

```text
model
agent role
task category
success/failure
latency
cost
watchdog interventions
user correction
QA result
```

Do not overfit routing on tiny sample counts.

## Exit criteria

The same logical agent request can run through two provider/model implementations without changing agent code.

---

# 9. Phase 4 — Agent runtime and first vertical slice

## Goal

Prove the central Novalton experience end-to-end with very few agents.

## Initial agents

Recommended first set:

```text
Orchestrator
Developer Manager
Developer Worker
QA Worker
```

Optionally add a generic Research Worker only if needed by the first workflow.

Do not implement every future department yet.

## First vertical slice

Recommended first real workflow:

> "Inspect a repository task, propose an implementation, perform the permitted change, run checks, and have QA review the result."

Conceptual flow:

```text
User
 ↓
Orchestrator creates plan
 ↓
Policy evaluation
 ↓
Developer Manager
 ↓
Developer Worker
 ↓
QA Worker
 ↓
Orchestrator synthesis
 ↓
User
```

The exact repository-write permissions may initially be constrained for safety.

## Structured contracts

Agent input/output must use the contracts defined by `01-agent-model.md`.

No uncontrolled free-form agent-to-agent chat is required.

## Exit criteria

One multi-agent workflow completes end-to-end with:

- visible plan;
- model choices;
- structured results;
- QA challenge;
- approval where required;
- audit events;
- final synthesis.

This is the first major product milestone.

---

# 10. Phase 5 — Memory Engine

## Goal

Make workflows improve through durable context without turning every sentence into eternal truth.

## Initial implementation

PostgreSQL should own structured memory.

Implement first:

- source records;
- memory records;
- scopes;
- provenance;
- fact/inference/hypothesis/obsolete states;
- temporal versions;
- corrections;
- contradiction links;
- full-text search;
- Qdrant indexing;
- hybrid retrieval;
- context package generation;
- sensitivity/model-access fields;
- basic dedupe;
- Operational Lessons records.

## Avoid initially

- advanced knowledge graph infrastructure;
- fully automatic entity merging;
- complicated decay algorithms.

## Exit criteria

A new workflow can retrieve relevant prior project facts, sources, corrections, and lessons without receiving unrelated memories.

---

# 11. Phase 6 — Reliable workflow runtime and watchdog

## Goal

Make longer workflows survivable.

## Deliverables

Implement:

- dependency graph execution;
- parallel independent steps;
- step state machine;
- checkpoints;
- idempotency strategy;
- retries;
- technical fallback;
- Pause;
- Stop;
- resume;
- crash recovery;
- worker replacement where possible;
- workflow plan revision events;
- budget checks;
- watchdog detectors.

Initial watchdog signals:

```text
repeated tool call
repeated model output
no meaningful progress
API error loop
invalid structured result
timeout
abnormal token usage
repeated contradiction
reasoning capability failure
```

## Exit criteria

Kill/restart the backend during a recoverable workflow and demonstrate that the run can resume from a checkpoint without blindly starting over.

---

# 12. Phase 7 — Command Center V1

## Goal

Turn the working backend into the Jarvis-style operating interface.

## Build functional state first

The first Command Center should include:

- Nova central console;
- active alerts;
- pending approvals;
- AI spend/usage;
- project selector;
- active workflow cards;
- real-time Kanban tasks;
- agent activity;
- notification center;
- command palette;
- workflow timeline;
- Pause/Stop controls.

## Orchestrator-managed home

The home layout may adapt based on current state, but the Orchestrator must choose from user-approved widget/layout capabilities rather than generate arbitrary unsafe UI.

User custom layout preferences override adaptive suggestions where configured.

## Visual polish order

1. information hierarchy;
2. responsiveness on desktop sizes;
3. animation system;
4. premium dark design;
5. Three.js enhancements.

Three.js should enhance states such as Nova listening/thinking/working, not carry critical functionality.

## Exit criteria

A user can operate the complete initial workflow without opening developer tools or database consoles.

---

# 13. Phase 8 — Obsidian Bridge

## Goal

Expose Novalton memory as a human-readable second brain.

## V1 bridge

Implement:

- generated Markdown views;
- stable frontmatter IDs;
- project/entity note generation;
- DB → Markdown synchronization;
- edit detection;
- Markdown → structured-memory proposal;
- diff preview;
- simulation;
- conflict detection;
- approval for impactful updates;
- rename handling;
- deletion/tombstone handling.

The database remains authoritative for structured memory.

## Exit criteria

A user can edit a managed note in Obsidian and receive a correct preview of the structured memory changes before applying them.

---

# 14. Phase 9 — Novalton Node and Local Model Manager foundation

## Goal

Create the local execution side of the hybrid architecture.

## Novalton Node V1

Start with a lightweight agent capable of:

- authenticating to the backend;
- maintaining an outbound secure connection;
- reporting hardware capabilities;
- receiving scoped jobs;
- executing approved local tools;
- returning structured results;
- emitting health/events;
- revoking itself cleanly.

## Node capability profiles

The Node should advertise capability, not assume performance.

Example:

```yaml
cpu: available
gpu:
  vendor: nvidia
  vram_mb: 4096
ram_mb: 16384
features:
  local_stt: possible
  local_tts: possible
  local_llm: constrained
```

A weak PC may operate as a **thin Node**:

```text
secure gateway
local file/tool access
minimal preprocessing
no heavy AI inference
```

Heavy work may execute on:

- another capable Node;
- private Novalton server;
- approved external provider.

## Local Model Manager V1

Implement the lifecycle primitives:

```text
catalog
compatibility check
download
verify
install
activate
test
update staging
rollback
uninstall
cleanup
```

Model families can initially focus on voice.

## Exit criteria

A Node can register itself, report hardware, install a compatible local model under user approval, and execute a local inference job.

---

# 15. Phase 10 — Voice V1

## Goal

Add voice only after text orchestration and policy control are trustworthy.

## V1 capabilities

Implement:

- wake word `Nova`;
- VAD;
- local French-capable STT;
- local/free TTS;
- Local Model Manager integration;
- ~3-second silence end-of-turn;
- continuous conversation;
- automatic return to listening when Nova expects a reply;
- barge-in;
- visible listening/thinking/speaking state;
- Daily Brief;
- UI approvals while discussing them by voice;
- Meeting/Class Mode;
- transcript segmentation;
- summary generation;
- task extraction as proposals only.

## Voice safety validation

Test explicitly:

- Nova's own TTS cannot command Nova;
- ambient media does not trivially trigger actions;
- uncertain destructive transcripts cause clarification;
- Meeting/Class Mode never treats ambient speech as user authorization.

## Exit criteria

The user can say:

> "Nova, fais-moi le brief d'aujourd'hui"

receive a spoken brief, discuss a pending approval, and complete the confirmation via UI without repeating the wake word.

---

# 16. Phase 11 — Hardening and internal alpha

## Goal

Use Novalton OS for real work before expanding scope.

## Alpha usage

Use the system on actual Novalton development tasks and selected low-risk workflows.

Collect:

- failures;
- confusing approvals;
- incorrect memory retrieval;
- model-routing mistakes;
- watchdog misses;
- excessive costs;
- UI friction;
- recovery failures;
- agent conflict patterns.

## Required hardening

- backup/restore;
- database migration discipline;
- secret rotation;
- audit review tools;
- rate limits;
- event retention policies;
- integration tests;
- chaos/failure tests;
- policy regression tests;
- memory integrity checks;
- performance profiling;
- security review of Node communication.

## Exit criteria

The system is trusted for repeated internal daily use without frequent manual database/code intervention.

---

# 17. Phase 12 — SaaS-ready V2 preparation

## Goal

Only after V1 is genuinely useful, begin the multi-user/productization layer.

## V2 preparation areas

- authentication;
- user sessions;
- organization membership;
- roles/permissions UI;
- tenant provisioning;
- workspace creation;
- Node enrollment flow;
- centralized admin console;
- feature flags;
- entitlement system;
- quota hierarchy;
- usage aggregation;
- billing adapter interface;
- self-service API-key management;
- tenant backup/deletion;
- enterprise audit export;
- SSO later.

## Metering

By this stage, V1 Usage Events should already exist.

V2 may connect the internal Usage Ledger to a specialized system such as an OpenMeter/Lago/Stripe adapter, but Novalton's core must remain provider-independent.

---

# 18. Recommended milestone releases

## M0 — Development Skeleton

```text
web + api + postgres + redis + qdrant + events
```

## M1 — Controlled Intelligence

```text
Policy Engine + approvals + Model Router
```

## M2 — First AI Team

```text
Orchestrator + Developer Manager + Developer + QA
```

This is the first demo-worthy milestone.

## M3 — Durable Brain

```text
Memory Engine + retrieval + provenance + Operational Lessons
```

## M4 — Reliable Runtime

```text
checkpoints + watchdog + pause/stop + recovery
```

## M5 — Novalton Command Center

```text
full desktop control surface + real-time workflow UX
```

This is the first strong product experience milestone.

## M6 — Human Second Brain

```text
Obsidian Bridge
```

## M7 — Hybrid Intelligence

```text
Novalton Node + Local Model Manager
```

## M8 — Nova Voice

```text
wake word + local STT/TTS + Daily Brief + Meeting/Class Mode
```

## M9 — Internal Alpha

```text
daily use + hardening
```

## M10 — SaaS V2 foundation

```text
multi-user + provisioning + quotas + admin
```

---

# 19. Build-order dependencies

Simplified dependency graph:

```text
Engineering Foundation
        |
        v
Domain + Event Core
        |
        +--------------------+
        |                    |
        v                    v
Policy Engine          Model Router
        |                    |
        +---------+----------+
                  |
                  v
            Agent Runtime
                  |
                  v
             Memory Engine
                  |
                  v
          Workflow Reliability
                  |
                  v
            Command Center
             /          \
            v            v
     Obsidian Bridge   Novalton Node
                         |
                         v
                 Local Model Manager
                         |
                         v
                      Voice
```

Some Memory work can begin earlier, but the first vertical workflow should not wait for the complete final memory design.

---

# 20. Development strategy for AI-assisted coding

Novalton itself will eventually assist development, but until then AI coding tools should be used with explicit scope.

Recommended workflow:

```text
Specification
   ↓
Small implementation task
   ↓
AI-generated patch
   ↓
Tests/static checks
   ↓
Review
   ↓
Commit
```

Avoid prompts like:

> "Build all Novalton OS."

Prefer bounded tasks such as:

> "Implement the PolicyDecision enum, policy evaluation contract, unit tests, and database migration described in section X. Do not implement the UI."

This makes AI-assisted development auditable and recoverable.

---

# 21. Definition of Done for core features

A feature is not done merely because the happy-path demo works.

Core features should generally have:

- typed/domain contract;
- persistence where required;
- tenant/workspace scope;
- Policy Engine integration where actions occur;
- events;
- audit where relevant;
- error behavior;
- tests;
- UI state if user-facing;
- documentation;
- no hard dependency on one model/provider unless explicitly intended.

---

# 22. Prioritization rule

When choosing between features, use this order:

```text
Trust / safety
Reliability
Core usefulness
Observability
Performance
Polish
Breadth
Novelty
```

A flashy new agent should not outrank fixing workflows that silently lose state.

---

# 23. What to build first after this roadmap

The next implementation-oriented specification should define the **actual repository skeleton and first development backlog**.

Recommended next document:

```text
docs/11-implementation-plan.md
```

It should turn Phase 0–4 into concrete issues/tasks such as:

- initialize `apps/web`;
- initialize `apps/api`;
- Docker Compose infrastructure;
- database schema baseline;
- event envelope;
- Policy Engine contracts;
- first approval API;
- model provider interface;
- model catalog;
- first Orchestrator contract;
- Developer/QA agent contracts;
- first vertical-slice workflow;
- test strategy;
- CI workflow;
- initial seed data.

The implementation plan should be small enough that coding can begin immediately after it is approved.

---

# 24. Invariants

1. Novalton OS is built as a modular monolith first.
2. Policy control precedes broad autonomous tool execution.
3. Model routing is provider/model independent.
4. One useful vertical slice precedes dozens of agents.
5. Structured memory uses PostgreSQL as its initial authority.
6. Qdrant remains a retrieval index, not the source of truth.
7. V1 remains single-user friendly while carrying future tenant/workspace scopes.
8. Full multi-user authentication is deferred to V2.
9. Mobile is deferred to V2.
10. Voice comes after reliable text orchestration.
11. TTS/STT should be local by default in Voice V1.
12. Local AI capability is hardware-dependent; weak Nodes remain useful as thin gateways.
13. Metering begins before billing integration.
14. Billing vendors remain replaceable adapters.
15. Three.js enhances the product but never becomes a core dependency.
16. Audit, events, and recovery are product features, not debugging leftovers.
17. Every milestone must have explicit exit criteria.
18. Internal real-world use precedes public SaaS expansion.
