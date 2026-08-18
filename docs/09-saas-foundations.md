# Novalton OS — SaaS Foundations

> Version: 0.1 — 19 August 2026
>
> Status: Foundational draft

## 1. Purpose

This document defines how Novalton OS can evolve from a single-user local/hybrid installation into a multi-tenant SaaS without rewriting its core architecture.

The goal is **not** to build full SaaS billing, authentication, enterprise administration, and multi-tenant hosting in V1.

The goal is to make sure that V1 does not hard-code assumptions that later prevent:

- organizations;
- workspaces;
- multiple users;
- centralized administration;
- hybrid execution;
- enterprise-local resources;
- usage metering;
- quotas;
- future billing;
- customer-provided API keys;
- strict data isolation.

The initial deployment remains primarily **single-user and hybrid**, but the data model and runtime boundaries must be compatible with future SaaS operation.

---

# 2. Core principle

Novalton OS should separate:

```text
CONTROL
DATA
EXECUTION
IDENTITY
USAGE
```

rather than assuming everything runs in one machine and belongs to one person forever.

Conceptually:

```text
Novalton Control Plane
        |
        +--> tenants / organizations
        +--> workspaces
        +--> orchestration
        +--> policy
        +--> usage accounting
        +--> administration
        |
        v
Hybrid Execution Layer
        |
        +--> server-side services
        +--> Novalton Nodes
        +--> external providers
```

---

# 3. Organization hierarchy

The foundational hierarchy is:

```text
TENANT / ORGANIZATION
        |
        +--> WORKSPACE
                |
                +--> PROJECT
                        |
                        +--> TASK / WORKFLOW / AGENT RUN
```

A tenant represents an organization or company.

A workspace represents a logical team, department, or isolated operational area inside that organization.

Examples:

```text
VANNES BATTERIES
├── Direction
├── Commercial
├── Support
└── Administration
```

A future personal installation may still use the same model:

```text
tenant_local
└── workspace_default
```

The existence of tenant/workspace identifiers does not mean multi-user SaaS must be implemented in V1.

---

# 4. Tenant-global resources

Some resources belong to the whole organization rather than one workspace.

Possible tenant-level resources:

- organization identity;
- company-wide policies;
- global budget;
- allowed model/provider catalog;
- allowed tools;
- shared connectors;
- company-wide agent templates;
- selected shared memory;
- shared usage limits;
- Node registry;
- organization-wide security defaults.

Workspace-specific configuration may add restrictions or narrower permissions but must not silently override stricter organization-level rules.

Conceptually:

```text
TENANT POLICY
     ↓
WORKSPACE POLICY
     ↓
PROJECT POLICY
     ↓
AGENT / WORKFLOW POLICY
```

Where multiple applicable rules conflict, the effective policy must respect the Policy Engine precedence and strictness model defined elsewhere.

---

# 5. Workspace boundaries

A workspace should provide a meaningful isolation and organization boundary.

Workspace-scoped resources may include:

- projects;
- tasks;
- agents;
- workflows;
- memory;
- tools;
- budgets;
- quotas;
- dashboards;
- usage reports;
- workspace-specific policies.

Cross-workspace access must be explicit.

A tenant-global agent or service may exist, but it must still retrieve only the memory and tools authorized for the current task.

---

# 6. Role direction

Future roles should remain simple at the top level while supporting fine-grained permissions underneath.

Base roles:

```text
OWNER
ADMIN
MEMBER
VIEWER
```

These are convenience bundles, not the entire authorization model.

Fine-grained control may govern:

- project access;
- agent access;
- workflow creation;
- memory visibility;
- secret usage;
- model usage;
- tool usage;
- approval authority;
- Node management;
- billing/usage visibility;
- policy administration.

The detailed RBAC/permission model belongs to a later specification.

---

# 7. Authentication roadmap

V1 is not required to implement a full SaaS identity stack.

Initial direction:

```text
V1
single-user / private installation
minimal authentication where needed

V2+
accounts
sessions
organization membership
roles
passkeys / OAuth where appropriate
SSO later for enterprise
```

