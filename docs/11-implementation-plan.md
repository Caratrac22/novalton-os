# Novalton OS — Implementation Plan

> Version: 0.1 — 19 August 2026
>
> Status: Initial implementation blueprint

## 1. Purpose

This document converts the roadmap into the first concrete implementation sequence for the Novalton OS repository.

The goal is not to implement the entire product at once. The goal is to create a stable engineering foundation and then prove one end-to-end vertical slice under policy, model routing, audit, and user control.

The first implementation target is therefore:

```text
User request
  ↓
API
  ↓
Policy evaluation
  ↓
Model routing
  ↓
Agent runtime
  ↓
Structured result
  ↓
Audit + real-time event
  ↓
Minimal UI
```

Memory, watchdog, Obsidian, Node, local models, and voice come after this vertical slice is reliable.

---

# 2. Repository structure

Initial repository structure:

```text
novalton-os/
├── apps/
│   ├── web/
│   │   ├── src/
│   │   ├── public/
│   │   └── package.json
│   │
│   ├── api/
│   │   ├── app/
│   │   │   ├── api/
│   │   │   ├── core/
│   │   │   ├── domain/
│   │   │   ├── infrastructure/
│   │   │   ├── modules/
│   │   │   └── main.py
│   │   ├── tests/
│   │   └── pyproject.toml
│   │
│   └── node/
│       └── README.md
│
├── packages/
│   ├── contracts/
│   ├── ui/
│   └── sdk/
│
├── infra/
│   ├── docker/
│   ├── migrations/
│   └── compose.yaml
│
├── scripts/
├── docs/
├── .github/
│   └── workflows/
├── .env.example
├── README.md
└── Makefile
```

`apps/node` exists from the beginning as a placeholder, but Novalton Node is not implemented during the first phase.

---

# 3. Backend architecture

The backend should begin as a **modular monolith**.

Recommended internal layout:

```text
apps/api/app/
├── api/
│   ├── dependencies.py
│   └── v1/
│       ├── health.py
│       ├── projects.py
│       ├── tasks.py
│       ├── policies.py
│       ├── approvals.py
│       ├── models.py
│       ├── workflows.py
│       └── events.py
│
├── core/
│   ├── config.py
│   ├── database.py
│   ├── logging.py
│   ├── ids.py
│   ├── exceptions.py
│   └── security.py
│
├── domain/
│   ├── enums.py
│   ├── events.py
│   └── shared.py
│
├── infrastructure/
│   ├── postgres/
│   ├── redis/
│   ├── qdrant/
│   └── providers/
│
└── modules/
    ├── tenants/
    ├── workspaces/
    ├── projects/
    ├── tasks/
    ├── audit/
    ├── events/
    ├── policy/
    ├── approvals/
    ├── models/
    ├── agents/
    └── workflows/
```

Each module should preferably contain:

```text
models.py
schemas.py
repository.py
service.py
routes.py     # when applicable
```

The exact naming may evolve, but business logic must not be placed directly inside FastAPI route handlers.

---

# 4. Initial technology choices

## Backend

```text
Python 3.13.x (supported range: >=3.13,<3.14)
FastAPI
Pydantic v2
SQLAlchemy 2.x
Alembic
PostgreSQL 17.x
Redis
Qdrant
httpx
pytest
ruff
mypy or pyright later if useful
```

Async database access should be used where it materially simplifies concurrent workflow execution, but unnecessary async complexity should be avoided in pure domain logic.

## Frontend

```text
Node.js 24.x LTS
Next.js
React
TypeScript
Tailwind CSS
shadcn/ui
TanStack Query
Zod
```

Three.js / React Three Fiber should not be installed until the Command Center functional state exists.

## Infrastructure

V1 development infrastructure:

```text
PostgreSQL 17.x
Redis
Qdrant
```

via Docker Compose.

---

# 5. Default V1 identity scope

Even though V1 is single-user, every relevant record should support the future SaaS identity model.

Bootstrap identities:

```text
tenant_id    = tenant_local
workspace_id = workspace_default
user_id      = user_owner
```

These values may initially be seeded during database bootstrap.

They must not be scattered as hard-coded string literals across business logic.

Use a scoped request/context object.

Example:

```python
RequestScope(
    tenant_id="tenant_local",
    workspace_id="workspace_default",
    user_id="user_owner",
)
```

---

# 6. Initial database tables

The first migration should not create every future table.

