# Novalton OS — Agent Model

> Version: 0.2 — 18 August 2026
>
> Status: Foundational draft

## 1. Purpose

This document defines what an **agent** is inside Novalton OS, how agents are instantiated, supervised, allowed to delegate work, challenged by other agents, and connected to models, tools, memory, and policy.

An agent is **not** a model, a prompt, or a standalone chatbot.

An agent is a governed execution role with:

- a stable definition;
- a mission;
- capabilities;
- permissions;
- tools;
- memory access;
- model requirements;
- structured inputs and outputs;
- execution constraints;
- observability;
- lifecycle state;
- versioned operational lessons.

The same agent role must be able to run with different models over time without changing its identity.

---

# 2. Core separation: system components vs agents

Novalton OS separates **core system components** from **specialized agents**.

```text
CORE SYSTEM
├── Orchestrator
├── Policy Engine
├── Memory Engine
├── Model Router
└── Event / Runtime Layer

SPECIALIZED AGENTS
├── Project Manager
├── Developer
├── Tester / QA
├── Legal Research Assistant
├── Outreach / Commercial Assistant
└── Personal Assistant
```

The **Orchestrator is not a normal agent**.

It is a privileged coordination component responsible for:

- understanding user intent;
- proposing workflows;
- selecting capabilities and agents;
- inspecting agent results;
- choosing what should happen next;
- consulting the Model Router;
- submitting actions to the Policy Engine;
- requesting user input or approval;
- stopping, adapting, or continuing workflows.

The Orchestrator may use an LLM internally, but its architectural role is different from that of a specialized agent.

---

# 3. Agent definition and Agent Run

Novalton OS distinguishes a persistent **Agent Definition** from a temporary **Agent Run**.

```text
Agent Definition
Developer v3
     |
     ├── Agent Run #184
     ├── Agent Run #185
     └── Agent Run #186
```

## 3.1 Agent Definition

The Agent Definition contains the durable role configuration:

```yaml
id: developer.default
name: Developer
slug: developer
version: 3
status: enabled
workspace_id: default
category: engineering
```

It also contains:

- mission;
- capability profile;
- permission profile;
- allowed tools;
- memory policy;
- model policy;
- delegation policy;
- output contract;
- operational lessons.

## 3.2 Agent Run

Each execution creates an isolated Agent Run.

Example:

```yaml
run_id: run_01JXYZ
agent_id: developer.default
agent_version: 3
task_id: task_123
status: running
started_at: ...
model_route: ...
```

Each run has its own:

- task context;
- selected model;
- tool calls;
- runtime state;
- events;
- cost;
- outputs;
- errors;
- approval state;
- audit trail.

Historical runs must remain traceable even after the Agent Definition evolves.

---

# 4. Agent mission

Every agent must have a clear, narrow mission.

Bad mission:

> Help with everything technical.

Good mission:

> Design, implement, review, and document software changes inside approved repositories while respecting project constraints, security policies, coding standards, and tool permissions.

Mission defines **responsibility**, not **authority**.

Permissions are separate and enforced outside the model.

---

# 5. Capabilities

Capabilities describe what an agent knows how to do.

Example Developer capabilities:

```yaml
capabilities:
  - software_architecture
  - python
  - typescript
  - fastapi
  - nextjs
  - debugging
  - testing
  - git
  - docker
  - code_review
```

Example Legal capabilities:

```yaml
capabilities:
  - french_legal_research
  - rgpd_research
  - contract_analysis
  - source_comparison
  - risk_identification
  - legal_summary
```

Capabilities are used by the Orchestrator to match tasks to workers.

Later, capabilities may support metadata such as proficiency, evidence, historical success, and confidence.

---

# 6. Permissions

Permissions define what an agent may attempt.

They are enforced by the Policy Engine and tool layer, not by prompt instructions alone.

Example:

```yaml
permissions:
  files:
    read: allow
    write: require_policy_check
    delete: deny

  git:
    read: allow
    commit: require_policy_check
    push: require_confirmation

  email:
    read: deny
    draft: deny
    send: deny

  shell:
    execute: require_policy_check
    destructive: deny

  web:
    research: allow
```

Permissions should support:

- allow;
- deny;
- require policy check;
- require confirmation;
- scoped allow.

Example scoped permission:

```yaml
filesystem_write:
  mode: scoped_allow
  paths:
    - /workspace/projects/**
```

An agent cannot grant itself new permissions.

---

# 7. Tool access

Tools are concrete mechanisms used by agents.

Examples:

- filesystem;
- terminal;
- GitHub;
- web search;
- browser;
- email;
- calendar;
- database;
- PDF reader;
- code runner;
- project manager;
- document generator.

An agent may only request tools explicitly exposed to it.

Every tool call must independently pass a permission/policy check.

The model is never the final security boundary.

---

# 8. Memory scope

Agents do not automatically receive all stored memory.

Possible scopes:

```text
GLOBAL
WORKSPACE
PROJECT
CLIENT
USER
SESSION
TASK
DOCUMENT_SET
```

Example:

```yaml
memory_scope:
  read:
    - workspace
    - project
    - task
  write:
    - project
    - task
  sensitive_access: false
```

The Memory Engine should construct the smallest useful context for a run.

A Developer working on Project A must not automatically receive unrelated data from Project B.

---

# 9. Personal Assistant context model

The Personal Assistant is a special case because it needs broad situational awareness without becoming an all-powerful super-agent.

The selected design is:

> **Broad synthesized context, narrow direct permissions.**

The Personal Assistant may receive a concise general context containing information such as:

- current active projects;
- current priorities;
- relevant user preferences;
- upcoming obligations;
- recent important decisions;
- currently active tasks;
- selected long-term context.

However, this does **not** imply unrestricted raw access to every source system.

For example, the Personal Assistant may know that an important client conversation exists without receiving the entire mailbox unless the current task requires it.

When deeper access is needed, the agent requests an appropriate tool or memory scope and the Policy Engine evaluates it.

Conceptually:

```text
General Personal Context
        |
        v
Personal Assistant
        |
        +--> Need email detail?
        |       -> request scoped access
        |
        +--> Need project file?
                -> request scoped access
```

This preserves usefulness without creating an agent with permanent unrestricted access to everything.

---

# 10. Task-aware Model Router

Model selection is performed **per Agent Run**, not permanently per Agent Definition.

The system should normally choose the **least expensive model expected to complete the task reliably**, while respecting minimum quality requirements.

Conceptually:

```text
Agent + Task
    |
    v
Task difficulty / required capability
    |
    v
Model Router
    |
    ├── Free / local model if sufficient
    ├── Low-cost API model if needed
    └── Stronger paid model if justified
```

The Model Router may consider:

- task complexity;
- required capabilities;
- tool-use support;
- structured-output support;
- code/reasoning quality;
- context window;
- latency;
- provider availability;
- privacy constraints;
- historical performance;
- remaining budget;
- expected cost.

Example:

```text
Developer + rename/refactor small function
→ free/cheap coding model

Developer + major distributed architecture design
→ stronger reasoning/coding model

Orchestrator + high-impact ambiguous decision
→ high-quality orchestration model
```

The exact provider is replaceable.

---

# 11. Agent input contract

Agents receive structured inputs rather than only raw user text.

Example:

```json
{
  "task_id": "task_123",
  "objective": "Review the authentication implementation",
  "context": {
    "project_id": "novalton-os",
    "files": ["backend/auth.py"]
  },
  "constraints": [
    "Do not modify files",
    "Focus on security"
  ],
  "expected_output": "code_review_report"
}
```

Inputs may include:

- objective;
- approved plan scope;
- context;
- constraints;
- relevant memories;
- prior agent results;
- sources;
- budget;
- priority;
- expected output schema;
- permitted tools;
- policy context.

---

# 12. Agent output contract

Every agent returns a structured result.

Baseline contract:

```json
{
  "status": "completed",
  "summary": "...",
  "findings": [],
  "artifacts": [],
  "sources": [],
  "assumptions": [],
  "risks": [],
  "uncertainties": [],
  "blocking_issues": [],
  "challenge": null,
  "recommended_next_steps": [],
  "requested_actions": []
}
```

Possible statuses:

```text
COMPLETED
PARTIAL
BLOCKED
NEEDS_INPUT
FAILED
CANCELLED
```

The `assumptions` field is mandatory when the agent had to make non-trivial assumptions.

An agent must never silently present an assumption as a verified fact.

---

# 13. Challenge and disagreement mechanism

Agents are explicitly allowed to challenge the proposed continuation of a workflow.

A challenge may use levels such as:

```text
NONE
WARNING
HUMAN_REVIEW_RECOMMENDED
BLOCK_RECOMMENDED
```

Example:

```json
{
  "challenge": {
    "level": "HUMAN_REVIEW_RECOMMENDED",
    "reason": "The proposed contract is missing a data-processing clause",
    "evidence": ["src_12"],
    "suggested_action": "Ask the user before sending the contract"
  }
}
```