However, internal records should already be compatible with future identity ownership.

Examples:

```text
tenant_id
workspace_id
actor_id
created_by
approved_by
```

V1 may use placeholder/local identities such as:

```text
user_owner
service_orchestrator
node_desktop_main
```

---

# 8. Customer-provided AI/API keys

The initial SaaS direction is **bring-your-own-key for enterprise/provider access**.

An organization provides its own API keys for external AI providers and other paid external services.

Novalton should not require all tenants to share one global provider key.

Advantages:

- clearer cost ownership;
- easier provider choice;
- stronger tenant isolation;
- reduced billing complexity in early versions;
- enterprise control over external providers.

Provider credentials must be stored as secrets, never as ordinary configuration or memory.

The system should track:

```text
provider
credential owner
scope
allowed workspaces
rotation metadata
status
last validation
```

Actual secret values must not appear in ordinary logs, memory, model prompts, or usage events.

---

# 9. Execution-location vocabulary

The term `cloud` is too vague for authorization decisions.

Novalton OS should distinguish at least:

```text
LOCAL_DEVICE
PRIVATE_NOVALTON_INFRA
EXTERNAL_PROVIDER
```

## 9.1 LOCAL_DEVICE

Execution on a trusted user/company device through a Novalton Node or Voice Client.

Examples:

- local STT;
- local TTS;
- local LLM;
- LAN resource access;
- local file processing.

## 9.2 PRIVATE_NOVALTON_INFRA

Execution on infrastructure controlled by the organization or Novalton deployment.

Examples:

- self-hosted Proxmox backend;
- organization server;
- dedicated private Novalton deployment;
- private database services.

## 9.3 EXTERNAL_PROVIDER

Execution through an external third party.

Examples:

- OpenRouter;
- external LLM API;
- SaaS connector;
- external storage/API provider.

Policies should be able to control where data may travel.

Example:

```yaml
data_class: confidential_client_document
execution:
  local_device: allow
  private_novalton_infra: allow
  external_provider: require_confirmation
```

This vocabulary should replace ambiguous `local vs cloud` decisions wherever security consequences matter.

---

# 10. Hybrid-first deployment model

The default long-term product direction is **hybrid**.

A Novalton installation may use:

```text
Novalton Control Plane / Backend
             |
             +--> browser clients
             +--> desktop clients
             +--> mobile client later
             |
             +--> Novalton Nodes
```

The user should not have to run the entire AI stack independently on every device.

A primary backend may run on a server, while PCs and other devices connect to it.

This supports:

- access from multiple devices;
- centralized memory;
- centralized orchestration;
- shared policies;
- shared task state;
- local device capabilities where useful.

---

# 11. Novalton Node

A **Novalton Node** is a trusted execution agent installed on a machine inside the user or company environment.

It is not the Orchestrator.

It is not an autonomous policy authority.

It is an execution endpoint for local capabilities.

Conceptually:

```text
Novalton Control Plane
        |
        | authenticated secure channel
        v
Novalton Node
        |
        +--> local filesystem
        +--> LAN services
        +--> browser/runtime tools
        +--> local models
        +--> STT / TTS
        +--> hardware integrations
        +--> secure command execution
```

The Node should normally establish an outbound authenticated connection to the backend rather than requiring broad inbound Internet exposure of the company LAN.

---

# 12. Node capabilities

Each Node advertises capabilities rather than pretending every computer can do everything.

Example capability report:

```yaml
node_id: office_pc_01
os: windows
cpu:
  model: ...
ram_gb: 16
gpu:
  vendor: nvidia
  vram_gb: 4
capabilities:
  filesystem: true
  lan_access: true
  browser_automation: true
  local_stt: true
  local_tts: true
  local_llm: limited
```

The scheduler/orchestrator should select a Node based on:

- permissions;
- location;
- available capabilities;
- current load;
- hardware;
- data residency requirements;
- network availability;
- task requirements.

---

# 13. Weak-device behavior

Novalton Node must work on weak or old PCs.

Local AI is **optional capability**, not a requirement for Node participation.

