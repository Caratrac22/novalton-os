# Novalton OS — Task & Workflow Model

> Version: 0.1 — 18 August 2026
>
> Status: Foundational draft

## 1. Purpose

This document defines how Novalton OS turns a user request into an executable, observable, policy-governed workflow.

It covers:

- tasks;
- plans;
- workflow steps;
- dependencies;
- approvals;
- adaptive changes;
- budgets;
- watchdog behavior;
- retries and model fallback;
- model escalation;
- pause and stop;
- checkpoints;
- recovery;
- real-time progress.

The workflow system is the execution backbone between the user, Orchestrator, specialized agents, the Model Router, the Policy Engine, tools, and memory.

---

# 2. Core concepts

Novalton OS distinguishes:

```text
User Request
    |
    v
Task
    |
    v
Workflow Plan
    |
    v
Workflow Run
    |
    +--> Step
    +--> Step
    +--> Step
```

## 2.1 Task

A Task represents the user's objective.

Example:

```json
{
  "task_id": "task_001",
  "objective": "Prepare and implement a customer portal",
  "workspace_id": "default",
  "project_id": "project_123",
  "priority": "normal",
  "created_by": "user"
}
```

A Task may generate one or more Workflow Runs over its lifetime.

## 2.2 Workflow Plan

A Workflow Plan is the Orchestrator's proposed execution strategy before or during execution.

Example:

```text
1. Project Manager clarifies scope
2. Legal Agent checks privacy implications
3. Developer Manager proposes implementation decomposition
4. Developer workers implement
5. QA verifies
6. Orchestrator summarizes results
```

The plan must be shown to the user when approval is required.

## 2.3 Workflow Run

A Workflow Run is one execution instance of an approved or policy-allowed plan.

It includes:

- current state;
- plan version;
- approval scope;
- step state;
- agent runs;
- budgets;
- events;
- checkpoints;
- warnings;
- errors;
- policy decisions.

---

# 3. Workflow state model

Suggested states:

```text
DRAFT
PLANNING
AWAITING_APPROVAL
READY
RUNNING
PAUSING
PAUSED
WAITING_FOR_INPUT
WAITING_FOR_APPROVAL
RECOVERING
COMPLETED
FAILED
CANCELLED
STOPPED
```

The state must persist so a workflow can survive process restart.

---

# 4. Step model

Each workflow step has a durable identifier and explicit dependencies.

Example:

```json
{
  "step_id": "step_dev_architecture",
  "title": "Design application architecture",
  "type": "agent_task",
  "assigned_capability": "software_architecture",
  "depends_on": ["step_scope"],
  "status": "pending",
  "risk_level": "medium",
  "approval_requirement": "covered_by_workflow",
  "estimated_cost_eur": 0.01
}
```

Possible step statuses:

```text
PENDING
READY
QUEUED
RUNNING
WAITING
AWAITING_APPROVAL
PAUSED
COMPLETED
PARTIAL
FAILED
SKIPPED
CANCELLED
BLOCKED
```

---

# 5. Dependencies and graph execution

Workflows should be modeled as a directed dependency graph rather than a rigid linear list.

Example:

```text
              Scope
             /     \
            /       \
        Legal       Architecture
            \       /
             \     /
           Implementation
              |
              v
              QA
```

Independent steps may run concurrently when:

- dependencies are satisfied;
- resources do not conflict;
- concurrency limits allow it;
- budget allows it;
- policy allows it.

The Runtime Layer must prevent unsafe concurrent modification of the same mutable resource unless explicitly coordinated.

---

# 6. Plan approval

When the Orchestrator proposes a workflow that requires approval, the user should see a clear operational summary.

Example:

```text
Proposed workflow

1. Legal Agent researches privacy obligations
2. Developer Manager creates implementation plan
3. Backend + Frontend workers run in parallel
4. QA tests the result
5. Orchestrator prepares final report

Expected external actions:
- Modify repository files
- Create test artifacts

No email will be sent.

Estimated AI cost: 0.04 EUR

[Approve] [Modify] [Cancel]
```

Approval applies only to the scope described.

---

# 7. Balanced autonomy mode

The default Novalton OS operating mode is **Balanced**.