It should establish the minimum platform skeleton.

## Phase A tables

### tenants

```text
id
name
status
created_at
updated_at
```

### workspaces

```text
id
tenant_id
name
status
created_at
updated_at
```

### users

```text
id
tenant_id
display_name
status
created_at
updated_at
```

Authentication fields are not required yet.

### projects

```text
id
tenant_id
workspace_id
name
description
status
created_at
updated_at
```

### tasks

```text
id
tenant_id
workspace_id
project_id
parent_task_id nullable
title
description
status
priority
created_at
updated_at
```

### audit_events

```text
id
tenant_id
workspace_id
event_type
actor_type
actor_id nullable
entity_type nullable
entity_id nullable
payload_json
created_at
```

### runtime_events

```text
id
tenant_id
workspace_id
event_type
actor_type
actor_id nullable
correlation_id nullable
payload_json
created_at
```

Runtime events and audit events may share infrastructure but should remain logically distinct.

---

# 7. IDs

Use globally unique application-generated identifiers.

Recommended shape:

```text
ten_...
ws_...
usr_...
prj_...
tsk_...
pol_...
apr_...
mdl_...
wfp_...
wfr_...
wfs_...
agd_...
agr_...
evt_...
aud_...
```

ULID or UUIDv7 are suitable implementation choices.

The public API should not depend on sequential database IDs.

---

# 8. Initial status enums

## Project

```text
ACTIVE
PAUSED
ARCHIVED
```

## Task

```text
BACKLOG
READY
IN_PROGRESS
BLOCKED
REVIEW
DONE
CANCELLED
```

## Generic execution

```text
PENDING
RUNNING
WAITING_APPROVAL
PAUSED
SUCCEEDED
FAILED
CANCELLED
```

Enums should be centralized and versioned deliberately rather than duplicated as arbitrary strings.

---

# 9. Phase A API endpoints

The first useful API should remain small.

## Health

```text
GET /api/v1/health
GET /api/v1/health/dependencies
```

Dependency health may report:

```text
postgres
redis
qdrant
```

without exposing credentials or sensitive internals.

## Projects

```text
POST   /api/v1/projects
GET    /api/v1/projects
GET    /api/v1/projects/{project_id}
PATCH  /api/v1/projects/{project_id}
```

## Tasks

```text
POST   /api/v1/tasks
GET    /api/v1/tasks
GET    /api/v1/tasks/{task_id}
PATCH  /api/v1/tasks/{task_id}
```

Deletion should not be prioritized initially. Archive/cancel states are safer and preserve auditability.

## Events

```text
GET /api/v1/events
GET /api/v1/events/stream
```

The first stream may use SSE. WebSockets can be introduced when bi-directional realtime communication is actually required.

---

# 10. Event envelope

All internal and external runtime events should use a common envelope.

Example:

```json
{
  "event_id": "evt_01...",
  "type": "task.updated",
  "tenant_id": "tenant_local",
  "workspace_id": "workspace_default",
  "timestamp": "2026-08-19T00:00:00Z",
  "actor": {
    "type": "user",
    "id": "user_owner"
  },
  "correlation_id": "req_01...",
  "payload": {}
}
```

Initial rules:

1. event types are stable strings;
2. payloads are JSON serializable;
3. tenant/workspace are always explicit when relevant;
4. secrets must not be included in event payloads;
5. emitted events may feed realtime UI, audit, watchdog, and metering later.

---

# 11. Audit foundation

Every important mutation should emit an audit event.

Initial examples:

```text
project.created
project.updated
task.created
task.updated
policy.created
policy.updated
approval.created
approval.resolved
model.selected
workflow.created
workflow.started
workflow.completed
```

Audit writes should be performed by application services, not manually by frontend clients.

---

# 12. Phase B — Policy Engine tables

After the platform skeleton is stable, add:

### policies

```text
id
tenant_id
workspace_id nullable
project_id nullable
agent_id nullable
name
description
priority
effect
conditions_json
status
created_by
created_at
updated_at
```

Effect enum:

```text
ALLOW
ALLOW_WITH_LOG
REQUIRE_CONFIRMATION
BLOCK
```

### approval_requests

```text
id
tenant_id
workspace_id
workflow_run_id nullable
agent_run_id nullable
action_type
action_summary
risk_json
status
expires_at nullable
created_at
resolved_at nullable
resolved_by nullable
resolution_note nullable
```