A weak PC may operate as a **thin Node**:

```text
Thin Novalton Node
├── secure tunnel/client
├── filesystem access
├── LAN access
├── lightweight tool execution
└── no heavy local inference required
```

Heavy reasoning can be executed elsewhere:

```text
weak office PC
    |
    | secure structured request
    v
private server / Proxmox / authorized provider
    |
    | result
    v
weak office PC
```

For sensitive files, the system may minimize what leaves the Node.

Example:

```text
read document locally
    ↓
extract required fields locally
    ↓
send only necessary structured data
```

Where local processing is impossible and policy forbids external transfer, the task should fail safely or request another authorized Node rather than secretly sending the full source elsewhere.

---

# 14. Capability-aware workload placement

Execution placement should be decided by requirements rather than ideology.

Possible execution targets:

```text
NODE_LOCAL
PRIVATE_SERVER
EXTERNAL_PROVIDER
```

Example decision factors:

- model requirement;
- GPU/VRAM requirement;
- latency;
- privacy;
- data location;
- cost;
- availability;
- user policy.

The Model Router chooses reasoning models, while the runtime scheduler determines **where** eligible work executes.

These are related but distinct decisions.

---

# 15. Local Model Manager and Nodes

The Local Model Manager defined in the Voice architecture may run through Novalton Nodes.

A capable Node may manage:

- STT models;
- TTS models;
- embeddings;
- rerankers;
- OCR models;
- vision models;
- local LLMs;
- future local AI runtimes.

The Node reports:

- installed models;
- available disk space;
- hardware compatibility;
- runtime health;
- active versions;
- update status.

The backend may propose model installation or updates, but Policy Engine rules still apply to significant downloads, system modifications, or resource use.

---

# 16. Node security

A Node must authenticate as a device identity.

A Node is not trusted merely because it is on the LAN.

Requirements:

- unique Node identity;
- revocable authorization;
- encrypted transport;
- scoped tenant/workspace access;
- tool permission boundaries;
- secret isolation;
- command audit;
- replay protection where relevant;
- heartbeat/health reporting.

A compromised Node should not automatically gain access to all tenant memory, secrets, or tools.

---

# 17. Usage metering

Novalton OS should implement **event-based usage metering**.

Every billable, quota-relevant, or operationally important resource consumption creates a structured usage event.

Example:

```json
{
  "event_id": "usage_01J...",
  "tenant_id": "tenant_123",
  "workspace_id": "commercial",
  "project_id": "prospection",
  "metric": "llm_input_tokens",
  "quantity": 18420,
  "provider": "example_provider",
  "model_id": "example/model",
  "estimated_cost": 0.0032,
  "occurred_at": "..."
}
```

Possible metrics:

```text
LLM input tokens
LLM output tokens
model calls
agent runs
workflow runtime
external tool calls
storage
vector storage
STT minutes
TTS minutes
Node compute
local GPU time
premium model calls
```

Not every metric must become billable.

Metering and billing are separate concerns.

---

# 18. Usage architecture

Initial architecture:

```text
Execution
   |
   v
Usage Event
   |
   v
Usage Ledger
   |
   +--> aggregation
   +--> dashboard
   +--> quota evaluation
   +--> cost analytics
   |
   v
Future Billing Adapter
```

The **Usage Ledger** is Novalton-owned infrastructure.

It should not depend structurally on one external billing vendor.

Possible future adapters may integrate systems such as:

```text
OpenMeter
Lago
Stripe
other billing/metering systems
```

The choice of billing provider remains replaceable.

---

# 19. Usage event properties

Usage events should be:

- immutable after acceptance where practical;
- idempotent;
- timestamped;
- tenant-scoped;
- workspace-scoped where relevant;
- attributable to a workflow/run/model/tool;
- auditable;
- aggregatable.

Corrections should preferably use adjustment events rather than silently rewriting old usage history.

---

# 20. Quota hierarchy

Quotas should support hierarchy:

```text
TENANT
  ↓
WORKSPACE
  ↓
PROJECT
  ↓
USER / AGENT / WORKFLOW when useful
```