In Balanced mode:

- internal low-risk work inside an approved plan may continue automatically;
- policy-required confirmations remain mandatory;
- meaningful plan changes are shown to the user;
- external or high-impact actions may trigger confirmation;
- model escalation that increases cost or materially changes execution requires user approval;
- the Orchestrator may ask the user whenever ambiguity or disagreement is important enough.

Future modes may include:

```text
SUPERVISED
BALANCED
CONTROLLED_AUTONOMOUS
```

Balanced remains the default.

---

# 8. Plan changes during execution

The Orchestrator may discover that the approved plan needs to change.

Every meaningful plan change must be **visible to the user**.

Examples:

- add a missing research step;
- add QA after unexpected code changes;
- split one development step into multiple workers;
- remove an obsolete step;
- reorder execution;
- add a new external action.

A change creates a new plan version.

Example:

```text
Plan v3
  -> Step 4 added: Security review
Reason: authentication architecture changed
```

The system must never silently rewrite the plan history.

Depending on policy and risk, a visible plan change may either:

- continue automatically;
- require confirmation;
- be blocked.

Visibility is mandatory even when confirmation is not.

---

# 9. Approval scope

Approval should be represented explicitly rather than as a vague boolean.

Conceptually:

```json
{
  "approval_id": "approval_123",
  "workflow_id": "wf_123",
  "plan_version": 2,
  "scope": {
    "steps": ["step_1", "step_2", "step_3"],
    "allowed_action_types": [
      "filesystem.write",
      "git.local_commit"
    ]
  },
  "expires_when": "workflow_scope_changes"
}
```

An approval does not automatically authorize newly invented actions.

---

# 10. Budget model

Novalton OS should support multiple simultaneous budget boundaries.

At minimum:

```text
PER_AGENT_RUN
PER_WORKFLOW
PER_DAY
PER_MONTH
```

Optional future scopes:

```text
PER_PROJECT
PER_WORKSPACE
PER_PROVIDER
PER_MODEL
```

The Model Router should try to remain inside budget by:

1. using an allowed free model when appropriate;
2. selecting a very low-cost paid model;
3. reducing unnecessary context;
4. reusing cached results where safe;
5. avoiding redundant parallel work;
6. requesting approval before expensive escalation.

---

# 11. Allowed free-model policy

The initial free-model pool is intentionally narrow.

Preferred free options:

- **Nemotron Ultra Free** when available and suitable, including very large-context use cases;
- **DeepSeek V4 Flash Free** when available and suitable, especially for coding and general low-cost work.

Novalton OS should not automatically rotate through arbitrary free models simply because they cost zero.

Other models should normally be selected from low-cost paid options according to capability, quality, and budget.

Premium models should be used only when justified by task difficulty, failure recovery, or user preference.

Model names and provider availability are configuration, not hard architectural dependencies.

---

# 12. Model selection inside a workflow

The Model Router combines:

- worker/manager recommendation;
- required capabilities;
- task difficulty;
- previous failures;
- quality history;
- provider health;
- available context window;
- latency;
- cost;
- current budget;
- user preferences.

A Developer Manager may recommend:

```text
"Use DeepSeek V4 Flash for backend worker"
```

or:

```text
"Need strong coding + long context, lowest reasonable cost"
```

The Router evaluates the recommendation rather than blindly obeying it.

---

# 13. Technical failure recovery

Technical failures may trigger automatic recovery without user approval when the recovery remains inside the approved scope and budget.

Examples:

- transient API error;
- rate-limit retry;
- network timeout;
- malformed provider response;
- temporary tool failure;
- model endpoint unavailable.

Possible recovery actions:

```text
RETRY_SAME_MODEL
RETRY_WITH_BACKOFF
SWITCH_EQUIVALENT_ROUTE
RESTART_FROM_CHECKPOINT
REASSIGN_WORKER
```

Retries must be bounded.

The system should avoid repeatedly retrying the same failing route without new evidence that recovery is likely.

---

# 14. Runtime Watchdog

Novalton OS includes a Runtime Watchdog responsible for detecting unproductive or pathological agent behavior.

The Watchdog is separate from the agent's own self-evaluation.

It may monitor signals such as:

- repeated identical or near-identical tool calls;
- repeated API errors;
- excessive retries;
- repeated invalid structured outputs;
- lack of measurable progress;
- excessive elapsed time relative to task type;
- unexpectedly high token usage;
- repeated planning without execution;
- repeated contradictions;
- repeated loops over the same subproblem;
- runaway child-worker creation attempts;
- worker stuck waiting for a resource that will not resolve;
- repeated context requests without new information.

The Watchdog does not need access to private chain-of-thought.

It operates on observable runtime behavior, events, outputs, tool calls, counters, and validated progress signals.

---

# 15. Watchdog severity levels

Suggested levels:

```text
NORMAL
SUSPICIOUS
DEGRADED
STUCK
ABORT_RECOMMENDED
```

Example policy:

```text
SUSPICIOUS
→ emit warning

DEGRADED
→ attempt bounded recovery

STUCK
→ stop or checkpoint worker and re-evaluate

ABORT_RECOMMENDED
→ terminate worker as safely as possible and return control to manager/orchestrator
```

The exact thresholds must be configurable and learned from real usage over time.

---

# 16. Progress detection

The Watchdog should not define progress only as "the model is still generating tokens".

Useful progress signals may include:

- new validated artifact produced;
- new source discovered;
- new test completed;
- task subgoal marked complete;
- code diff changed meaningfully;
- error count reduced;
- dependency resolved;
- new structured finding produced;
- tool output advanced the task state.

Repeated prose without state advancement should not count as reliable progress.

---

# 17. Model insufficiency detection

A model may be technically healthy but insufficient for the task.

Possible evidence:

- repeated low-quality outputs after correction;
- inability to satisfy output schema;
- repeated incorrect tool usage;
- failure to integrate required context;
- repeated QA rejection;
- repeated contradiction with validated sources;
- manager assessment that task complexity exceeds the current worker/model profile.

This is different from an API failure.

---

# 18. Model escalation

When a worker appears insufficient rather than technically broken, Novalton OS may propose escalation to a stronger model.

Escalation that materially increases expected cost requires user approval in Balanced mode.

Example:

```text
Worker stopped after insufficient progress.

Current model:
DeepSeek V4 Flash Free

Reason:
- 3 rejected implementation attempts
- QA found the same architectural defect twice

Proposed escalation:
Stronger reasoning/coding model

Estimated additional cost:
0.06 EUR

Resume from checkpoint:
Yes

[Approve] [Choose Model] [Cancel]
```

The system should explain why escalation is proposed.

---

# 19. Fallback vs escalation

Novalton OS distinguishes:

## 19.1 Fallback

Used for technical route failure or equivalent substitution.

Example:

```text
Provider endpoint unavailable
→ use equivalent approved route
```

May happen automatically if inside policy/budget.

## 19.2 Escalation

Used when a more capable model is needed.

Example:

```text
Current model cannot solve architecture task reliably
→ propose stronger model
```

In Balanced mode, paid escalation with meaningful additional cost requires user approval.

---

# 20. Checkpoints

Long or expensive steps should support checkpoints.

A checkpoint may contain:

- completed subgoals;
- current structured state;
- generated artifacts;
- validated intermediate results;
- tool outputs worth preserving;
- relevant memory references;
- unresolved issues;
- current plan/agent/model versions.

The goal is to resume useful work without blindly restarting from zero.

Example:

```text
Backend Worker
Progress: 72%
Checkpoint created

Completed:
- data model
- auth endpoints
- validation layer

Remaining:
- migration
- integration tests
```

---

# 21. Checkpoint safety

A checkpoint must not automatically certify that previous work is correct.

Recovered work may need:

- validation;
- QA review;
- source re-check;
- conflict detection;
- environment verification.

Checkpoints preserve state, not truth.

---

# 22. Pause

`Pause` is a controlled suspension.

Desired behavior:

1. stop scheduling new steps;
2. let currently executing atomic operations reach a safe boundary where possible;
3. create checkpoints;
4. persist workflow state;
5. release resources that do not need to remain locked;
6. enter `PAUSED`.

The UI should show what is still finishing during `PAUSING`.

---

# 23. Stop

`Stop` requests termination as quickly as safely possible.

