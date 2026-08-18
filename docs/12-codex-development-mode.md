# Novalton OS — Codex Development Mode

> Version: 0.1 — 19 August 2026
>
> Status: Temporary implementation workflow

## 1. Purpose

This document defines the temporary development workflow for Novalton OS while Codex access is available.

It **supersedes only the tool-specific implementation guidance** in sections 39–41 of `docs/11-implementation-plan.md` where OpenCode/Cursor/Hermes are named as the primary coding agent.

All architecture, ticket scope, sequencing, constraints, and definitions of done in `docs/00-foundations.md` through `docs/11-implementation-plan.md` remain authoritative.

---

## 2. Temporary primary development worker

During the current Codex access period:

```text
Primary coding worker: Codex
Fallback coding worker: DeepSeek V4 Flash Free / OpenCode when needed
Architecture lead: ChatGPT conversation + repository specifications
Source of truth: repository docs + accepted GitHub changes
```

Codex is used because the project benefits from repository-aware, multi-file implementation, command execution, testing, and iterative fixes against the actual codebase.

This is a development-tool choice, **not** a product architecture dependency. Novalton OS itself must remain independent from Codex or any OpenAI-specific coding environment.

---

## 3. Responsibility split

### User

The user retains final authority over product direction and important changes.

### Architecture / project lead

The architecture lead is responsible for:

- preserving consistency with foundational documents;
- choosing implementation order;
- defining ticket scope;
- reviewing Codex results;
- identifying architectural drift;
- deciding when specifications need amendment;
- coordinating fixes and next tickets.

### Codex

Codex acts as the implementation worker.

For each ticket it should:

```text
read relevant docs
inspect repository state
produce a short plan
implement only ticket scope
run relevant commands/tests
fix failures caused by its changes
report changed files
report commands and test results
report assumptions and unresolved risks
```

Codex must not silently redesign foundational architecture.

---

## 4. Branch and change discipline

Implementation work should preferably happen on a dedicated branch per ticket or small ticket group.

Suggested naming:

```text
codex/i-001-repository-scaffold
codex/i-002-dev-infra
codex/i-003-backend-core
```

Changes should remain reviewable.

A ticket should not combine unrelated architecture refactors merely because the coding model noticed an opportunity.

---

## 5. Codex working rules

Codex should always treat the repository docs as constraints rather than suggestions.

Priority when conflicts occur:

```text
accepted user decision
↓
foundational docs
↓
implementation plan / ticket
↓
existing code conventions
↓
Codex implementation preference
```

If existing code conflicts with a foundational document, Codex should surface the conflict rather than silently choose one side.

---

## 6. Verification requirement

Generated code is not considered complete until the relevant verification has been attempted.

For each ticket, Codex should run the applicable subset of:

```text
backend lint
backend tests
frontend lint
frontend typecheck
frontend tests
migration checks
Docker/Compose validation
application boot checks
```

Failures caused by the ticket should be fixed before completion whenever practical.

Pre-existing failures must be reported separately.

---

## 7. No architecture-by-vibe

Codex must not introduce major dependencies simply because they are popular or convenient.

Examples requiring explicit architectural justification before adoption:

- agent orchestration frameworks;
- alternative databases;
- message brokers beyond current needs;
- authentication frameworks before the planned phase;
- large UI frameworks outside the accepted stack;
- cloud services that create avoidable vendor coupling;
- arbitrary code-execution infrastructure.

The modular-monolith direction remains the default.

---

## 8. Codex and secrets

Codex must never commit real secrets.

Provider keys and credentials belong in ignored local configuration or a future secret manager.

`.env.example` contains placeholders only.

If a task requires a credential that is unavailable, implementation should expose the configuration boundary and use mocks/fakes where appropriate rather than invent a secret.

---

## 9. Codex and model/provider choices

The coding worker used to build Novalton OS is distinct from the models that Novalton OS will route at runtime.

Using Codex for development does **not** change the Model Router policy in `docs/05-model-router.md`.

Runtime model choices remain governed by:

- Model Catalog Service;
- user-approved provider policy;
- cost rules;
- capability requirements;
- approval requirements.

---

## 10. Temporary fallback strategy

If Codex quota/access becomes unavailable or unsuitable for a ticket:

```text
1. preserve current branch and test state;
2. record the unfinished ticket state;
3. continue with OpenCode + DeepSeek V4 Flash Free or another explicitly approved coding setup;
4. do not alter product architecture merely because the development worker changed.
```

The repository specifications are designed to make this handoff possible.

---

## 11. Ticket I-001 execution instruction

The first implementation ticket remains **I-001 — Repository scaffold** from `docs/11-implementation-plan.md`.

Codex should receive this instruction:

```text
Implement GitHub ticket I-001 for the Novalton OS repository.

Before modifying anything:
1. read docs/00-foundations.md through docs/12-codex-development-mode.md;
2. inspect the actual repository state;
3. provide a short implementation plan based on what currently exists.

Then implement ONLY I-001 — Repository scaffold as defined in docs/11-implementation-plan.md.

Required foundation:
- monorepo structure with apps/web, apps/api, apps/node, packages/contracts, packages/ui, packages/sdk, infra, scripts;
- FastAPI backend with GET /api/v1/health;
- Python project config, Ruff, pytest, structured logging and health test;
- Next.js + TypeScript + Tailwind minimal frontend;
- Docker Compose for PostgreSQL, Redis and Qdrant with healthchecks and persistent development volumes;
- .env.example with placeholders only;
- basic GitHub Actions CI for backend and frontend;
- developer quick-start README;
- apps/node remains a placeholder only.

Do not implement agents, authentication, Memory Engine, Model Router, Policy Engine, orchestration frameworks, Novalton Node runtime, voice, Three.js, or premium UI yet.

Keep dependencies minimal and respect the modular-monolith direction.

Run all relevant lint/tests/typechecks and fix failures caused by your changes.

Finish with:
- files changed;
- commands executed;
- test/lint/typecheck results;
- assumptions;
- remaining manual steps;
- any conflict found with repository specifications.
```

---

## 12. Review loop

After Codex completes a ticket:

```text
Codex implementation
      ↓
Git diff / PR
      ↓
architecture + correctness review
      ↓
CI / tests
      ↓
accept or request changes
      ↓
next ticket
```

A successful Codex response is not itself proof that the implementation is correct.

Repository state and tests are authoritative.

---

## 13. End of temporary Codex mode

This document is intentionally temporary.

When Codex is no longer the primary coding worker, the implementation process may switch tools without changing the Novalton OS architecture.

The development-worker abstraction is effectively:

```text
Ticket + Repository + Specs
            ↓
    Coding Worker
            ↓
      Verified Change
```

The worker may change. The contract should not.