Example:

```text
Organization budget: 100 EUR/month

Commercial workspace: 30 EUR
Support workspace: 20 EUR
Direction workspace: 50 EUR
```

A workspace remaining under its own limit does not allow the tenant global limit to be exceeded.

Effective usage must satisfy all applicable quota layers.

---

# 21. Quota behaviors

Quota rules may use several behaviors:

```text
SOFT_LIMIT
HARD_LIMIT
APPROVAL_LIMIT
```

## 21.1 SOFT_LIMIT

Usage continues but creates warnings.

Example:

> 80% of monthly AI budget used.

## 21.2 HARD_LIMIT

Further relevant usage is blocked.

## 21.3 APPROVAL_LIMIT

The workflow pauses and requests user approval before spending beyond the configured threshold.

This is particularly compatible with Novalton's human-authority model.

Example:

```text
Workspace reached 95% of monthly budget.
Developer Manager requests a premium model call estimated at €0.42.

[Approve once]
[Increase workspace limit]
[Reject]
```

---

# 22. Budget and quota separation

A budget is not exactly the same thing as a quota.

Examples:

```text
budget = target/financial envelope
quota = enforceable limit
```

A workspace may have:

```yaml
monthly_budget_eur: 25
soft_warning_at_percent: 80
approval_limit_eur: 25
hard_limit_eur: 35
```

This enables controlled flexibility without surprise spending.

---

# 23. Future billing compatibility

V1 does **not** need subscription billing.

The architecture should merely preserve enough data to support it later.

Possible future concepts:

- plans;
- included usage;
- overage;
- seats;
- feature entitlements;
- storage tiers;
- premium model access;
- dedicated Nodes;
- enterprise support;
- private deployments.

These should be implemented later through an entitlement/billing layer rather than hard-coded into ordinary application logic.

---

# 24. Entitlements

Future plans may grant capabilities through entitlements.

Examples:

```text
max_workspaces
max_users
max_concurrent_workflows
premium_models_allowed
meeting_mode_enabled
advanced_audit_enabled
max_storage_gb
custom_retention_enabled
```

The UI should query effective entitlements rather than use scattered `if plan == pro` checks throughout the codebase.

---

# 25. Data isolation

Every durable resource that may become tenant-owned must be tenant-aware.

This includes:

- PostgreSQL records;
- Qdrant collections/points;
- Redis keys;
- background jobs;
- workflow events;
- files/object storage;
- logs;
- secrets;
- usage events;
- caches;
- Nodes;
- audit records.

Cross-tenant access must never result from a missing filter or semantic similarity.

---

# 26. Tenant context propagation

Every request entering tenant-scoped backend logic should establish an immutable execution context containing identifiers such as:

```text
tenant_id
workspace_id
actor_id
request_id
```

Workflow and agent runs should inherit this context explicitly.

Internal APIs should not rely on global mutable variables to determine tenant ownership.

---

# 27. PostgreSQL isolation direction

V1 may use shared database tables with mandatory `tenant_id` and workspace scoping.

Future SaaS hardening may additionally use:

- PostgreSQL Row Level Security;
- tenant-aware repository abstractions;
- dedicated databases for high-isolation enterprise deployments.

The architecture should allow stronger isolation without rewriting domain models.

---

# 28. Vector isolation

Qdrant/vector retrieval must enforce tenant and workspace filters before results are considered valid.

Possible designs include:

- shared collections with mandatory tenant payload filters;
- collection-per-tenant for selected deployments;
- dedicated vector service for high-security tenants.

Semantic similarity never overrides tenant boundaries.

---

# 29. Secrets isolation

Secrets must be tenant-owned and scope-aware.

Examples:

```text
organization provider key
workspace GitHub token
project deployment credential
Node-local credential
```

Secrets should support:

- ownership;
- scope;
- allowed consumers;
- rotation;
- revocation;
- audit;
- encrypted storage.

A model must not receive raw secret values merely because it requested them.

Tools should consume secrets through controlled execution paths.

---

# 30. SaaS administration plane

A future Novalton internal administration console may manage platform-level concerns.

