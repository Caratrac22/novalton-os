# I-044 controlled verification

## V1 contract

`verify.backend_syntax` version 1 is the single registered command. Parameters
must be the empty object. It checks Python syntax beneath `apps/api/src` and
`apps/api/tests` in the immutable I-044A snapshot. It does **not** execute pytest,
Ruff, application imports, test bodies, or project dependencies. Passing means
syntax validity only, never functional correctness or QA approval.

The model proposes `{command_id: "verify.backend_syntax", parameters: {}}` through
its existing ToolProposal. Unknown fields and targets are rejected. Executable,
argv, shell, cwd, environment, timeout, DB, signals, mounts and output destinations
are not part of this protocol. The API never starts a verification process.

The gateway requires all of: Developer Worker identity, exact immutable permission,
assignment permission, and deterministic Policy ALLOW or ALLOW_WITH_LOG for
`tool.verify.backend_syntax`. Risk is server-owned LOW/read-only. BLOCK denies;
REQUIRE_CONFIRMATION denies with `verification_policy_requires_allow`. No default
Policy permission is silently installed. Manager and QA cannot execute this tool.

## Deployment and containment

The API workspace must be `/srv/novalton/workspace`. The trusted I-044A systemd unit
binds this literal path read-only into the service. The root-owned deployment parent
must not be writable by the API identity; only the workspace contents are mutable.
A different API root fails closed. IPC still accepts no source path or descriptor.
The adapter compares its live digest to the worker-prepared snapshot before launch,
and again after completion. Metadata of the entire live tree, including `.git`,
staged index and excluded/dirty files, is compared before and after verification;
a change fails with `unexpected_workspace_mutation`. Linked Git worktrees are not
supported by this V1 integrity contract. These checks detect concurrent edits; the
OS read-only snapshot is the primary prevention of verifier writes to live source.

The release-owned containment probe invokes one fixed release-owned stdlib syntax
checker with isolated Python (`-I -S -B`), empty environment, closed stdin, no PTY,
and a two-second subprocess timeout. It compiles bytes without evaluating code.
At most 4,096 Python files, 2 MiB per file and four diagnostics are admitted, further
bounded by the existing snapshot size, memory, PID, CPU and wall-clock limits.
The existing seccomp, AppArmor, namespaces and descendant cleanup remain active.
The containment probe's intentional timeout does not prove syntax completion:
there must also be a separate valid checker result, exit classification, and clean
snapshot/scratch/cgroup disposal. Timeout, missing source and infrastructure errors
fail the tool and do not authorize a syntax repair.

No provider, GitHub, SSH, proxy or database credentials enter the sandbox. This is
DB-free verification. No network or database profile can be supplied. Diagnostics
contain only a bounded relative filename and a literal code, never source lines,
compiler exception text or raw output. Invalid filename characters are redacted.
Invalid encodings/NUL are failed syntax data. The checker produces bounded JSON;
raw stdout/stderr are not persisted. Combined durable evidence is at most 4 KiB
plus the gateway duration field. All evidence is labelled `UNTRUSTED_DATA`.

## Lifecycle and repair

ToolCall supplies PROPOSED/RUNNING/SUCCEEDED/FAILED/BLOCKED state, scoped linkage,
timestamps, safe definition/parameter fingerprint, snapshot digest, bounded syntax
result, integrity outcome and duration. SUCCEEDED means verification completed;
its syntax result can still be `failed`. No CommandRun table is needed.

At most two verification attempts per AgentRun are durably reserved under an
AgentRun row lock. Replay of the same call key never re-executes. The OS worker
retains its global one-active-run limit. No hidden retry is attempted.

The explicit trusted continuation states are:
- read evidence → propose one governed mutation or one verification, or finish;
- approved mutation evidence → propose one verification, or finish;
- first completed syntax failure → propose one governed correction, or finish;
- passing/second verification → terminal result only.

Each provider continuation is a separate accounted ModelRun, at most six total.
Every mutation/correction retains I-041 Policy and exact human approval. An atomic
per-mutation continuation claim prevents an old approval replay from consuming a
later correction wait. A crash after claiming fails closed; no automatic provider
retry or reapplication occurs. Syntax output never grants another permission.

The trusted workflow links each Manager, Developer, QA and generic AgentRun before
provider/tool work. An initially linked CREATED or RUNNING AgentRun with no
ToolCalls is also terminalized after the same one-hour lease on a later explicit
`advance`. A never-started CREATED run becomes CANCELLED with no fabricated start
timestamp; a RUNNING run becomes FAILED. The step and workflow become FAILED.
The AgentRun and step are locked and rechecked, and ToolCalls are reread after
locking so a concurrently committed proposal prevents this pre-tool recovery.
Active ModelRuns, AgentRun, step and workflow fail in one transaction. Neither
provider calls nor tools are replayed. A completed AgentRun is not reclaimed by
the pre-tool path, including a result waiting for human challenge resolution.
Tool reservation, approval linkage and their Policy/audit records commit in one
transaction. An interrupted pending proposal, running/finished first tool, applied
mutation, denial or claimed continuation is failed closed on a later explicit
`advance` after the fixed one-hour lease. Active continuations are not reclaimed
before that lease; each governed provider continuation has a 300-second deadline.
An aged RUNNING AGENT_TASK step with no linked AgentRun is separately failed with
`initial_step_interrupted`, under the step row lock and a scoped workflow CAS.
Delayed linkage to a terminal step or workflow is rejected. If the process died
after creating an AgentRun but before linking it, the orphan is left untouched:
no association is guessed from a shared task or timestamp. It has no ModelRun or
tool authority. Neither recovery path automatically retries an assignment or
provides a durable task scheduler. Cancellation of an already dispatched provider
remains a separate concern.

Approved replacement preserves existing ordinary mode/group so the separate
verification UID can still read admitted source. Foreign ownership, privileged
bits and extended attributes fail closed. Reads and replacement use pinned
directory descriptors, reject symlinks and recheck the approved parent. This does
not claim filesystem compare-and-swap against a hostile concurrent same-UID writer.

QA receives bounded server-derived ToolCall references and passed/failed/stale
classification, not authority or raw process logs. Operator Console renders readonly
result, exit code, counts, bounded diagnostic paths, truncation, duration, integrity,
and source identity alongside existing AgentRun/workflow and Policy information.

## Identity and validation

I-044B, AppArmor, seccomp and namespace helpers are unchanged. I-044A's actual
trusted checker, fixed binding and probe changes require new generated input/bundle
pins. Run `infra/verification/i044b-v2/tools/refresh_reviewed_inputs.py`; never edit
hashes manually. A input identity remains distinct from the compiler-dependent
installed manifest. This is INPUT_REPRODUCIBLE_ONLY, not byte-reproducible CPython.

Migration `20261011_0032` adds immutable Developer v4 and permits only
TOOL_CONTINUATION ordinals through six. Downgrade retains/archives v4 and refuses
when historical ordinals cannot fit the old schema; it never rewrites usage history.

Unit tests cover closed parameters/injection, bounded evidence, integrity and
infrastructure failure classification. Database tests cover exact authority,
Policy, concurrent reservations, replay, migrations, the approved two-verification
cycle and old-approval replay. Existing I-040..I-043 tests stay enabled.
The installed CI acceptance runs that same harmless provider-free workflow as the
peer-authenticated non-root API client, with disposable `novalton_test`, actual
I-044A IPC and no mocked adapter. Existing kernel, AppArmor negative/positive,
cleanup, I-044A/B contracts and full API suites remain required.