Approval status:

```text
PENDING
APPROVED
REJECTED
EXPIRED
CANCELLED
```

---

# 13. Policy Engine API

Initial endpoints:

```text
POST /api/v1/policies
GET  /api/v1/policies
POST /api/v1/policies/simulate
POST /api/v1/policy/evaluate

GET  /api/v1/approvals
GET  /api/v1/approvals/{approval_id}
POST /api/v1/approvals/{approval_id}/approve
POST /api/v1/approvals/{approval_id}/reject
```

`/policy/evaluate` should not become a public authorization bypass.

Internal execution services must call the same Policy Engine directly rather than trusting a client-side decision.

---

# 14. Policy evaluation contract

Input example:

```json
{
  "scope": {
    "tenant_id": "tenant_local",
    "workspace_id": "workspace_default",
    "project_id": "prj_123"
  },
  "actor": {
    "type": "agent",
    "id": "agd_developer"
  },
  "action": {
    "type": "repository.write",
    "resource": "github:Caratrac22/novalton-os",
    "risk": "medium"
  }
}
```

Output:

```json
{
  "decision": "REQUIRE_CONFIRMATION",
  "matched_policy_ids": ["pol_123"],
  "reason_codes": ["external_write_requires_confirmation"]
}
```

The deterministic result is authoritative.

An LLM may help explain the result to the user but does not determine the final effect.

---

# 15. Phase C — Model Router tables

Add:

### model_definitions

```text
id
provider
provider_model_id
display_name
status
context_window
capabilities_json
pricing_json
metadata_json
last_verified_at
created_at
updated_at
```

### model_runs

```text
id
tenant_id
workspace_id
agent_run_id nullable
model_definition_id
provider
input_tokens nullable
output_tokens nullable
estimated_cost nullable
latency_ms nullable
status
failure_code nullable
created_at
completed_at nullable
```

### usage_events

```text
id
tenant_id
workspace_id
project_id nullable
metric
quantity
unit
cost nullable
source_type
source_id
created_at
```

---

# 16. Model Catalog Service

The Model Catalog Service must be the source used by the Router when deciding which models actually exist and are available.

Responsibilities:

```text
refresh provider catalog
normalize provider metadata
track availability
track price/context/capabilities
track allowed/free policies
mark stale records
expose candidate queries
```

The Router must never execute a model ID proposed only in natural-language agent output unless that model exists in the current catalog and passes policy validation.

---

# 17. Model Router API/internal contracts

External diagnostic endpoints may include:

```text
GET  /api/v1/models
GET  /api/v1/models/{model_id}
POST /api/v1/models/refresh
POST /api/v1/models/route/simulate
```

Actual model selection should normally be an internal service call.

Routing request example:

```json
{
  "task_category": "code_review",
  "required_capabilities": ["reasoning", "code"],
  "context_tokens_estimate": 50000,
  "cost_policy": "prefer_free",
  "agent_role": "qa",
  "privacy": "external_provider_allowed"
}
```

Routing result:

```json
{
  "model_id": "mdl_...",
  "reason_codes": [
    "capabilities_match",
    "sufficient_context",
    "lowest_expected_cost"
  ],
  "requires_user_approval": false
}
```

---

# 18. Phase D — Agent runtime tables

Add:

### agent_definitions

```text
id
tenant_id
workspace_id nullable
name
role
description
capabilities_json
permissions_json
status
version
created_at
updated_at
```

### agent_runs

```text
id
tenant_id
workspace_id
agent_definition_id
workflow_run_id nullable
workflow_step_id nullable
parent_agent_run_id nullable
model_run_id nullable
status
input_json
result_json nullable
challenge_signal nullable
started_at nullable
completed_at nullable
created_at
```

---

# 19. Agent execution contract

Every agent invocation receives a structured request.

Example:

```json
{
  "objective": "Review the proposed backend change",
  "scope": {},
  "constraints": [],
  "context": {},
  "requested_output": "qa_review"
}
```

Every agent returns a structured result compatible with `01-agent-model.md`.

Minimum output:

```json
{
  "summary": "...",
  "findings": [],
  "artifacts": [],
  "sources": [],
  "assumptions": [],
  "risks": [],
  "uncertainties": [],
  "blocking_issues": [],
  "challenge": {
    "signal": "NONE",
    "reason": null
  },
  "recommended_next_steps": [],
  "requested_actions": []
}
```