Desired behavior:

- cancel model generation where supported;
- stop new tool calls;
- terminate worker runs where supported;
- avoid starting recovery retries;
- attempt to preserve the last safe checkpoint;
- mark unfinished work clearly;
- record which actions may already have completed externally.

Some external operations cannot be undone merely because Stop was pressed.

The UI must make this explicit.

---

# 24. Cancellation and side effects

Before executing actions with side effects, the workflow should know whether they are:

```text
REVERSIBLE
COMPENSATABLE
IRREVERSIBLE
UNKNOWN
```

Examples:

```text
Create temporary file
→ REVERSIBLE

Create Git commit locally
→ REVERSIBLE

Send email
→ effectively IRREVERSIBLE

External API mutation
→ depends on API
```

This information should influence policy, approval, Stop behavior, and recovery.

---

# 25. Rollback and compensation

Novalton OS should not pretend every action can be rolled back.

When possible, workflows may define compensation actions.

Example:

```text
Create temporary deployment
→ compensation: destroy deployment
```

Compensation itself must pass policy checks.

A failed compensation must be visible to the user.

---

# 26. Agent disagreement during a workflow

When agents disagree, the Orchestrator evaluates:

- severity;
- evidence;
- policy impact;
- source quality;
- reversibility;
- cost of independent verification.

It may:

```text
DECIDE
REQUEST_SECOND_OPINION
MODIFY_PLAN
ASK_USER
STOP
```

The Orchestrator is allowed to decide routine low-risk disagreements.

For important ambiguity, significant risk, or unresolved contradiction, it should ask the user.

A challenge such as `HUMAN_REVIEW_RECOMMENDED` or `BLOCK_RECOMMENDED` forces explicit reconsideration rather than silent continuation.

---

# 27. Domain-manager workflow adaptation

A domain manager, such as Developer Manager, may propose changes inside its technical execution domain.

Example:

```text
Developer Manager:
"Split implementation into backend and frontend workers, then run QA."
```

The Orchestrator may:

```text
APPROVE
MODIFY
REJECT
REQUEST_MORE_DETAIL
ASK_USER
```

The approved delegation becomes part of the workflow plan and is visible in real time.

---

# 28. Worker replacement

A manager or Orchestrator may replace a worker when:

- technical failure persists;
- the worker is stuck;
- provider becomes unavailable;
- Watchdog detects pathological behavior;
- the worker repeatedly fails validation;
- the task needs a different specialization.

Equivalent low-cost replacement may occur automatically if inside policy.

Replacing a worker with a materially more expensive or substantially stronger model follows escalation rules.

---

# 29. Real-time event model

The workflow runtime should emit structured events.

Examples:

```text
workflow.created
workflow.plan_proposed
workflow.awaiting_approval
workflow.approved
workflow.started
workflow.plan_changed
workflow.pausing
workflow.paused
workflow.resumed
workflow.stop_requested
workflow.stopped
workflow.completed
workflow.failed

step.ready
step.started
step.completed
step.failed

watchdog.warning
watchdog.recovery_started
watchdog.worker_stopped

model.fallback
model.escalation_proposed
model.escalation_approved

checkpoint.created
checkpoint.restored
```

These events drive the live interface and audit trail.

---

# 30. Real-time UI expectations

The user should be able to see:

```text
Workflow: Customer Portal

✓ Scope
✓ Legal review

Developer Manager
├─ Backend Worker      72%
├─ Frontend Worker     48%
└─ QA Worker           waiting

Budget
Workflow: 0.027 / 0.10 EUR
Month:    1.82 / 5.00 EUR

Latest event
Backend checkpoint created
```

Progress percentages should only be shown when they are based on meaningful task structure or validated estimates.

The UI must not invent fake precision merely to look active.

---

# 31. Budget exhaustion behavior

When a budget threshold approaches, the Orchestrator should first try to reduce cost without degrading required quality excessively.

Possible actions:

- use an allowed cheaper route;
- reduce redundant context;
- postpone non-critical work;
- serialize unnecessary parallel workers;
- reuse validated existing results;
- ask whether the user wants to increase the budget.

When the hard budget limit is reached:

```text
PAUSE_OR_STOP_COSTLY_WORK
PRESERVE_STATE
REPORT_WHAT_REMAINS
ASK_USER_IF_NEEDED
```

The system must never silently exceed a hard user-defined budget.

---

# 32. Recovery after system restart

Workflow state must be persisted sufficiently to survive backend or host restart.

On restart, Novalton OS should determine:

- which workflows were active;
- which steps completed;
- which agent runs were interrupted;
- which external actions may have already executed;
- which checkpoints are valid;
- whether provider/tool state needs revalidation.

The system must not blindly replay side-effecting tool calls after restart.

---

# 33. Idempotency

Where possible, tool actions should use idempotency keys or duplicate-detection mechanisms.

This is especially important for:

- API mutations;
- document creation;
- ticket creation;
- job submission;
- payment-like future integrations;
- email draft generation;
- workflow recovery.

Irreversible operations that cannot be made idempotent require stronger confirmation and logging.

---

# 34. Auditability

A Workflow Run should preserve enough information to answer:

- what did the user request?
- what plan was proposed?
- what did the user approve?
- how did the plan change?
- which agents ran?
- which models were used?
- what tools were called?
- what warnings occurred?
- what was retried?
- what was escalated?
- what did it cost?
- what external side effects occurred?
- what final result was produced?

---

# 35. Example workflow

User request:

> Build a small internal CRM.

Possible execution:

```text
1. Orchestrator analyzes request
2. Project Manager creates scope
3. User sees proposed workflow
4. User approves
5. Developer Manager proposes:
   - Backend Worker
   - Frontend Worker
   - QA Worker
6. Orchestrator approves delegation
7. Backend + Frontend run in parallel
8. Watchdog monitors both
9. Backend model loops repeatedly
10. Watchdog stops backend worker
11. Equivalent fallback is attempted
12. Fallback still fails quality checks
13. Developer Manager proposes stronger model
14. Orchestrator shows escalation + estimated cost
15. User approves
16. Stronger backend worker resumes from checkpoint
17. QA tests integrated result
18. QA raises WARNING
19. Orchestrator adds visible fix step
20. Developer fixes issue
21. QA passes
22. Orchestrator produces final report
23. Workflow completes
```

---

# 36. Invariants

1. Workflow plan history is versioned.
2. Meaningful plan changes are visible to the user.
3. Approval is scoped, not unlimited.
4. Balanced mode is the default.
5. Hard user budgets cannot be silently exceeded.
6. Free-model selection is intentionally restricted.
7. Technical fallback and capability escalation are different mechanisms.
8. Equivalent technical fallback may be automatic when policy allows.
9. Paid/stronger-model escalation requires approval when it materially increases cost in Balanced mode.
10. The Watchdog observes runtime behavior independently from agent self-report.
11. Retries are bounded.
12. Progress must be based on meaningful state advancement.
13. Long work should support checkpoints.
14. Pause and Stop have different semantics.
15. Stop cannot guarantee reversal of already completed external actions.
16. Restart recovery must avoid blindly replaying side effects.
17. Agent disagreement must be explicitly reconsidered by the Orchestrator.
18. Important unresolved ambiguity may be escalated to the user.
19. Domain managers may propose workflow adaptation within their expertise.
20. Workflow execution must remain auditable.

---

# 37. Open design questions

The following implementation details remain for later documents:

- exact Watchdog thresholds;
- progress-scoring algorithm;
- maximum automatic retry counts by error type;
- exact pricing cache and provider-cost refresh mechanism;
- how model quality history is scored;
- checkpoint storage format;
- step locking and distributed concurrency;
- workflow scheduler implementation;
- persistence model and event-store strategy;
- idempotency implementation per tool;
- which plan changes require confirmation versus visibility only;
- exact user controls for budget overrides;
- exact behavior for partial external failure;
- future controlled-autonomous mode rules.

---

# 38. Next specification

The next specification should define the **Policy Engine** in detail.

It must define:

- permission representation;
- user policies;
- workspace policies;
- action risk classification;
- approval rules;
- approval scope;
- policy precedence;
- irreversible action handling;
- escalation from agent challenges;
- tool enforcement;
- audit logging;
- how LLM risk hints are used without becoming the final authority.
