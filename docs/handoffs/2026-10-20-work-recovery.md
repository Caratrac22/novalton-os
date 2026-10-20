# Novalton OS — checkpoint (2026-10-20)

## Base and recovery

- Source: SHA-256-verified ZIP and Git bundle at `087c6e91f9c101de36f2c1b3fe84e924014a94b5`.
- 379 tracked files match ZIP byte-for-byte (Git paths decoded with `-z`); bundle also contains `origin/main` at `150a3ec1ef4dbd5b2f4c0ab132baa21430837978`.
- GitHub connector: PR #88 OPEN, `feature/i044-controlled-verification` ahead 9 / behind 0 against the recorded main, 40 changed files. No upstream push or merge from this session.
- Working branch: `fix/i044-pretoolcall-recovery`.

## Environment

- Python 3.13.5 (supported family, not reference 3.13.15); Node 22.16.0 (not reference 24.19.0).
- Docker and PostgreSQL CLIs not available. No migrations or DB-backed tests run.
- Ruff not installed; offline dependency lookup failed. Static Python compile and `git diff --check` used instead.
- Tests run locally with `PYTHONPATH=apps/api/src pytest -q --noconftest ...` to avoid pretending the `novalton_test` DB fixture has passed; this is *not* DB integration acceptance.

## Change

- `reconcile_stale_continuation` now terminates a stale, initially linked, `RUNNING` AgentRun with zero ToolCalls after the fixed one-hour lease.
- AgentRun is row-locked and all ToolCalls are reread after locking, preventing terminalization if a proposal landed concurrently.
- No provider retry, ToolCall creation, mutation replay, approval bypass, or new command execution granted.
- AgentRun, RUNNING ModelRuns, step, and workflow are failed atomically using existing CAS transitions. Other continuation paths are preserved.

## Proof and limitations

- Isolated mocked reconciliation tests: six passing cases covering stale, young, late ToolCall, already completed AgentRun, concurrent AgentRun status change, concurrent step change.
- Additional API unit-only checks: `test_output_budget.py`, `test_agent_contracts.py`; total 33 passed, 0 failed via DB-free invocation.
- Local full database acceptance and installed sandbox acceptance **not run** (infrastructure unavailable).
- Follow-up gate required: full CI on new commit using disposable migrated `novalton_test`, concurrency DB test, independent security review, installed I-044A gate if behavior is security-sensitive.

## Prioritized work

- [ ] **P0 VERIFYING:** Run post-commit GitHub CI and validate live PostgreSQL row-lock/CAS semantics; do not merge #88 based on mocked tests.
- [ ] **P1 TODO:** Add persisted database-level interruption test at the initial AgentRun pre-ToolCall boundary, plus competing producer/cleanup scenario.
- [ ] **P2 TODO:** Review issues #40/#41 against current provider contract; run a real, explicitly authorized provider test when credentials and clean environment exist.
- [ ] **P3 TODO:** Design durable autonomous task queue atop existing Policy/orchestrator; no parallel engine.
- [ ] **P4 BLOCKED:** Locally reproduce installed AppArmor/seccomp acceptance without Docker/privileged runner (use GitHub Actions).
