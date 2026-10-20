# Durable task dispatch — implementation design

Status: DESIGN ONLY, 2026-10-20. This document does not enable a background worker,
automatic provider retries, new tool permissions, or unattended mutations.

## Existing foundation

The current `Task` already persists BACKLOG, READY, IN_PROGRESS, BLOCKED, REVIEW,
DONE and CANCELLED. `WorkflowPlan` versions and dependencies, `WorkflowRun`,
`WorkflowStepRun`, typed handoffs, `AgentRun`, `ModelRun`, `ToolCall`, approvals,
challenge resolutions, runtime events and audit records are durable. Reuse them.
`orchestrator.service.advance` claims at most one READY step with compare-and-set;
it is the execution entry point, not an implementation to duplicate in a scheduler.

Task status is user-editable metadata. It must not by itself authorize a model
call, a new workflow, a mutation, a commit or publication. A completed workflow
and a user task marked DONE are also distinct facts today.

## Prerequisites before unattended dispatch

1. Pass recovery and concurrency database tests and installed I-044A gates.
2. Pass the initial-step/linkage/start recovery tests. Mission 2 adds terminal
   recovery at these boundaries, including cancellation of never-started linked
   runs. An unlinked orphan is retained without inferred reassignment. None of
   these uncertain attempts is silently rerun.
3. Define and test cancellation during provider activity. A cancelled workflow
   must not accept a late proposal or start an additional provider continuation.
4. Pass terminal-linkage regression tests. The mission-2 link predicate now
   rejects a terminal step or workflow, preserving empty linkage after a delayed
   producer returns. This is not cancellation of an already dispatched provider.
5. Prove one fresh Manager → Developer → QA workflow with an explicitly configured
   real provider. Transport/schema unit tests are necessary, not a live proof.

## Proposed persisted scheduling records

Add a small scheduling module alongside `orchestrator`, not another execution
engine. A migration should create a dispatch record bound to an existing task
and an explicit existing workflow run. Include tenant/workspace/project/task/run
scope, immutable request key, priority, eligible time, lifecycle state, owner,
monotonic claim generation, lease deadline, attempt count, stop reason and timestamps.
Use scoped foreign keys rather than trusting caller-supplied IDs independently.

States: READY, LEASED, WAITING_HUMAN, BLOCKED, DONE, CANCELLED. Map an active QA
step to a VERIFYING presentation label, not a second source of workflow truth.
Use a partial unique index for one active dispatch per task and one per workflow.
Repeated enqueue with the same request key returns the existing binding; a key
with different immutable input fails. Re-execution requires a new explicit run.

Append a dispatch-attempt row for each claim: claim generation, start/end times,
workflow/step references, pre/post status, outcome and bounded reason codes. Keep
provider/model/tool/approval evidence in its existing tables and reference it.
Never copy raw provider content, source files, keys or arbitrary exception text.

## Claim and execution protocol

Within one short transaction, select an eligible READY row in the requested
workspace with `FOR UPDATE SKIP LOCKED`. Order by priority descending, eligible
time then stable ID; add bounded aging only after starvation tests. Check explicit
dispatch opt-in, dependencies, budgets and run status. Increment the generation,
reserve one attempt and mark LEASED atomically. Commit before network work.

Call the existing scoped `advance` once. Never hold a queue row lock throughout
a provider call. Persist the resulting classification with a generation/owner CAS:

- STEP_COMPLETED with another eligible step: READY, subject to remaining budget.
- WORKFLOW_COMPLETED: DONE only for the matching persisted completed workflow.
- WAITING_FOR_HUMAN or a pending exact approval/challenge: WAITING_HUMAN.
- WORKFLOW_FAILED, an uncertain interruption, or exhausted budget: BLOCKED.
- CANCELLED: CANCELLED.
- No ready step while active work exists: wait for that existing work; do not
  manufacture another AgentRun or poll into a duplicate provider invocation.

A WAITING_HUMAN task releases the scheduler's claim. Another independent READY
task can be selected. A human decision updates the existing approval/challenge
record; a trusted dispatcher observes it and classifies the same workflow again.
Queue state never counts as approval and cannot choose or approve a correction.

## Restart, fencing and side effects

Use database time for leases. A heartbeat and every attempt completion must carry
the exact owner and generation. An expired owner may not extend or finalize a
new owner's claim. A queue lease by itself does not fence existing AgentRun or
ToolCall producers; enforce the generation at their trusted reservation boundary
before allowing overlapping ownership. Until that integration is proved, an
expired LEASED dispatch with uncertain execution becomes BLOCKED, never READY.

The existing one-hour continuation lease is a fail-closed recovery bound, not
permission for the scheduler to retry. Do not shorten it to match a poll interval.
A provider request can have succeeded externally before a crash prevented local
accounting. Exactly-once billing or generation cannot be promised without a
provider-supported idempotency/reconciliation contract. Record uncertainty.

I-041 exact mutation fingerprints and approval linkage, I-042 commit proofs and
I-043 publication reconciliation remain the authority for their respective effects.
The scheduler cannot replay these effects, infer success from a timeout, or
transfer an approval from an old mutation to a later repair.

## Budgets and stop conditions

Persist bounded step/attempt counts, a deadline and a model-call budget. Reserve
capacity transactionally before dispatch. A zero budget or expired deadline blocks
new work. Cost reservations need an explicit unknown-cost policy for models whose
price is absent; unknown is not zero. Keep existing per-AgentRun verification and
continuation limits, and never use a task budget to enlarge those permissions.
The server operator must explicitly opt a workspace into unattended model calls.

## Required acceptance matrix

| Scenario | Required result |
| --- | --- |
| Two workers claim the same row | One owner/generation and one `advance` |
| Same enqueue key, different input | Conflict; no second run |
| Restart before `advance` | Reconcile recorded attempt; no blind retry |
| Restart during provider or mutation | Uncertain attempt BLOCKED; no replay |
| Old owner returns after lease expiry | CAS rejected; no new proposal authority |
| Task A waits for approval | A remains WAITING_HUMAN; independent B runs |
| Dependencies, tenant or workspace mismatch | Claim denied; no model call |
| Budget exhaustion, cancellation, deadline | No further provider/tool reservation |
| QA PASS versus FAIL or human review | Durable workflow outcome determines queue state |
| Repeated old approval | No new mutation, continuation or queue claim |

Implementation order: close the prerequisite gaps; add migration plus repository
claim/CAS tests on disposable `novalton_test`; add a bounded one-tick trusted runner;
prove restart/approval/fencing cases; only then add a long-running worker and UI.