A challenge does not automatically become a hard technical veto unless a policy says so.

However, the Orchestrator is **required to reconsider the workflow** when a meaningful challenge is raised.

It may then:

- revise the plan;
- ask another agent for an independent opinion;
- request additional research;
- stop the workflow;
- ask the user;
- continue only if policy allows and it can justify the decision operationally.

For high-risk challenge categories, the Policy Engine may require human confirmation automatically.

The Orchestrator must never silently ignore `BLOCK_RECOMMENDED` or `HUMAN_REVIEW_RECOMMENDED`.

## 13.1 Durable human challenge resolution

`HUMAN_REVIEW_RECOMMENDED` is advisory Agent disagreement, not a Policy
`REQUIRE_CONFIRMATION` decision. When orchestration waits on this signal, the runtime persists one
minimal challenge record tied to the exact WorkflowRun, WorkflowStepRun, and successful AgentRun.
It stores only the challenge level and the bounded result semantics needed to finish the local
workflow transition; it does not store the AgentResult body, prompt, provider output, handoff body,
or requested actions.

The trusted local V1 human may choose `ACCEPT_RESULT` or `REJECT_RESULT`. Acceptance resolves the
challenge without changing the Agent result or QA verdict and performs no new model invocation.
Rejection deterministically fails the active step and workflow. A duplicate decision is idempotent
only when its decision and canonical reason match: a supplied reason is trimmed, `null` means no
reason, and blank or over-500-character input is rejected. A conflicting decision is rejected.

`BLOCK_RECOMMENDED` is deliberately stricter in V1: it may be rejected but not accepted. Actual
AgentResult statuses `BLOCKED` and `NEEDS_INPUT` fail the AgentRun and never become resolvable
successful challenges. An Agent or model cannot resolve its own challenge.

---

# 14. Requested actions

Agents propose actions, but proposals are not execution rights.

Example:

```json
{
  "requested_actions": [
    {
      "type": "git.write_file",
      "target": "backend/auth.py",
      "reason": "Fix missing token expiration validation",
      "risk_hint": "medium"
    }
  ]
}
```

The action goes through the Policy Engine, which returns:

```text
ALLOW
REQUIRE_CONFIRMATION
BLOCK
```

Only then may the tool execute it.

---

# 15. Hierarchical agent teams

Some agents may act as **domain managers** for multiple worker runs.

The Developer Agent is the first planned example.

Conceptually:

```text
Orchestrator
     |
     v
Developer Manager
     |
     ├── Backend Worker
     ├── Frontend Worker
     ├── Test Worker
     └── Documentation Worker
```

This hierarchy is bounded.

The Developer Manager may analyze a development task and propose how to divide it among workers.

Example proposal:

```json
{
  "delegation_plan": {
    "reason": "Frontend and backend work are independent",
    "workers": [
      {
        "role": "backend",
        "objective": "Implement project API"
      },
      {
        "role": "frontend",
        "objective": "Build project dashboard"
      }
    ]
  }
}
```

The **Developer has a real say in how development work should be executed** because it has domain expertise.

The Orchestrator then evaluates the proposal.

It may:

```text
APPROVE
MODIFY
REJECT
REQUEST_MORE_DETAIL
ASK_USER
```

The Orchestrator does not micromanage implementation blindly. It coordinates overall goals, policy, budget, and cross-domain dependencies, while the Developer Manager provides the technical execution strategy.

---

# 16. Worker agents

A worker agent is a temporary specialized Agent Run created under an approved delegation plan.

Workers may be based on:

- the same Agent Definition with different task scopes;
- specialized child definitions;
- dynamically constrained worker profiles.

Examples:

```text
Developer Manager
├── run_backend_001
├── run_frontend_002
└── run_tests_003
```

Workers receive only the context and permissions needed for their assigned work.

A worker cannot recursively create unlimited workers.

Any further delegation must follow the configured delegation policy.

---

# 17. Parallelism

Multiple Agent Runs, including multiple runs of the same role, may execute in parallel when tasks are independent.

Example:

```text
              Developer Manager
                /      |      \
               /       |       \
        Backend      Frontend      Docs
           |            |           |
           +------------+-----------+
                        |
                        v
                     Review
```

Parallelism is controlled by:

- task dependencies;
- concurrency limits;
- API budget;
- hardware capacity;
- model rate limits;
- policy;
- workspace settings.

The runtime must avoid parallel work on conflicting mutable resources unless explicitly coordinated.

---

# 18. Domain-manager principle

The Developer pattern may later apply to other domains.

Examples:

