# Novalton OS — Mission 3 handoff for Mission 4

Date: 2026-10-20. This report describes the reviewed code checkpoint
`9d309c1d8d0fc5a567cd178fac5999e7136713a5` and its completed validation.
The final export's `HEAD.txt` identifies the later documentation commit, if any.

## Continuity and Git

- Repository: `Caratrac22/novalton-os`; Mission 3 PR
  [#92](https://github.com/Caratrac22/novalton-os/pull/92), branch
  `feature/mission3-durable-dispatch`.
- Stacked on Mission 2 PR #91, whose validated base was
  `978612f62302a08c16cc4447d2f710d8dae896a3` on
  `fix/mission2-workflow-recovery`. Neither PR was merged into `main` in this
  mission. No force push was used.
- Cancellation checkpoint: `3d5f3e318d6e11673b49a7cbe01242fd38511d4c`.
  Initial dispatch foundation: `617409c83aa0a197ac6cf5b674b1db7b5bca10eb`.
  Exact step evidence and migration: `745a927b042f3c5138554312fa0c64b90553eecd`.
  Lease-clock race fix: `94898da74ee40f05f08fba7be4d719e3824040a8`.
  Unlinked-agent authority fix and validated code head:
  `9d309c1d8d0fc5a567cd178fac5999e7136713a5`.
- The GitHub branch was checked out at that exact code head with a clean working
  tree before writing this report. The prior session's local execution runtime
  had temporarily been unavailable; code validation was performed on GitHub
  Actions, not claimed from that local runtime.

## Delivered behavior

The scoped `POST /workflow-runs/{id}/cancel` commits a monotonic workflow
cancellation fence, then settles unfinished steps in a separate restart-safe
transaction. Repeated/concurrent requests remain idempotent. Reservations for
linked agent starts, models, tools, approved mutations and continuations check
the same persisted fence; late provider responses cannot hand off to a new step
or revive an old approval. Already engaged provider and tool operations retain
their actual usage and outcome evidence. See
[cancellation contract](17-workflow-cancellation.md).

The controlled dispatcher reuses `orchestrator.service.advance` for **one
explicit iteration per claim**. Migration `20261020_0033` creates workspace
activation, task dispatch, dependencies and attempt evidence; `20261020_0034`
adds the composite foreign key binding attempt step evidence to its exact
workflow. Requests bind an existing fresh WorkflowRun to an immutable scoped
task/request key. Claiming uses PostgreSQL `FOR UPDATE SKIP LOCKED`, priority,
eligibility, dependencies and atomic owner/generation/lease/attempt state.
Activation requires both the default-off server flag and an explicit audited
workspace operator change. No task-status edit or model-produced input enables
execution.

Claim authority is rechecked at workflow, model, tool, handoff and continuation
boundaries. Attempt and model-call counts, deadlines and unknown-pricing policy
bound new reservations. Expired or uncertain claims become BLOCKED without
replay; a revoked late owner cannot renew, finalize or reserve new effects.
The row-lock heartbeat test verifies database time **after** waiting for a
concurrent lock. A claim cannot borrow authority for an unlinked AgentRun.
Actual workflow/approval state governs DONE, CANCELLED and WAITING_HUMAN;
another independent task proceeds while one awaits exact human approval.
See [operator contract and limitations](19-durable-task-dispatch.md) and the
[original design](16-durable-task-dispatch-design.md).

No background worker, automatic retry, production workspace activation,
HTTP scheduling route or model-callable scheduling tool was introduced. I-044A/B
sandbox and approval contracts were not rebuilt or expanded.

## Validation evidence

| Gate | Result on code head `9d309c1` | Evidence |
| --- | --- | --- |
| API on disposable PostgreSQL `novalton_test` | **816 passed** across 49 test files; 37 durable-dispatch cases and 13 cancellation cases | [CI run 39471757859](https://github.com/Caratrac22/novalton-os/actions/runs/39471757859), backend job 118797320273 |
| Backend Ruff format and lint; migrations; `pip-audit` | Passed | Same CI backend job |
| Frontend lint tests, lint, typecheck, build; `npm audit --audit-level=high` | Passed | Same CI run, frontend job 118797319701 |
| I-044A source/staging, disposable schema round-trip and full API | Passed | [I-044 run 39471757686](https://github.com/Caratrac22/novalton-os/actions/runs/39471757686), job 118798042356 |
| I-044B reproducible foundation | Passed | Same I-044 run, job 118798042601 |
| Installed I-044A kernel/seccomp, AppArmor positive/negative, governed verify-correct-verify | Passed | Same I-044 run, job 118798991928 |
| Recovery export | Bundle verified and cloned to compare exact HEAD/tree; source ZIP and SHA-256 sums uploaded | Same CI run, job 118799600634, [artifact 12287078900](https://github.com/Caratrac22/novalton-os/actions/runs/39471757859/artifacts/12287078900) |

The PostgreSQL logs include expected duplicate-key and foreign-key errors from
negative tests; the test steps and jobs themselves concluded successfully. An
earlier dispatcher checkpoint had 811 passing and two failing tests: the exact
metadata table inventory needed the four new tables, and a terminal workflow
start needed its historic error code under the new fence. Both were corrected
before the 816-pass checkpoint. No failed tests remain at the validated head.
The focused cancellation checkpoint separately passed 778 API tests plus
frontend, audit and installed I-044 gates in
[CI 39464653289](https://github.com/Caratrac22/novalton-os/actions/runs/39464653289)
and [I-044 39464653302](https://github.com/Caratrac22/novalton-os/actions/runs/39464653302).

## Recovery package and procedure

The PR CI `Verified Git recovery export` job runs only after backend and
frontend succeed. Its artifact contains:

- `Novalton_OS_Mission_3.bundle`: full Git history under `mission3-export`;
- `Novalton_OS_Mission_3_Sources.zip`: tracked sources at the exact HEAD;
- `HEAD.txt`, `COMMITS.txt`, `MISSION_4_REPRISE.md` and `SHA256SUMS`.

Download the latest successful artifact for PR #92, not an earlier checkpoint;
the Action's retention is 90 days. Verify all files with `sha256sum -c
SHA256SUMS` after extracting the artifact. Restore with:

```bash
git bundle verify Novalton_OS_Mission_3.bundle
git clone --branch mission3-export Novalton_OS_Mission_3.bundle novalton-os
cd novalton-os
test "$(git rev-parse HEAD)" = "$(cat ../HEAD.txt)"
git remote add origin https://github.com/Caratrac22/novalton-os.git
git switch -c feature/mission4-next
```

Check GitHub PR #91 and #92 heads before rebasing or opening a Mission 4 PR.
Do not infer a clean remote branch from an old package or overwrite it. Protect
the disposable database profile and only migrate `novalton_test` during tests.

## Remaining boundaries and next work

No OpenRouter key or live provider call was available for Mission 3 acceptance;
the Manager → Developer → QA path is proved with deterministic providers and
PostgreSQL integration tests, not a real remote model. Issues #40/#41 and
existing transport/structured-output work still require an explicitly
configured live-provider acceptance on a fresh workflow, with secrets excluded
from reports and logs.

The dispatcher is an internal trusted operator API. Before routine deployment,
integrate explicit operator authentication/authorization and controlled
activation, load/fairness/capacity tests, provider reconciliation or idempotency
where available, and any reviewed monetary reservation policy. Unknown cost is
not treated as zero; an already sent request may have incurred cost despite a
crash. The one-hour default lease requires an explicit heartbeat strategy if
long-running operations will be supported. A permanent background service/UI
comes only after recovery and isolation acceptance. Keep human approvals,
I-041 fingerprints, I-042 commit proofs and I-043 publication reconciliation as
the sole authority for their respective effects. Never replay BLOCKED uncertain
attempts merely because a lease expired.