Schema validation failure is an execution failure, not permission to accept malformed output silently.

---

# 20. Phase E — Workflow tables

Add:

### workflow_plans

```text
id
tenant_id
workspace_id
project_id nullable
created_by
status
objective
plan_json
created_at
updated_at
```

### workflow_runs

```text
id
tenant_id
workspace_id
workflow_plan_id
status
budget_json nullable
started_at nullable
completed_at nullable
created_at
```

### workflow_steps

```text
id
tenant_id
workspace_id
workflow_run_id
step_key
title
agent_definition_id nullable
depends_on_json
status
input_json
result_json nullable
started_at nullable
completed_at nullable
created_at
```

Full checkpoint/recovery tables may be introduced during the later reliability phase rather than prematurely.

---

# 21. First built-in agents

Seed only:

```text
Orchestrator
Developer Manager
Developer Worker
QA Worker
```

Do not create legal, commercial, personal assistant, research, marketing, finance, and dozens of other agents before the runtime proves itself.

The first goal is quality of coordination, not headcount.

---

# 22. First vertical workflow

First useful test workflow:

```text
User asks:
"Inspect this repository task and propose a safe implementation."
```

Initial execution:

```text
1. Orchestrator interprets objective.
2. Orchestrator creates WorkflowPlan.
3. Plan is displayed to user.
4. Policy Engine evaluates proposed actions.
5. Developer Manager decomposes technical work.
6. Model Router selects model for worker.
7. Developer Worker produces implementation proposal or patch.
8. QA Worker independently reviews it.
9. Orchestrator resolves findings.
10. User sees result, model usage, risks, and pending actions.
```

Repository writes should initially require confirmation.

---

# 23. Minimal frontend before Command Center

Do not build the full premium interface during platform bootstrap.

The initial frontend only needs:

```text
/                 basic status
/projects         project list
/tasks            simple kanban/list
/activity         realtime event stream
/approvals        approval inbox
/models           model catalog diagnostic view
/workflows        workflow list/detail
```

This interface exists to prove backend state.

The premium Command Center from `07-interface.md` replaces this progressively later.

---

# 24. Initial frontend state boundaries

Frontend should treat backend data as authoritative.

Use:

```text
TanStack Query → server state
local React state → transient UI state
```

Avoid duplicating the entire backend domain in a global client store.

Realtime events should invalidate/update cached server state rather than create a second hidden database in the browser.

---

# 25. Docker Compose foundation

`infra/compose.yaml` should initially define:

```text
postgres
redis
qdrant
```

API and web may initially run directly in developer mode outside Compose for faster iteration.

Later, optional profiles may containerize all components.

Required properties:

- named persistent volumes;
- healthchecks;
- predictable development ports;
- no production secrets committed;
- `.env.example` documentation.

---

# 26. Environment variables

Initial convention:

```text
NOVALTON_ENV=development
DATABASE_URL=...
REDIS_URL=...
QDRANT_URL=...
OPENROUTER_API_KEY=...
```

Actual secrets belong in `.env` or a secret manager, never Git.

Code should read provider credentials through a central configuration layer.

---

# 27. Logging

Structured JSON-compatible logging should exist from the beginning.

Useful fields:

```text
timestamp
level
service
request_id
correlation_id
tenant_id
workspace_id
workflow_run_id
agent_run_id
event
message
```

Never log raw API keys, auth tokens, or unrestricted sensitive prompts by default.

---

# 28. Correlation IDs

Every incoming API request should receive or generate a correlation/request ID.

That ID should propagate into:

- runtime events;
- audit events;
- agent runs;
- model runs;
- workflow events;
- logs.

This is critical for debugging multi-agent execution later.

---

# 29. Testing strategy

## Unit tests

Prioritize deterministic logic:

```text
policy precedence
policy inheritance
ID generation
state transitions
cost calculations
routing candidate filtering
schema validation
```

## Integration tests

Use real PostgreSQL where practical for:

```text
repositories
transactions
scoping
migrations
approval gating
```

## End-to-end backend tests

The first major E2E test should validate:

```text
request
→ plan
→ policy
→ approval
→ agent execution
→ QA
→ completion
→ audit events
```

External model providers should have mock/fake adapters for deterministic CI.

---

# 30. CI baseline

GitHub Actions initial jobs:

```text
backend-lint
backend-test
frontend-lint
frontend-typecheck
frontend-test
```

Later:

```text
integration-test
migration-test
security-scan
```

Do not require live paid model API calls in CI.

---

# 31. Migration discipline

Every schema change must use Alembic.

CI should eventually test:

```text
empty database
↓
apply all migrations
↓
application boots
```

Avoid editing already-released migration history unless the migration has never left development and the impact is understood.

---

# 32. Security baseline

Before agents execute tools:

- never expose provider keys to frontend;
- validate all API payloads;
- scope all database access by tenant/workspace where relevant;
- centralize tool execution;
- send all action requests through Policy Engine;
- avoid arbitrary shell execution in the API process;
- audit mutations;
- use allowlisted provider/tool adapters;
- use timeouts for external calls.

The future sandbox/tool-runtime design should be specified before arbitrary code execution becomes a general capability.

---

# 33. Implementation order

Concrete recommended sequence:

```text
I-001 Repository scaffold
I-002 Development infrastructure
I-003 Backend core/config/logging
I-004 Database + migrations
I-005 Tenant/workspace bootstrap
I-006 Projects CRUD
I-007 Tasks CRUD
I-008 Runtime event service
I-009 Audit service
I-010 SSE event stream
I-011 Minimal web shell
I-012 Project/task/activity views
I-013 Policy schema + engine
I-014 Approval workflow
I-015 Policy simulation
I-016 Provider abstraction
I-017 Model Catalog Service
I-018 Model Router
I-019 Usage capture
I-020 Agent definitions/runs
I-021 Structured agent contracts
I-022 First provider-backed agent
I-023 Workflow plan/run/steps
I-024 Orchestrator V1
I-025 Developer Manager
I-026 Developer Worker
I-027 QA Worker
I-028 First vertical workflow
I-029 Full vertical integration test
I-030 UX pass on approvals/workflows
```

Do not start Memory Engine until the first vertical workflow produces stable structured events/results, unless a tiny temporary context store is needed for development.

---

# 34. First milestone

The first milestone is complete when this scenario works:

```text
1. Developer starts PostgreSQL, Redis, Qdrant.
2. API boots.
3. Web boots.
4. User creates a project.
5. User creates/moves tasks.
6. Changes appear in realtime activity.
7. Every mutation has audit events.
```

This milestone contains no LLM dependency.

That is intentional.

---

# 35. Second milestone

Complete when:

```text
1. A proposed action is evaluated by Policy Engine.
2. REQUIRE_CONFIRMATION creates an ApprovalRequest.
3. Execution is physically blocked.
4. User approves in UI.
5. Execution continues.
6. Audit trail proves the entire chain.
```

Still no need for autonomous agents yet.

---

# 36. Third milestone

Complete when:

```text
1. Model Catalog contains verified current provider models.
2. Router selects an allowed candidate.
3. Provider adapter executes request.
4. Usage/cost is recorded.
5. Technical failures retry/fallback within limits.
6. Intelligence escalation cannot become paid without required approval.
```

---

# 37. Fourth milestone — first real Novalton workflow

Complete when:

```text
User request
↓
visible plan
↓
Developer Manager
↓
Developer Worker
↓
QA Worker
↓
Orchestrator synthesis
↓
user result
```

with:

- structured agent contracts;
- live events;
- policy gating;
- model routing;
- cost tracking;
- QA challenge;
- audit trace.

This milestone is the first point at which Novalton OS should feel like a real product rather than infrastructure.

---

# 38. Definition of done for implementation tickets

A ticket is not done merely because generated code exists.

Minimum definition:

```text
code implemented
lint passes
tests added/updated
tests pass
schema/migration included if needed
error cases handled
logs/events added where relevant
no secrets committed
documentation updated where architecture changed
```

For policy/security-sensitive features, tests for bypass attempts are mandatory.

---

# 39. AI-assisted development rules

OpenCode/Cursor/Hermes may implement code, but they should operate under explicit ticket scope.

For each ticket:

```text
read relevant docs
inspect current repository
propose small plan
implement only requested scope
run tests/lint
report files changed
report unresolved risks
```

The coding agent should not redesign foundational architecture silently.

If implementation conflicts with a foundation document, it should surface the conflict rather than override the document.

---

# 40. FIRST OPENCODE TICKET

The first implementation request should be intentionally boring and foundational.

## Ticket I-001 — Repository scaffold

### Objective

Create the initial Novalton OS monorepo scaffold based on the foundational documents without implementing business logic yet.