```text
Commercial Manager
├── Prospect Research Worker
├── Offer Draft Worker
└── Follow-up Worker

Legal Manager
├── Source Research Worker
├── Contract Review Worker
└── Compliance Worker
```

However, Novalton OS should not create deep hierarchies merely because it can.

Hierarchy must exist only when delegation improves quality, speed, or specialization enough to justify complexity and cost.

---

# 19. Operational learning

Agents may benefit from lessons learned from prior executions.

This does **not** mean allowing an agent to silently rewrite its own prompt or identity.

Instead, Novalton OS stores versioned **Operational Lessons**.

Example:

```yaml
lesson_id: lesson_dev_042
agent_id: developer.default
scope: project
statement: >
  When changing database models in this project, verify that a matching migration
  is included before marking the task complete.
origin:
  run_id: run_184
  detected_by: qa.default
confidence: high
status: active
created_at: ...
```

Lessons may originate from:

- QA findings;
- user corrections;
- failed runs;
- successful patterns;
- post-run evaluations;
- repeated errors.

Operational lessons must have provenance and lifecycle states such as:

```text
PROPOSED
VALIDATED
ACTIVE
SUPERSEDED
REJECTED
ARCHIVED
```

Important or broad lessons may require user or system validation before becoming active.

Lessons should be retrievable based on scope:

```text
GLOBAL AGENT
WORKSPACE
PROJECT
CLIENT
TASK TYPE
```

The objective is to let Novalton OS improve over time without creating uncontrolled self-modification.

---

# 20. Agent lifecycle

Each Agent Run has an explicit lifecycle.

```text
CREATED
   |
QUEUED
   |
PREPARING_CONTEXT
   |
MODEL_SELECTION
   |
RUNNING
   |
   +--> WAITING_FOR_TOOL
   +--> WAITING_FOR_APPROVAL
   +--> WAITING_FOR_INPUT
   +--> WAITING_FOR_CHILDREN
   |
COMPLETED
```

Failure/terminal branches:

```text
FAILED
CANCELLED
TIMED_OUT
BLOCKED_BY_POLICY
```

This lifecycle powers the real-time UI.

---

# 21. Real-time observability

The runtime emits structured events such as:

```text
agent_run.created
agent_run.started
agent_run.context_prepared
agent_run.model_selected
agent_run.delegation_proposed
agent_run.child_started
agent_run.tool_requested
agent_run.tool_started
agent_run.tool_completed
agent_run.challenge_raised
agent_run.awaiting_approval
agent_run.resumed
agent_run.completed
agent_run.failed
```

Example UI:

```text
Developer Manager
├─ Backend Worker      ███████░ 78%
├─ Frontend Worker     ████░░░░ 43%
└─ QA Worker           waiting

Latest event:
Backend Worker proposed database migration
```

The system exposes operational state and outputs, not private chain-of-thought.

---

# 22. Agent-to-agent communication

The default pattern remains orchestrated communication:

```text
Agent A
   |
Structured Result
   |
Orchestrator / Parent Manager
   |
Agent B
```

Within an approved domain team, a parent manager may aggregate child outputs directly, but all exchanges remain structured, logged, and scoped.

Free-form uncontrolled conversations between agents are not the default architecture.

---

# 23. Error handling

Suggested error categories:

```text
MODEL_ERROR
TOOL_ERROR
PERMISSION_DENIED
POLICY_BLOCK
INVALID_INPUT
CONTEXT_MISSING
SOURCE_UNAVAILABLE
BUDGET_EXCEEDED
TIMEOUT
OUTPUT_VALIDATION_FAILED
CHILD_RUN_FAILED
CONFLICTING_WRITES
UNKNOWN_ERROR
```

The responsible manager or Orchestrator decides whether to:

- retry;
- switch model;
- switch tool;
- reduce scope;
- reassign work;
- request user input;
- stop.

Retries must be bounded.

---

# 24. Confidence, uncertainty and assumptions

Agent outputs should represent:

- known information;
- likely conclusions;
- uncertainty;
- conflicting evidence;
- unknowns;
- assumptions.

Example:

```yaml
confidence:
  level: medium
  reason: "Two primary sources agree, but one implementation detail is undocumented"

assumptions:
  - "PostgreSQL is available in the target environment"
```

Numerical confidence scores must not be presented as mathematically precise truth unless they are actually calibrated.

---

# 25. Sources and provenance

Research agents preserve source provenance.

Example:

```json
{
  "source_id": "src_456",
  "type": "web",
  "uri": "...",
  "title": "...",
  "publisher": "...",
  "retrieved_at": "...",
  "relevance": "primary legal source"
}
```

