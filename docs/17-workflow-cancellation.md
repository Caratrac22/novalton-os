# Cancellation during provider activity

Cancellation is a monotonic persisted workflow authority fence. The scoped empty-body
POST `/workflow-runs/{id}/cancel` is idempotent. It commits CANCELLED and one runtime
event before projecting unfinished steps to CANCELLED in a separate restart-safe
transaction. A crash between these commits cannot restore execution authority;
repeated cancellation or advance completes the projection.

Short PostgreSQL transaction advisory locks serialize cancellation with linked
AgentRun starts, ModelRun reservations, ToolCall proposals, prepared mutation
execution and continuation claims. Reservations acquire AgentRun row locks before
the workflow guard; cancellation never acquires an AgentRun or ToolCall lock.
No advisory lock is held across provider network I/O. Each reservation rechecks
the durable workflow state, including repeated old approval requests.

An already reserved provider request may still finish or incur cost. Its actual
success/failure and usage remain ModelRun evidence. A RUNNING tool may already have
applied its exactly approved effect; cancellation does not pretend to undo it.
The workflow fence prevents its result from granting another model reservation,
tool or continuation. Late workflow completion/handoff processing is fenced and
lost cancellation races return the durable CANCELLED orchestration outcome.

This is cooperative authority revocation, not a claim of upstream provider
transport cancellation. It does not add shell authority, change I-044 verification
limits, grant approvals, or retry uncertain operations. Standalone AgentRuns retain
their existing behavior. Cross-scope AgentRun links fail closed.

Validation must cover Manager/Developer/QA late responses, truncated responses and
provider failures; no new ModelRun/ToolCall reservation after cancellation; exact
approval replay; repeated concurrent cancellation; and crash after the fence commit.
The durable dispatcher must use these same reservation fences.
