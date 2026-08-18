# Novalton OS — Agent Model

> Version: 0.1 — 18 August 2026
>
> Status: Foundational draft

## 1. Purpose

This document defines what an **agent** is inside Novalton OS.

An agent is **not** a model, a prompt, or a standalone chatbot.

An agent is a governed execution role with:

- a mission;
- capabilities;
- permissions;
- tools;
- memory access;
- model requirements;
- structured inputs and outputs;
- execution constraints;
- observability;
- lifecycle state.

The same agent role should be able to run with different models over time without changing its identity.

---

# 2. Core definition

Conceptually:

```text
Agent
  = Identity
  + Mission
  + Capabilities
  + Permissions
  + Tools
  + Memory Scope
  + Model Policy
  + Input Contract
  + Output Contract
  + Runtime State
  + Audit Trail
```

An agent is therefore a **logical worker** managed by the orchestrator.

It does not own the workflow.

It receives work, produces a structured result, and returns control to the orchestrator.

---

# 3. Agent identity

Every agent has a stable identity independent of the model used.

Minimum identity fields:

```yaml
id: agent_dev_default
name: Developer
slug: developer
version: 1
status: enabled
workspace_id: default
```

Recommended metadata:

```yaml
description: Builds, reviews, and modifies software
category: engineering
icon: code
created_at: ...
updated_at: ...
created_by: ...
```

The `version` field allows an agent definition to evolve without silently changing historical executions.

---

# 4. Agent mission

Each agent must have a clear mission.

Bad mission:

> Help with everything technical.

Good mission:

> Design, implement, review, and document software changes inside approved repositories while respecting project constraints, security policies, coding standards, and tool permissions.

The mission defines **what the agent is responsible for**, but not what it is allowed to execute.

Mission and permission are separate concepts.

---

# 5. Capabilities

Capabilities describe what an agent knows how to do.

Examples for a Developer Agent:

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

Examples for a Legal Research Agent:

```yaml
capabilities:
  - french_legal_research
  - rgpd_research
  - contract_analysis
  - source_comparison
  - risk_identification
  - legal_summary
```

Capabilities are used by the orchestrator to match tasks to agents.

They should eventually support metadata such as:

```yaml
- id: python
  proficiency: advanced
  confidence: 0.95
  source: built_in
```

The initial version does not need sophisticated proficiency scoring, but the schema should allow it later.

---

# 6. Permissions

Permissions define what an agent may attempt.

They are enforced by the Policy Engine and tool layer, not by prompt instructions alone.

Example:

```yaml
permissions:
  files:
    read: true
    write: true
    delete: false

  git:
    read: true
    write: true
    push: false

  email:
    read: false
    draft: false
    send: false

  shell:
    execute: true
    destructive_commands: false

  web:
    research: true

  finance:
    spend: false
```

Permissions should support at least:

- allow;
- deny;
- require confirmation;
- scoped allow.

Example:

```yaml
filesystem_write:
  mode: scoped_allow
  paths:
    - /workspace/projects/**
```

---

# 7. Tool access

Tools are the concrete mechanisms through which agents act.

Examples:

- filesystem reader;
- filesystem writer;
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

An agent may only request tools explicitly available to it.

Example:

```yaml
tools:
  - id: filesystem.read
  - id: filesystem.write
  - id: git.read
  - id: git.diff
  - id: terminal.run
  - id: web.research
```

A tool must independently verify permission before execution.

The model must never be trusted as the sole permission boundary.

---

# 8. Memory scope

Agents should not automatically receive access to all stored memory.

Each agent receives a memory scope appropriate to the task.

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

A Developer Agent working on Project A should not automatically receive unrelated client data from Project B.

The orchestrator and Memory Engine are responsible for constructing the smallest useful context.

---

# 9. Model policy

An agent should declare **requirements**, not a hard-coded model name.

Example:

```yaml
model_policy:
  capabilities_required:
    - tool_use
    - structured_output
    - strong_code_generation

  preferences:
    reasoning: high
    latency: medium
    cost: low

  allow_local: true
  allow_cloud: true
  max_cost_per_run_eur: 0.05
```

The Model Router selects a model according to:

- required capabilities;
- current availability;
- cost budget;
- latency target;
- privacy constraints;
- context window;
- provider health;
- fallback policy;
- historical performance.

Example routing candidates for a Developer Agent might include a free or low-cost coding model first, then a stronger paid fallback if the task requires it.

---

# 10. Agent input contract

Agents should receive structured inputs rather than only a raw text message.

Example:

```json
{
  "task_id": "task_123",
  "objective": "Review the authentication implementation",
  "context": {
    "project_id": "novalton-os",
    "files": [
      "backend/auth.py",
      "backend/models/user.py"
    ]
  },
  "constraints": [
    "Do not modify files",
    "Focus on security and correctness"
  ],
  "expected_output": "code_review_report"
}
```

The input may contain:

- task objective;
- relevant context;
- approved plan scope;
- constraints;
- source references;
- budget;
- deadline/priority;
- required output schema;
- tool availability;
- policy context.

---

# 11. Agent output contract

Every agent should return a structured result.

Minimum conceptual structure:

```json
{
  "status": "completed",
  "summary": "...",
  "findings": [],
  "artifacts": [],
  "sources": [],
  "risks": [],
  "uncertainties": [],
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

An agent should never silently pretend success if the task was incomplete.

---

# 12. Requested actions

An agent may propose actions, but proposals are not execution rights.

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

The orchestrator sends requested actions to the Policy Engine.

The Policy Engine then returns one of:

```text
ALLOW
REQUIRE_CONFIRMATION
BLOCK
```

Only after authorization may the tool execute the action.

---

# 13. Agent lifecycle

An agent execution should have an explicit lifecycle.

```text
CREATED
   |
   v
QUEUED
   |
   v
PREPARING_CONTEXT
   |
   v
RUNNING
   |
   +----> WAITING_FOR_TOOL
   |
   +----> WAITING_FOR_APPROVAL
   |
   +----> WAITING_FOR_INPUT
   |
   v
COMPLETED
```

Failure branches:

```text
FAILED
CANCELLED
TIMED_OUT
BLOCKED_BY_POLICY
```

This lifecycle is essential for the real-time interface.

The UI should be able to display exactly what stage an agent is in without exposing hidden reasoning.

---

# 14. Real-time observability

A core Novalton OS experience is watching agents work in real time.

The runtime should therefore emit structured events.

Examples:

```text
agent.started
agent.context_prepared
agent.model_selected
agent.tool_requested
agent.tool_started
agent.tool_completed
agent.awaiting_approval
agent.resumed
agent.completed
agent.failed
```

Example UI timeline:

```text
[17:02:01] Developer started
[17:02:02] Qwen selected
[17:02:04] Reading 5 project files
[17:02:08] Analysis completed
[17:02:09] Proposed modification to auth.py
[17:02:09] Waiting for approval
```

The system must expose operational state, not private chain-of-thought.

---

# 15. Agent-to-agent communication

Direct uncontrolled communication between agents is discouraged.

The default pattern is:

```text
Agent A
   |
   v
Structured Result
   |
   v
Orchestrator
   |
   v
Agent B
```

The orchestrator may pass all or part of Agent A's result to Agent B if relevant.

Direct agent-to-agent messaging may be introduced later for tightly scoped workflows, but it must remain observable, permissioned, and bounded.

---

# 16. Delegation

By default, specialized agents do **not** independently spawn unlimited subagents.

Delegation is controlled by the orchestrator.

A future agent may request delegation:

```json
{
  "delegation_request": {
    "capability": "security_review",
    "reason": "Authentication changes require specialist review"
  }
}
```

The orchestrator decides whether to:

- assign another existing agent;
- select a specialist model;
- reject the delegation;
- ask the user;
- continue without delegation.

This avoids recursive agent explosions and uncontrolled cost.

---

# 17. Error handling

An agent must classify failures rather than returning vague errors.

Suggested categories:

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
UNKNOWN_ERROR
```

The orchestrator may decide whether to retry, change model, change tool, request user input, or stop.

Retries should be bounded.

---

# 18. Confidence and uncertainty

Agent outputs should distinguish confidence from certainty.

Possible representation:

```yaml
confidence:
  level: medium
  score: 0.68
  reason: "Two official sources agree, but one implementation detail is undocumented"
```

Numerical confidence must not be presented as mathematically precise truth unless it is actually calibrated.

The most important requirement is semantic clarity:

- known;
- likely;
- uncertain;
- conflicting;
- unknown.

---

# 19. Sources and provenance

Agents performing research should preserve source provenance.

A source record may contain:

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

This is especially important for:

- legal research;
- finance;
- security;
- compliance;
- technical specifications;
- business intelligence.

---

# 20. Agent versioning

Agent definitions will change over time.

Historical runs must preserve which version was used.

Example:

```yaml
agent_id: legal_fr
agent_version: 3
prompt_version: 5
policy_version: 2
model_route_version: 4
```

This makes debugging and audit possible when behavior changes.

---

# 21. Prompts

Prompts are implementation details of an agent, not its identity.

An agent may use multiple prompt layers:

```text
Platform rules
  + Workspace rules
  + Agent mission
  + Task instructions
  + Retrieved memory/context
  + Tool descriptions
```

Prompts should be versioned.

Secrets must never be embedded directly in prompts.

---

# 22. Initial built-in agents

## 22.1 Orchestrator

Mission:

> Understand user intent, construct or adapt workflows, choose capabilities, route tasks, inspect results, enforce approval flow, and produce final synthesis.

Important limitation:

The Orchestrator coordinates permissions but does not bypass the Policy Engine.

## 22.2 Project Manager

Mission:

> Convert objectives into structured projects, tasks, dependencies, priorities, milestones, and progress updates.

Primary capabilities:

- planning;
- backlog creation;
- dependency analysis;
- prioritization;
- project status synthesis.

## 22.3 Developer

Mission:

> Design, write, modify, review, and document software within approved project scope.

Primary capabilities:

- architecture;
- coding;
- debugging;
- code review;
- Git;
- testing support.

## 22.4 Tester / QA

Mission:

> Independently verify software behavior, identify regressions, design tests, and challenge developer assumptions.

A key rule is that QA should not blindly trust the Developer Agent's conclusions.

## 22.5 Legal Research Assistant

Mission:

> Research and summarize legal information from reliable sources, identify uncertainty and risk, and prepare material for human review.

It must never present itself as a substitute for a qualified lawyer.

## 22.6 Outreach / Commercial Assistant

Mission:

> Research prospects, prepare outreach material, organize sales context, draft proposals, and recommend follow-up actions.

External sending actions remain subject to policy.

## 22.7 Personal Assistant

Mission:

> Help the user organize tasks, information, reminders, projects, communications, and daily workflow across Novalton OS.

Its access must remain tightly scoped because it may touch broad personal context.

---

# 23. Future agent builder

Novalton OS should eventually allow an authorized user to create an agent without editing code.

Conceptual form:

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

Model policy:
  Prefer strong reasoning
  Max cost/run: 0.10 EUR
```

Custom agents must use the same Policy Engine and runtime as built-in agents.

No custom agent receives unrestricted access by default.

---

# 24. Example complete agent definition

```yaml
id: developer.default
name: Developer
version: 1
status: enabled
category: engineering

mission: >
  Design, implement, review, and document software changes inside approved
  projects while respecting project constraints, coding standards, security
  policies, and tool permissions.

capabilities:
  - software_architecture
  - python
  - typescript
  - fastapi
  - nextjs
  - debugging
  - testing
  - git

permissions:
  filesystem:
    read: allow
    write: require_policy_check
    delete: deny
  git:
    read: allow
    commit: require_policy_check
    push: require_confirmation
  shell:
    execute: require_policy_check
    destructive: deny
  email:
    read: deny
    send: deny

memory_scope:
  read:
    - project
    - task
  write:
    - project
    - task

model_policy:
  required:
    - structured_output
    - tool_use
  preferred:
    reasoning: high
    coding: high
    cost: low
  allow_local: true
  allow_cloud: true
  max_cost_per_run_eur: 0.05

output_schema: agent_result.v1
```

---

# 25. Invariants

The following rules should remain true across all agent implementations:

1. An agent is not tied to one model.
2. An agent cannot grant itself new permissions.
3. An agent cannot bypass the Policy Engine.
4. An agent cannot silently expand task scope.
5. An agent result must have a known status.
6. Significant actions must be auditable.
7. Tool use must be permission-checked.
8. Memory access must be scoped.
9. Agent runs must be observable in real time.
10. Failures and uncertainty must be representable.
11. Historical runs must preserve agent/model/policy versions.
12. The orchestrator retains control over inter-agent workflow by default.

---

# 26. Open design questions

The following details should be resolved in later specifications:

- exact JSON schemas for agents and results;
- whether agent definitions live in PostgreSQL, version-controlled YAML, or both;
- how capability matching is scored;
- how model quality history influences routing;
- exact approval token/scope format;
- sandboxing strategy for code execution;
- agent concurrency limits;
- per-agent token/cost budgets;
- whether long-running agents can checkpoint and resume;
- how custom agents are signed/trusted in a future plugin ecosystem.

---

# 27. Next document

The next specification should define the **Task and Workflow Model**.

That document must answer:

- what a task is;
- what a workflow is;
- how dependencies work;
- how plans are approved;
- how workflows adapt after an agent result;
- what happens when the orchestrator wants to add a new step;
- how cancellation and rollback work;
- how real-time progress is represented;
- how retries and fallbacks work;
- how workflow state survives restart.

This is the next critical layer between the user, orchestrator, agents, and Policy Engine.