### Required output

Create:

```text
apps/web
apps/api
apps/node
packages/contracts
packages/ui
packages/sdk
infra/docker
infra/migrations
scripts
.github/workflows
```

### Backend

Initialize a minimal FastAPI application with:

```text
GET /api/v1/health
```

returning a structured health response.

Include:

- `pyproject.toml`;
- ruff configuration;
- pytest;
- application config module;
- basic structured logging;
- one health endpoint test.

### Frontend

Initialize Next.js + TypeScript + Tailwind.

Create a minimal page displaying:

```text
Novalton OS
Development foundation
```

Do not add Three.js or complex UI yet.

### Node

Create only a README placeholder explaining that Novalton Node will later provide hybrid local execution.

### Infrastructure

Create Docker Compose with:

```text
PostgreSQL
Redis
Qdrant
```

with persistent development volumes and healthchecks.

Create `.env.example` with non-secret placeholders.

### CI

Add a basic GitHub Actions workflow that runs backend lint/tests and frontend lint/typecheck.

### README

Add developer quick-start instructions.

### Constraints

- Follow `docs/00-foundations.md` through `docs/11-implementation-plan.md`.
- Use modular-monolith direction.
- Do not implement authentication.
- Do not implement agents yet.
- Do not implement Memory Engine yet.
- Do not introduce LangGraph or similar orchestration frameworks yet.
- Do not add paid services.
- Do not hard-code private credentials.
- Keep the implementation minimal and production-conscious.

### Completion report

The agent must report:

```text
files created
commands executed
tests/lint results
architecture assumptions
remaining setup steps
```

---

# 41. Suggested OpenCode prompt

```text
You are implementing ticket I-001 for the Novalton OS repository.

First read all architecture/specification documents in docs/, especially docs/00-foundations.md through docs/11-implementation-plan.md.

Then inspect the current repository before modifying anything.

Implement ONLY ticket I-001 — Repository scaffold as defined in docs/11-implementation-plan.md.

Key requirements:
- monorepo structure with apps/web, apps/api, apps/node, packages/contracts, packages/ui, packages/sdk, infra, scripts;
- FastAPI backend with GET /api/v1/health;
- Python project config, Ruff, pytest, structured logging and health test;
- Next.js + TypeScript + Tailwind minimal frontend;
- Docker Compose for PostgreSQL, Redis and Qdrant with healthchecks and persistent development volumes;
- .env.example with no real secrets;
- basic GitHub Actions CI for backend and frontend;
- developer quick-start README;
- apps/node is placeholder only.

Do not implement agents, authentication, memory, orchestration frameworks, Model Router, Policy Engine or premium UI yet.

Keep dependencies minimal.

Before coding, provide a short implementation plan based on the actual repository state. Then implement, run the relevant lint/tests/typechecks, fix failures caused by your changes, and finish with a concise report of files changed, commands run, test results, assumptions and remaining manual steps.
```

---

# 42. After ticket I-001

Do not jump straight into agents.

Next tickets should be:

```text
I-002 Development infrastructure verification
I-003 Backend core/config/logging
I-004 SQLAlchemy + Alembic database foundation
I-005 Bootstrap tenant/workspace/user scope
I-006 Project CRUD
I-007 Task CRUD
I-008 Runtime Event Service
I-009 Audit Service
I-010 SSE event stream
```

Only after this platform layer is stable should Policy Engine implementation begin.

---

# 43. Invariants

1. Business logic does not live in route handlers.
2. Single-user V1 still carries SaaS-compatible scope IDs.
3. PostgreSQL is authoritative for structured persistent state.
4. Redis is not authoritative durable storage.
5. Qdrant is not authoritative business storage.
6. No tool action bypasses Policy Engine once the tool layer exists.
7. Model names proposed by agents are not trusted without Model Catalog validation.
8. Paid intelligence escalation follows approval policy.
9. Agent outputs are schema validated.
10. Runtime events and audit are first-class concerns.
11. CI never requires live paid model calls.
12. Secrets are never committed.
13. The first milestone works without any LLM.
14. The first multi-agent workflow is deliberately narrow.
15. New complexity must solve a demonstrated need.

---

# 44. Next step

After this document is accepted, implementation should begin with **Ticket I-001 — Repository scaffold**.

The next specification document should only be created if implementation exposes an unresolved architectural question. The documentation phase is sufficiently complete to begin coding.