Possible functions:

```text
organizations
plans / entitlements
platform versions
Node health
provider health
model catalog
usage totals
quota incidents
service incidents
deployment status
security alerts
```

Administration privileges do **not** imply unrestricted access to customer content.

Platform metadata and customer private data must remain conceptually and technically separate.

---

# 31. Customer-data access principle

Routine platform administration should not require browsing customer conversations, documents, memory, or project content.

If exceptional support access is ever implemented, it should require explicit audited mechanisms such as:

- customer approval;
- time-limited access;
- narrow scope;
- strong audit;
- visible support session state.

This is not required in V1.

---

# 32. Hybrid access from multiple devices

A hybrid installation should allow multiple trusted clients to use the same backend.

Example:

```text
Desktop browser
Laptop browser
Future mobile client
        |
        v
Novalton Backend
        |
        +--> shared task state
        +--> shared workflows
        +--> shared memory
        +--> approvals
        +--> Nodes
```

The local machine running a Node does not need to be the device from which the user interacts with Nova.

Example:

```text
Phone / laptop UI
      ↓
Novalton Backend
      ↓
Office Node
      ↓
local company resource
```

This is a central reason the architecture is hybrid rather than purely desktop-local.

---

# 33. Offline and disconnection behavior

Nodes and clients may disconnect.

The runtime should distinguish:

```text
NODE_ONLINE
NODE_DEGRADED
NODE_OFFLINE
```

When a required Node is unavailable:

- do not silently reroute sensitive work to an external provider;
- try another authorized compatible Node if policy permits;
- pause the workflow if needed;
- show a clear blocking reason;
- resume from checkpoint when the Node returns.

---

# 34. Migration-ready V1 design

There is no existing production system to migrate yet.

The purpose of migration readiness is to avoid creating V1 data that later lacks ownership boundaries.

A single-user V1 may still create records under:

```text
tenant_id = tenant_local
workspace_id = workspace_default
user_id = user_owner
```

This produces:

```text
tenant_local
└── workspace_default
    └── user_owner
```

Later, the system may support transferring or promoting these resources into a SaaS organization without redesigning every table and memory object.

---

# 35. Future local-to-SaaS transition

Conceptual future transition:

```text
Before

tenant_local
└── workspace_default
    ├── projects
    ├── policies
    ├── memories
    └── agents

After

Novalton Organization
├── Direction
├── Development
├── Sales
└── Operations
```

A migration tool may later:

1. create the new organization;
2. map the local owner to an account;
3. move/copy selected workspaces;
4. preserve IDs where safe;
5. preserve provenance/version history;
6. remap secrets securely;
7. reindex vector memory;
8. verify tenant boundaries;
9. produce a migration report.

None of this migration tooling is required before development begins.

The important V1 requirement is simply to preserve ownership metadata and avoid global singleton assumptions.

---

# 36. Deployment modes

The product should eventually support several deployment modes without changing core domain semantics.

## 36.1 Local / private deployment

```text
UI + backend + database + Nodes
inside user/company infrastructure
```

## 36.2 Hybrid deployment

```text
central Novalton backend/control plane
+
customer Novalton Nodes
```

This is the preferred long-term default direction.

## 36.3 Managed/private enterprise deployment

Possible future option:

```text
dedicated tenant infrastructure
+
private Nodes
+
enterprise identity
```

The architecture should not require all customers to use identical hosting topology.

---

# 37. Platform vs tenant configuration

Novalton should distinguish:

```text
PLATFORM CONFIG
TENANT CONFIG
WORKSPACE CONFIG
USER PREFERENCES
```

Platform configuration defines system capabilities.

Tenant configuration defines organization policy and integrations.

Workspace configuration defines local operational choices.

User preferences customize personal UI and interaction where permitted.

Lower levels cannot override immutable security/platform constraints.

---

# 38. Feature flags

Feature flags should exist independently from billing plans.

Potential purposes:

- staged rollout;
- beta features;
- emergency disable;
- per-tenant testing;
- Node capability experiments;
- new model router behavior;
- migration compatibility.

