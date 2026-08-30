# Novalton OS — Policy Engine

> Version: 0.1 — 19 August 2026
>
> Status: Foundational draft

## 1. Purpose

The Policy Engine is the deterministic authorization layer of Novalton OS.

Its job is to decide whether a proposed action is:

```text
ALLOW
ALLOW_WITH_LOG
REQUIRE_CONFIRMATION
BLOCK
```

The Policy Engine exists to prevent language models, agents, tools, or workflows from silently exceeding their authority.

The guiding rule is:

> Intelligence may propose. Policy decides.

---

# 2. Architectural position

```text
User
  |
  v
Orchestrator
  |
  v
Proposed Action
  |
  v
Policy Engine
  |
  +--> User Policies
  +--> Workspace Policies
  +--> Agent Permissions
  +--> Workflow Approval Scope
  +--> Tool Constraints
  +--> Risk Classification
  +--> Budget / Time Constraints
  |
  v
ALLOW / LOG / ASK / BLOCK
  |
  v
Tool Execution
```

No tool call that changes external or mutable state should bypass the Policy Engine.

---

# 3. Decision states

## 3.1 ALLOW

The action may execute immediately.

Example:

```text
Read a file inside an approved project scope.
```

## 3.2 ALLOW_WITH_LOG

The action may execute immediately, but the system must produce an explicit audit event and surface the action in the live activity stream.

Example:

```text
Create a generated report inside an approved workspace folder.
```

## 3.3 REQUIRE_CONFIRMATION

The action must be shown to the user with enough context to make an informed decision.

The system must not execute until approval is granted.

## 3.4 BLOCK

The action is forbidden under the current policy context.

The user may need to change policy explicitly before the action can ever proceed.

## 3.5 Agent challenges are not ApprovalRequests

An Agent's `HUMAN_REVIEW_RECOMMENDED` signal does not originate from deterministic Policy and must
not manufacture an `ApprovalRequest` claiming a `REQUIRE_CONFIRMATION` effect. Its trusted human
decision is represented by the dedicated Agent challenge-resolution record.

Challenge resolution cannot override Policy `BLOCK`. The resolution service evaluates the fixed
`workflow.challenge.resolve` action for the server-established `local_user` actor and exact task
scope; a matching `BLOCK` prevents either challenge decision. Other Policy and Approval records
retain their existing meaning and scope. Resolving a challenge grants no action or tool authority.

---

# 4. Strictness ordering

When multiple applicable rules disagree, the stricter result wins.

```text
BLOCK
  >
REQUIRE_CONFIRMATION
  >
ALLOW_WITH_LOG
  >
ALLOW
```

This ordering applies unless a higher-priority explicit user policy intentionally overrides a lower-level default that is designed to be overridable.

Hard platform safety constraints, where present, are never weakened by lower-level policy.

---

# 5. Policy source priority

Policy sources are evaluated in priority order.

Recommended hierarchy:

```text
1. Platform hard constraints
2. Explicit user policy
3. Workspace policy
4. Workflow approval scope
5. Agent permission profile
6. Tool-level constraints
7. Risk classification defaults
8. LLM advisory assessment
```

The LLM is always advisory.

It may suggest that an action looks low-risk or high-risk, but it cannot overrule deterministic policy.

---

# 6. User ownership of policy

User-defined restrictions are authoritative within their permitted scope.

Example:

> Never send an email without asking me first.

If active, the Policy Engine must require confirmation for any email-send action, even if:

- the agent considers the email harmless;
- the Orchestrator believes it is routine;
- the current workflow is otherwise approved.

Likewise, a user may define scoped allowances such as:

> You may create files inside `/workspace/projects/**` without asking.

These allowances must remain bounded by tool, workspace, and platform constraints.

---

# 7. Policy rule model

A structured policy may look like:

```yaml
id: policy_email_send_confirmation
version: 1
status: active
source: user
scope:
  workspace_id: default
subject:
  agent: outreach.default
action:
  type: email.send
effect: require_confirmation
conditions: []
priority: 100
created_at: ...
updated_at: ...
expires_at: null
```

A rule may include:

- subject;
- action type;
- resource scope;
- effect;
- conditions;
- source;
- priority;
- expiration;
- provenance;
- version;
- description;
- audit metadata.

---

# 8. Subjects

Policies may target subjects such as:

```text
USER
WORKSPACE
AGENT_DEFINITION
AGENT_RUN
DOMAIN_MANAGER
WORKER
TOOL
WORKFLOW
TASK
ROLE
```

Examples:

```yaml
subject:
  agent: developer.default
```

or:

```yaml
subject:
  role: commercial
```

or:

```yaml
subject:
  workflow_id: wf_123
```

---

# 9. Actions

Action types should use stable names.

Examples:

```text
file.read
file.write
file.delete
file.move
shell.execute
git.read
git.commit
git.push
email.read
email.draft
email.send
calendar.read
calendar.create
calendar.modify
calendar.delete
web.research
browser.navigate
database.read
database.write
secret.read
credential.use
payment.initiate
publication.publish
agent.delegate
model.escalate
policy.modify
```

New tools should map their operations onto auditable action types rather than inventing opaque free-form permissions.

---

# 10. Resource scopes

A policy should be able to limit where an action applies.

Examples:

```yaml
resource:
  type: filesystem
  path: /workspace/projects/**
```

```yaml
resource:
  type: github_repository
  repository: Caratrac22/novalton-os
```

```yaml
resource:
  type: email_recipient
  domain: example.com
```

Scopes may include:

- workspace;
- project;
- client;
- repository;
- branch;
- file path;
- mailbox;
- recipient;
- calendar;
- database;
- document set;
- tool instance;
- API provider.

---

# 11. Conditions

Rules may depend on conditions.

Examples:

```yaml
conditions:
  - field: local_time
    operator: after
    value: "22:00"
```

```yaml
conditions:
  - field: estimated_cost_eur
    operator: greater_than
    value: 0.10
```

```yaml
conditions:
  - field: risk_level
    operator: in
    value: [high, critical]
```

Possible contextual fields include:

- time;
- weekday;
- action count;
- cost;
- data sensitivity;
- workflow approval state;
- destination;
- branch protection;
- reversibility;
- agent role;
- project;
- user presence;
- confidence;
- risk score;
- environment.

---

# 12. Natural-language Policy Builder

Novalton OS should allow authorized users to define policies in natural language.

Example input:

> The commercial assistant may draft emails, but it must always ask me before sending one after 22:00.

The system must **not** activate a raw LLM interpretation directly.

The required pipeline is:

```text
Natural-language request
        |
        v
LLM policy parser
        |
        v
Candidate structured rule
        |
        v
Schema validation
        |
        v
Semantic checks
        |
        v
Simulation / impact preview
        |
        v
User approval
        |
        v
Policy activation
```

The LLM translates intent into candidate structure.

The deterministic engine validates and enforces the final rule.

---

# 13. Natural-language ambiguity

If the original instruction is ambiguous, Novalton OS should not silently choose the most permissive interpretation.

Example:

> Let the assistant handle my emails.

This is ambiguous because "handle" might mean:

- read;
- summarize;
- draft;
- send;
- archive;
- delete;
- label.

The Policy Builder should either:

- ask the user to clarify;
- or propose a conservative structured interpretation for review.

Example:

```text
I interpreted this as:
✓ read email
✓ summarize email
✓ draft replies
✗ send replies
✗ delete email

Activate this policy?
```

---

# 14. Simulation mode

Simulation is a first-class Policy Engine feature.

The purpose is to answer:

> What would happen if this policy were active?

Simulation must not execute real-world side effects.

It evaluates policy decisions against synthetic or historical action examples.

---

# 15. Policy simulation modes

## 15.1 Single-action simulation

Example:

```text
Simulate:
Commercial Agent -> email.send -> client@example.com -> 23:05

Result:
REQUIRE_CONFIRMATION

Matched rules:
1. User policy: email send after 22:00 -> REQUIRE_CONFIRMATION
2. Commercial default: email.send -> REQUIRE_CONFIRMATION
```

## 15.2 Workflow simulation

A user may preview the permission impact of an entire workflow before launching it.

Example:

```text
Workflow contains 14 proposed actions:

8  -> ALLOW
3  -> ALLOW_WITH_LOG
2  -> REQUIRE_CONFIRMATION
1  -> BLOCK
```

The UI should identify exactly which action is blocked and why.

## 15.3 Policy-change simulation

Before activating a new rule, Novalton OS should compare current behavior with proposed behavior.

Example:

```text
Policy change impact

Before:
email.send -> REQUIRE_CONFIRMATION

After:
email.send to @novalton.fr during approved workflow -> ALLOW_WITH_LOG

Affected historical action patterns: 18
Newly auto-allowed patterns: 6
Newly blocked patterns: 0
```

This is especially important for powerful or broad policies.

---

# 16. Simulation safety

Simulation must be non-executing by default.

No external API call that causes side effects should occur merely to test policy.

Where tool metadata is required, simulation should use:

- cached capabilities;
- mock requests;
- dry-run APIs where explicitly supported;
- static action descriptors.

Simulation results should clearly state when they are incomplete because runtime context is unavailable.

---

# 17. Confirmation UX

When the Policy Engine returns `REQUIRE_CONFIRMATION`, the user should receive a concise approval card.

Example:

```text
Action proposed

Agent: Commercial Assistant
Action: Send email
Recipient: client@example.com
Reason: Follow-up requested in approved workflow
External effect: Yes
Reversible: No
Estimated API cost: €0.002
Matched policy: "Always confirm email sending"

[Approve once]
[Approve for this task]
[Modify]
[Reject]
```

The interface should expose enough information for informed consent without drowning the user in implementation details.

---

# 18. Approval scope

Approvals must have explicit scope.

Possible scopes:

```text
ONE_ACTION
TASK
WORKFLOW
RESOURCE
TIME_WINDOW
SESSION
```

Example:

```yaml
approval:
  action: file.write
  resource: /workspace/projects/novalton-os/**
  scope: workflow
  workflow_id: wf_123
```

Approval should never automatically extend to unrelated actions.

---

# 19. Temporary permissions

The user may grant temporary permissions.

Examples:

> Allow the Developer to write inside Project X for this workflow only.

> Allow the Personal Assistant to read my calendar for the next hour.

Temporary grants should support expiration by:

- one action;
- one task;
- one workflow;
- session;
- duration;
- absolute date/time.

---

# 20. Permission expiration

Every temporary permission must have explicit expiry semantics.

Example:

```yaml
expires:
  type: workflow_end
  workflow_id: wf_123
```

or:

```yaml
expires:
  type: timestamp
  value: 2026-08-19T18:00:00+02:00
```

Expired grants must not remain silently active.

---

# 21. Baseline risk model

The Policy Engine may use baseline risk categories.

```text
LOW
MEDIUM
HIGH
CRITICAL
```

The risk system helps determine defaults, but explicit policies remain authoritative.

Possible dimensions:

- reversibility;
- external side effects;
- financial impact;
- data sensitivity;
- destructive scope;
- number of affected resources;
- privilege level;
- public visibility;
- legal significance;
- security impact.

---

# 22. Baseline examples

Typical defaults may include:

| Action | Baseline decision |
|---|---|
| Read project file | ALLOW |
| Web research | ALLOW |
| Create temp file in approved workspace | ALLOW_WITH_LOG |
| Modify source code in approved task | ALLOW_WITH_LOG or REQUIRE_CONFIRMATION depending on scope |
| Git commit | REQUIRE_CONFIRMATION or scoped workflow approval |
| Git push | REQUIRE_CONFIRMATION |
| Send external email | REQUIRE_CONFIRMATION |
| Delete significant user data | REQUIRE_CONFIRMATION |
| Read secret | REQUIRE_CONFIRMATION or BLOCK |
| Change agent permissions | REQUIRE_CONFIRMATION |
| Modify Policy Engine rules | REQUIRE_CONFIRMATION |
| Initiate payment | REQUIRE_CONFIRMATION |

These are defaults, not universal truths.

---

# 23. Mandatory-confirmation categories

Some categories should normally require explicit confirmation unless the user intentionally creates a narrower high-trust policy that is allowed to override the default.

Recommended categories:

- external email sending;
- public publication;
- payment initiation;
- destructive deletion;
- access to secrets;
- credential export;
- protected-branch push;
- policy changes;
- permission expansion;
- model escalation that increases cost materially;
- actions with significant legal or contractual consequence.

---

# 24. Workflow approval interaction

Approving a workflow may authorize known low/medium-risk steps within its explicit scope.

Example:

```text
Approved workflow:
1. Research prospect
2. Draft offer
3. Generate project plan
4. Create internal project files
```

Internal steps may continue automatically if policy permits.

However, if the workflow later attempts:

```text
5. Send the offer externally
```

and email sending requires confirmation, workflow approval does not bypass that rule.

---

# 25. Plan changes

All material workflow plan changes must be visible to the user.

The Orchestrator may discover a new required step.

Example:

```text
Original plan:
Research -> Draft -> Review

New requirement discovered:
Research -> Draft -> Legal Check -> Review
```

The new step must appear in the live plan.

The Policy Engine determines whether explicit re-approval is required.

The system must never silently expand permission scope merely because the Orchestrator changed the workflow.

---

# 26. Agent permission requests

An agent may request additional permission, but cannot grant it to itself.

Example:

```json
{
  "permission_request": {
    "action": "git.push",
    "resource": "Caratrac22/novalton-os",
    "branch": "feature/auth",
    "reason": "Push completed implementation for review",
    "requested_scope": "one_action"
  }
}
```

The request is evaluated by the Policy Engine and may result in:

```text
ALLOW
REQUIRE_CONFIRMATION
BLOCK
```

---

# 27. Model escalation policy

Technical fallback and capability escalation are separate concepts.

## 27.1 Technical fallback

If a model fails because of:

- API outage;
- timeout;
- malformed response;
- provider error;
- transient rate limit;
- detected infinite loop;

Novalton OS may retry or switch to an equivalent permitted fallback automatically within bounded retry rules and budget.

## 27.2 Capability escalation

If the system concludes that the current model is not sufficiently capable for the task, moving to a meaningfully more expensive or premium model should normally require user approval.

Example:

```text
Current worker: DeepSeek V4 Flash Free
Detected issue: repeated low-quality architecture output
Proposed escalation: stronger paid reasoning model
Expected additional cost: €0.07

[Approve]
[Choose model]
[Cancel]
```

The Policy Engine treats this as `model.escalate`.

---

# 28. Budget-aware policy

Budget constraints are part of authorization.

Policies may cap:

- Agent Run cost;
- workflow cost;
- daily cost;
- monthly cost;
- model-specific cost;
- provider-specific cost.

Example:

```yaml
budget_policy:
  monthly_eur: 5.00
  workflow_eur: 0.25
  run_eur: 0.05
```

If the estimated operation exceeds an active cap, the action should be blocked or require explicit budget override depending on policy.

---

# 29. Allowed free-model policy

The initial Novalton OS configuration intentionally restricts free cloud models to a small trusted allowlist rather than routing through arbitrary free endpoints.

Initial preferred free candidates:

```text
Nemotron Ultra Free
DeepSeek V4 Flash Free
```

Other free models are not automatically eligible unless intentionally added to policy/configuration.

Low-cost paid models may be preferred over unknown free models when reliability is better.

---

# 30. Policy simulation for budget changes

Simulation should show the impact of budget rules.

Example:

```text
If workflow cap changes from €0.10 to €0.30:

- 12 historical workflows unaffected
- 4 workflows would avoid user interruption
- 2 premium escalations would become auto-eligible
- estimated monthly worst-case exposure increases by €1.20
```

This allows policy tuning without blindly loosening control.

---

# 31. Audit trail

Every meaningful policy decision must be auditable.

Audit events should record:

- action requested;
- requesting agent/run;
- workflow/task;
- resource;
- matched rules;
- final decision;
- user confirmation if any;
- approval scope;
- timestamps;
- policy versions;
- execution result.

Example:

```json
{
  "event": "policy.decision",
  "action": "email.send",
  "decision": "REQUIRE_CONFIRMATION",
  "matched_rules": ["policy_email_send_confirmation:v2"],
  "agent_run": "run_123",
  "workflow": "wf_456"
}
```

---

# 32. Explainability