Derived claims should reference source IDs where practical.

This is particularly important for legal, financial, security, compliance, technical, and business-intelligence work.

---

# 26. Versioning

Historical runs must preserve the exact execution configuration.

Example:

```yaml
agent_id: legal_fr
agent_version: 3
prompt_version: 5
policy_version: 2
model_route_version: 4
lesson_set_version: 7
```

This enables debugging, audit, and behavioral comparison.

---

# 27. Prompts

Prompts are implementation details, not agent identity.

Prompt composition may include:

```text
Platform rules
+ Workspace rules
+ Agent mission
+ Operational lessons
+ Task instructions
+ Retrieved memory/context
+ Prior structured results
+ Tool descriptions
```

Prompts should be versioned.

Secrets must never be embedded directly in prompts.

---

# 28. Initial specialized agents

## 28.1 Project Manager

Converts objectives into projects, tasks, dependencies, priorities, milestones, and progress reports.

## 28.2 Developer Manager

Owns technical execution strategy inside approved development tasks.

It may propose worker decomposition, implementation approach, tool usage, and sequencing.

Its delegation plans are subject to Orchestrator and Policy Engine control.

## 28.3 Tester / QA

Independently verifies behavior, identifies regressions, designs tests, challenges developer assumptions, and may raise workflow challenges.

QA must not blindly trust Developer conclusions.

## 28.4 Legal Research Assistant

Researches and summarizes legal information from reliable sources, identifies uncertainty and risk, and prepares material for human review.

It is not a substitute for a qualified lawyer.

## 28.5 Outreach / Commercial Assistant

Researches prospects, prepares outreach, organizes sales context, drafts offers, and proposes follow-up actions.

External communication remains governed by policy.

## 28.6 Personal Assistant

Maintains broad situational awareness through synthesized personal context while using narrow scoped permissions for raw systems and sensitive data.

---

# 29. Future Agent Builder

Authorized users should eventually be able to create agents without editing code.

Example:

```text
Name: Security Reviewer
Mission: Review applications for common security weaknesses
Capabilities:
  [x] code_review
  [x] web_security
  [x] dependency_analysis

Tools:
  [x] Read repository
  [x] Run tests
  [ ] Push changes

Memory:
  Project only

Delegation:
  Maximum workers: 0

Model policy:
  Prefer strong reasoning
  Prefer low cost
```

Custom agents use the same Policy Engine and runtime as built-in agents.

No custom agent receives unrestricted access by default.

---

# 30. Invariants

The following rules apply across all implementations:

1. An agent is not tied to one model.
2. The Orchestrator is a core system component, not a normal agent.
3. Every execution is an isolated Agent Run.
4. An agent cannot grant itself new permissions.
5. An agent cannot bypass the Policy Engine.
6. An agent cannot silently expand task scope.
7. Tool use must be permission-checked.
8. Memory access must be scoped.
9. Agent Runs must be observable in real time.
10. Multiple independent Agent Runs may execute concurrently.
11. Domain managers may propose bounded delegation plans.
12. The Orchestrator may approve, modify, reject, or escalate delegation plans.
13. Worker agents cannot recursively create unlimited workers.
14. Agents may challenge workflow continuation.
15. Significant challenges must be explicitly reconsidered by the Orchestrator.
16. Assumptions must not be silently represented as facts.
17. Operational learning must be versioned and traceable.
18. Historical runs preserve agent/model/policy/lesson versions.
19. The Personal Assistant has broad synthesized context but narrow direct permissions.
20. The Model Router normally seeks the least expensive sufficiently capable model.

---

# 31. Open design questions

The following details remain for later specifications:

- exact JSON schemas;
- database representation of Agent Definitions and Agent Runs;
- capability matching algorithm;
- model performance scoring;
- exact delegation depth and worker limits;
- sandboxing for code execution;
- shared-file locking between parallel workers;
- lesson validation and decay;
- how general personal context is generated and refreshed;
- exact challenge-to-policy escalation rules;
- long-running run checkpoints;
- custom-agent trust model.

---

# 32. Next document

The next specification is `02-task-workflow-model.md`.

It must define:

- tasks;
- workflow plans;
- dependencies;
- user approval scope;
- adaptive continuation;
- domain-manager delegation;
- parallel execution;
- challenge handling;
- retries and fallback;
- cancellation and rollback;
- persisted workflow state;
- real-time progress;
- budget boundaries;
- what happens when a new unapproved step becomes necessary.