Feature flags must not become a substitute for authorization.

---

# 39. Audit requirements

Future SaaS operation increases the importance of auditability.

Audit should capture relevant events such as:

```text
tenant.created
workspace.created
member.added
role.changed
secret.rotated
node.authorized
node.revoked
quota.changed
quota.exceeded
usage.adjusted
policy.changed
support_access.started
support_access.ended
```

Logs must remain tenant-scoped where applicable.

---

# 40. V1 SaaS-foundation requirements

V1 should implement only the foundations required to avoid architectural dead ends.

Minimum requirements:

1. tenant identifier on durable tenant-owned records;
2. workspace identifier where appropriate;
3. local default tenant/workspace/user identities;
4. tenant/workspace-aware Policy Engine context;
5. tenant/workspace-aware Memory Engine context;
6. tenant/workspace-aware workflow and agent runs;
7. provider keys modeled as tenant-owned secrets;
8. usage event schema;
9. basic Usage Ledger;
10. budget/quota concepts, even if UI is basic;
11. Novalton Node identity and capability model;
12. hybrid backend/Node communication design;
13. weak-device/thin-Node support;
14. explicit execution-location classification;
15. no requirement for full SaaS authentication or billing.

---

# 41. Deferred to V2+

The following may remain outside V1:

- public SaaS signup;
- full user account lifecycle;
- passkeys/OAuth;
- multi-user invitation flows;
- SSO/SAML;
- subscription billing;
- Stripe/Lago/OpenMeter integration;
- plan management UI;
- enterprise support access;
- advanced RBAC UI;
- mobile app;
- multi-region hosting;
- dedicated-tenant provisioning automation.

---

# 42. Invariants

1. Tenant/workspace ownership must be explicit on durable tenant-owned data.
2. Tenant-wide rules may apply across all workspaces.
3. Workspace configuration cannot weaken stricter tenant policies.
4. Cross-tenant access is never implicit.
5. External-provider data transfer is distinguishable from private/local execution.
6. Customer provider/API keys are tenant-owned secrets.
7. Metering and billing remain separate concerns.
8. Usage history is auditable.
9. Quotas may exist at multiple hierarchy levels.
10. Approval-based quota escalation is supported conceptually.
11. Novalton Node is an execution endpoint, not an authority bypass.
12. A Node does not need powerful hardware.
13. Heavy local AI is optional per Node.
14. Work may be placed according to capability, privacy, cost, and policy.
15. Sensitive work is not silently rerouted externally when a Node fails.
16. Platform administration does not imply free access to customer content.
17. V1 may remain single-user while preserving SaaS-compatible ownership IDs.
18. Future SaaS migration must preserve provenance and policies where possible.
19. Authentication and billing complexity should not be prematurely forced into V1.
20. Hybrid operation is a first-class architecture, not an afterthought.

---

# 43. Open design questions

Later specifications and implementation work must decide:

- exact Node transport protocol;
- Node pairing/onboarding flow;
- Node auto-update mechanism;
- whether some Nodes can operate fully offline;
- exact tenant/workspace PostgreSQL schema;
- Row Level Security adoption timing;
- exact Usage Ledger schema;
- quota evaluation frequency and caching;
- cost-estimation normalization across providers;
- local compute metering semantics;
- exact future billing integration;
- secret store implementation;
- tenant deletion workflow;
- data export/import format;
- workspace transfer rules;
- enterprise dedicated deployment model;
- V2 authentication provider strategy;
- future organization/member invitation flow.

---

# 44. Next document

The next specification should define the **implementation roadmap**.

`10-roadmap.md` should convert the architecture into buildable phases and define:

- V0 / foundation milestone;
- V1 MVP scope;
- repository structure;
- backend implementation order;
- frontend implementation order;
- database setup;
- first agent workflow;
- Policy Engine MVP;
- Model Router MVP;
- Memory Engine MVP;
- Novalton Node MVP;
- voice milestones;
- tests and quality gates;
- deployment on the initial hardware;
- what is explicitly postponed;
- criteria for considering V1 usable.