The Policy Engine should be able to answer:

> Why was this action blocked?

without exposing irrelevant internal implementation details.

Example:

```text
Blocked because:
1. Developer Agent has no permission for email.send
2. Workspace policy forbids external communication from engineering agents
```

Likewise, it should explain why confirmation was requested.

---

# 33. Policy versioning

Policies must be versioned.

Historical decisions should preserve the exact versions evaluated at the time.

Example:

```yaml
policy_id: email_send_default
version: 4
```

Editing a policy creates a new version rather than rewriting history invisibly.

---

# 34. Policy lifecycle

Possible policy states:

```text
DRAFT
SIMULATING
PENDING_APPROVAL
ACTIVE
DISABLED
SUPERSEDED
EXPIRED
REJECTED
```

Natural-language-generated policies should generally begin as `DRAFT`.

---

# 35. Dry-run workflow preview

Before a complex workflow begins, the user may request a dry-run policy preview.

Example:

```text
Nova plans 21 actions.

12 ALLOW
5 ALLOW_WITH_LOG
3 REQUIRE_CONFIRMATION
1 BLOCK

Block reason:
Developer Manager requested production database write.

Potential fix:
Use staging database instead.
```

The Orchestrator may use this information to redesign the workflow before execution.

---

# 36. Safe default for unknown actions

If an action cannot be reliably mapped to an existing policy/action type, the system should not default to permissive execution.

Recommended behavior:

```text
Unknown mutating action -> REQUIRE_CONFIRMATION
Unknown high-impact action -> BLOCK or REQUIRE_CONFIRMATION
Unknown read-only action -> REQUIRE_CONFIRMATION unless explicitly safe
```

The exact mapping may evolve, but uncertainty must never silently increase authority.

---

# 37. SaaS inheritance

Future SaaS operation may introduce policy inheritance.

Example:

```text
Platform Policy
   ↓
Organization Policy
   ↓
Workspace Policy
   ↓
User Policy
   ↓
Workflow Approval
   ↓
Agent Permission
```

A tenant administrator may define organization-wide restrictions, while individual users may add stricter personal rules.

The inheritance model must prevent lower levels from weakening non-overridable higher-level restrictions.

---

# 38. Policy presets

Novalton OS may later provide understandable presets such as:

```text
Strict
Balanced
Autonomous Controlled
```

The initial default behavior is **Balanced**.

Presets should expand into explicit policies rather than becoming magical hidden modes.

Users must be able to inspect what a preset actually permits.

---

# 39. Policy Engine invariants

1. A language model cannot directly grant permission.
2. An agent cannot grant itself permission.
3. A tool cannot bypass policy enforcement.
4. User restrictions are not silently weakened.
5. Conflicting rules resolve toward the stricter applicable effect.
6. Approvals are scope-bound.
7. Temporary permissions expire deterministically.
8. Policy changes are versioned and auditable.
9. Natural-language rules are simulated and confirmed before activation.
10. Simulation causes no real-world side effects by default.
11. Unknown high-impact actions do not default to allow.
12. Workflow approval does not override unrelated mandatory-confirmation policy.
13. Capability escalation to a materially more expensive model is approval-governed.
14. Policy decisions must be explainable in operational terms.
15. Future SaaS inheritance must preserve non-overridable higher-level restrictions.

---

# 40. Open design questions

Later specifications should define:

- exact policy JSON schema;
- policy expression language;
- condition operators;
- policy indexing and evaluation performance;
- conflict-resolution details for overlapping resource scopes;
- whether some user rules may explicitly override selected workspace defaults;
- how role-based access control integrates with tenant policy;
- how policy simulation samples historical activity;
- how dry-run tools expose safe metadata;
- approval-token format;
- cryptographic integrity of audit events;
- production secrets handling;
- policy migration/version compatibility.

---

# 41. Next document

The next major design document should define the **Memory Engine**.

It should specify:

- source memory;
- structured memory;
- derived memory;
- temporal versioning;
- provenance;
- confidence;
- fact vs hypothesis;
- retrieval;
- semantic search;
- project/client/user scopes;
- operational lessons;
- deletion and archival;
- contradiction handling;
- context construction for agents;
- long-term scalability.
