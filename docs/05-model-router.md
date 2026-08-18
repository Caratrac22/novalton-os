# Novalton OS — Model Router

> Version: 0.1 — 19 August 2026
>
> Status: Foundational draft

## 1. Purpose

The Model Router selects the most appropriate model for each Agent Run and Orchestrator decision while balancing:

1. sufficient quality;
2. cost;
3. speed;
4. provider preference.

The router must never choose a model merely because it is cheap if it is unlikely to complete the task reliably.

The default principle is:

> **Use the least expensive currently available model that is sufficiently capable for the task.**

Model selection is dynamic. Agent identity is never tied permanently to one provider or one model.

---

# 2. Core components

```text
Task / Agent Run
      |
      v
Capability Requirements
      |
      v
Model Catalog Service
      |
      v
Model Router
      |
      +--> availability
      +--> capabilities
      +--> context fit
      +--> privacy
      +--> cost
      +--> historical performance
      +--> provider health
      +--> user policy
      |
      v
Selected Model
```

The Model Router works with:

- Orchestrator;
- Policy Engine;
- Memory Engine;
- Runtime Watchdog;
- Model Catalog Service;
- Provider adapters;
- historical evaluation data.

---

# 3. Live Model Catalog Service

Novalton OS must not rely on an LLM's memory of model names.

A dedicated **Model Catalog Service** maintains the set of models that are actually usable at the current time.

It may gather data from:

- provider APIs;
- OpenRouter model listings;
- configured local inference servers;
- manually configured providers;
- provider health checks.

The catalog stores metadata such as:

```yaml
model_id: provider/model-slug
provider: provider_name
display_name: Model Name
status: available
pricing:
  input_per_million: ...
  output_per_million: ...
context_window: ...
capabilities:
  reasoning: true
  coding: true
  tool_calling: true
  structured_output: true
  vision: false
privacy:
  cloud: true
last_verified_at: ...
```

A model that does not exist in the current catalog cannot be selected.

If an agent recommends a nonexistent or unavailable model, the recommendation is treated as invalid metadata rather than blindly executed.

---

# 4. Catalog freshness

Model availability and pricing change frequently.

The catalog must therefore be refreshed periodically and on important routing failures.

Possible triggers:

```text
scheduled refresh
provider startup
provider authentication change
404 / model-not-found error
pricing metadata expiration
manual refresh
provider health degradation
```

The runtime should preserve the exact catalog snapshot or model metadata used for historical Agent Runs.

---

# 5. Initial free-model allowlist

The initial Novalton OS configuration intentionally keeps the free pool narrow.

Configured free models:

```text
DeepSeek V4 Flash Free
NVIDIA Nemotron 3 Ultra Free
```

The actual provider slugs must come from the live Model Catalog Service rather than being assumed forever.

No other free model is automatically added merely because a provider marks it free.

Adding another free model requires configuration or user approval.

This avoids unstable low-quality free-model roulette.

---

# 6. Paid tiers

Paid models are grouped conceptually by expected cost and capability rather than by permanent brand names.

```text
CHEAP
STRONG
PREMIUM
```

## 6.1 CHEAP

Very low-cost models suitable for routine workloads when the free pool is unavailable or insufficient.

## 6.2 STRONG

Models used for harder coding, reasoning, analysis, or orchestration tasks.

## 6.3 PREMIUM

Frontier/high-cost models reserved for tasks where the expected quality gain justifies the additional cost.

Tier membership is dynamic and comes from current pricing and evaluation data.

---

# 7. Intelligence escalation

Novalton OS distinguishes **technical fallback** from **intelligence escalation**.

## 7.1 Technical fallback

Examples:

```text
API timeout
rate limit
provider outage
invalid provider response
model endpoint unavailable
transient network failure
```

A technical fallback may automatically retry or switch to a sufficiently equivalent approved model within configured limits.

It should not require user approval when:

- the replacement remains within the approved capability/cost scope;
- no additional sensitive data exposure occurs;
- policy allows the fallback.

## 7.2 Intelligence escalation

Examples:

```text
INSUFFICIENT_REASONING
INSUFFICIENT_CONTEXT_HANDLING
REPEATED_BAD_OUTPUT
TASK_COMPLEXITY_UNDERESTIMATED
FAILED_SELF_CORRECTION
```

If the system concludes that the current model is not capable enough, moving to a materially stronger or more expensive model requires **explicit user approval**.

This applies even if the stronger model is not technically classified as PREMIUM.

Conceptually:

```text
Current model insufficient
        |
        v
Router proposes stronger candidate
        |
        v
Estimate expected benefit + extra cost
        |
        v
User approval required
        |
     yes / no
```

---

# 8. Escalation proposal

A user-facing escalation request should contain enough information to make the decision understandable.

Example:

```yaml
reason: INSUFFICIENT_REASONING
current_model: ...
proposed_model: ...
resume_from_checkpoint: true
estimated_extra_cost: ...
expected_benefit: higher architecture reasoning reliability
alternatives:
  - retry current model
  - choose another model
  - stop task
```

The user may:

```text
APPROVE
CHOOSE_ANOTHER_MODEL
RETRY
REDUCE_SCOPE
CANCEL
```

---

# 9. Agent model recommendations

Agents and domain managers do not own the final model decision.

They should preferably express **requirements**, for example:

```yaml
model_requirements:
  coding: strong
  reasoning: medium
  tool_calling: required
  context_tokens: 120000
  latency: normal
  budget_priority: high
```

A domain manager may optionally express a model preference, but that preference is advisory only.

The Model Router evaluates it against the live catalog.

Possible result:

```text
ACCEPT_PREFERENCE
SUBSTITUTE
ASK_ORCHESTRATOR
REQUIRE_USER_APPROVAL
```

No agent can force use of a nonexistent model.

---

# 10. Historical performance learning

Novalton OS should learn which models work well for which kinds of tasks.

Historical metrics may include:

- completion rate;
- retry rate;
- watchdog interventions;
- QA acceptance rate;
- user rejection/correction rate;
- structured-output validity;
- tool-call reliability;
- task duration;
- cost;
- tokens consumed;
- escalation frequency.

Example derived profile:

```text
Model A
frontend_small_tasks: strong
large_architecture: weak
tool_calling: reliable
average_cost: low
```

These statistics inform routing but must not become absolute truth.

Task mix, providers, and model versions change over time.

---

# 11. Model version awareness

Model performance history must distinguish model versions when possible.

A newer revision must not automatically inherit all performance assumptions from an older revision.

Example:

```yaml
model_family: deepseek-v4-flash
model_revision: 2026-07-31
provider_route: ...
```

The system may share prior family-level evidence with reduced confidence.

---

# 12. A/B model comparison

Novalton OS may run two models on the same task when comparison could materially improve reliability.

This is **not automatic by default**.

Before starting an A/B comparison, the system must ask the user for approval because it increases compute/API usage.

Example:

> Run two low-cost models independently and let QA compare their solutions?

Possible uses:

- important architecture choices;
- ambiguous technical decisions;
- legal/source synthesis;
- high-value code generation;
- benchmark/evaluation tasks.

A/B comparison must preserve independent outputs before aggregation to avoid cross-contamination.

---

# 13. Orchestrator model policy

The Orchestrator uses task-aware routing as well.

Suggested policy:

```text
Simple routing / formatting
→ sufficiently capable low-cost model

Multi-agent planning / complex reconciliation
→ stronger model when justified

Critical or highly ambiguous decision
→ propose stronger/premium model
→ explicit user approval before escalation
```

A stronger Orchestrator model does not grant additional permissions.

Policy remains external to the model.

---

# 14. Context-window handling

A huge context window is not an excuse to dump the entire memory database into a prompt.

The preferred order is:

```text
1. structured retrieval
2. relevant source retrieval
3. deduplication
4. context packaging
5. safe summarization/compression
6. select adequate context-window model
```

The Memory Engine should reduce irrelevant context first.

However, compression must preserve coherence.

The system must avoid aggressive compression that removes dependencies, contradictory evidence, important assumptions, or the logical structure needed by the model.

If compression would materially damage task understanding, the Router should prefer a larger-context model instead.

---

# 15. Context coherence guard

Before execution, a context package may be checked for:

- missing referenced entities;
- unresolved pronouns/references;
- missing dependencies;
- contradictory summaries;
- excessive compression;
- detached code snippets;
- missing source chronology;
- token overflow.

Possible result:

```text
CONTEXT_OK
CONTEXT_NEEDS_EXPANSION
CONTEXT_NEEDS_RETRIEVAL
CONTEXT_CONFLICT
CONTEXT_TOO_LARGE
```

This helps prevent a model from "losing the plot" merely because context optimization became too aggressive.

---

# 16. Runtime failure classification

The runtime should classify failures rather than treating every bad result identically.

Initial categories:

```text
API_ERROR
RATE_LIMIT
TIMEOUT
PROVIDER_UNAVAILABLE
MODEL_NOT_FOUND
INVALID_OUTPUT
TOOL_FAILURE
INSUFFICIENT_REASONING
INSUFFICIENT_CONTEXT
CONTEXT_OVERFLOW
REPETITIVE_LOOP
NO_MEANINGFUL_PROGRESS
POLICY_BLOCK
BUDGET_BLOCK
UNKNOWN
```

Failure classification informs retry, fallback, escalation, and watchdog behavior.

---

# 17. Watchdog integration

The Runtime Watchdog observes Agent Runs independently of the model.

Signals may include:

- repeated nearly identical outputs;
- repeated identical tool calls;
- excessive reasoning without progress;
- repeated plan regeneration;
- API error loops;
- token consumption without useful artifacts;
- failure to satisfy output schema;
- repeated contradictions;
- no progress across checkpoints.

The Watchdog may:

```text
WARN
INTERRUPT
RETRY
REQUEST_TECHNICAL_FALLBACK
CLASSIFY_AS_INSUFFICIENT_MODEL
STOP_RUN
```

It cannot silently approve an intelligence escalation that requires user confirmation.

---

# 18. Checkpoint-aware model replacement

When a model is replaced, Novalton OS should resume from the latest safe checkpoint whenever possible.

```text
Worker A
  70% valid work
      |
      v
Model failure
      |
      v
Safe checkpoint
      |
      v
Replacement model
```

The replacement model receives:

- objective;
- validated work already completed;
- remaining tasks;
- relevant source context;
- failure reason;
- prior assumptions;
- constraints.

It should not automatically receive a huge dump of the failed model's private reasoning.

---

# 19. Provider abstraction

Novalton OS should expose a normalized provider interface.

Conceptual API:

```text
list_models()
get_model_metadata()
complete()
stream()
health_check()
estimate_cost()
```

Provider-specific details remain inside adapters.

Possible providers may include:

- OpenRouter;
- direct model-provider APIs;
- future enterprise endpoints;
- local inference services for explicitly permitted use cases.

---

# 20. Local model policy

For the initial product, general text/reasoning workloads should **not prioritize local models**.

Local models are initially reserved primarily for voice-related processing such as:

- speech-to-text;
- wake-word detection;
- audio preprocessing;
- potentially lightweight voice intent preprocessing.

General reasoning, coding, orchestration, and research routing should use the configured cloud/API model pool unless future policy changes.

This keeps the architecture simple and avoids sacrificing quality merely to claim local inference.

---

# 21. Privacy routing

Before a model receives context, the Router must respect Memory Engine sensitivity metadata and Policy Engine rules.

A model that is otherwise ideal may be rejected because the relevant data cannot be sent to its provider.

Conceptually:

```text
Best capability model
        |
        v
Privacy check fails
        |
        v
Choose next permitted model
or ask user
```

Model quality never overrides privacy policy.

---

# 22. Cost estimation

Before a run, the Router should estimate cost when enough metadata is available.

Inputs may include:

- estimated prompt tokens;
- expected output tokens;
- reasoning-token pricing;
- provider pricing;
- expected retries;
- A/B duplication;
- tool-related model calls.

Actual cost is recorded after execution.

Estimates should be labeled estimates rather than exact guarantees.

---

# 23. Budget integration

Routing observes the budget hierarchy defined by the Workflow Model:

```text
RUN
WORKFLOW
DAILY
MONTHLY
```

Before spending more, the Router may search for a cheaper sufficiently capable option.

It must not evade a budget limit by splitting one expensive task into many hidden runs.

---

# 24. Routing decision record

Each Agent Run should preserve why a model was selected.

Example:

```yaml
routing_decision:
  selected_model: ...
  catalog_snapshot: catalog_184
  requirements:
    coding: strong
    context_tokens: 100000
  reason:
    - sufficient capability
    - lowest expected cost among qualifying models
    - provider healthy
  alternatives_considered:
    - ...
  estimated_cost: ...
```

This is operational explainability, not private chain-of-thought.

---

# 25. Provider health

The Router should maintain lightweight provider/model health state.

Possible statuses:

```text
HEALTHY
DEGRADED
RATE_LIMITED
UNAVAILABLE
UNKNOWN
```

Health signals may come from:

- recent API errors;
- latency;
- provider status endpoints;
- model-not-found errors;
- rate limiting;
- repeated malformed responses.

Routing should avoid degraded providers when a comparable approved option exists.

---

# 26. User model controls

The user should eventually be able to configure:

- allowed providers;
- allowed free models;
- allowed paid tiers;
- blocked models;
- preferred providers;
- maximum per-run spend;
- maximum workflow spend;
- daily/monthly budget;
- whether A/B runs are allowed;
- whether specific models may see sensitive data.

These settings are enforced through the Policy Engine.

---

# 27. Model simulation

The simulation philosophy should apply to routing as well.

Examples:

> Which model would Nova choose for this task and why?

> What changes if I disable provider X?

> How much would this workflow cost if all workers used STRONG models?

> Which runs would have selected differently under this new routing policy?

Simulation does not execute paid calls unless explicitly approved.

---

# 28. Initial routing algorithm

A conceptual V1 algorithm:

```text
1. Build task capability requirements.
2. Load currently verified models from Model Catalog.
3. Remove policy-blocked models.
4. Remove unavailable/degraded candidates when appropriate.
5. Remove models that cannot fit required context.
6. Remove models missing required capabilities.
7. Estimate expected quality using capability metadata + history.
8. Keep candidates above sufficient-quality threshold.
9. Rank qualifying candidates primarily by cost, then latency/provider preference.
10. Select the best candidate.
11. Record routing decision.
12. Watch execution for technical/intelligence failure.
```

If no model satisfies the minimum requirements:

```text
NO_SUITABLE_MODEL
→ Orchestrator explains why
→ propose options
→ ask user when escalation or policy change is required
```

---

# 29. Invariants

1. Agents are not permanently tied to models.
2. The Router only chooses models present in the current verified catalog.
3. An LLM's recollection of model names is not authoritative.
4. Free models are allowlisted rather than automatically trusted.
5. Initial free allowlist contains only DeepSeek V4 Flash Free and NVIDIA Nemotron 3 Ultra Free.
6. Technical fallback and intelligence escalation are different operations.
7. Technical equivalent fallback may happen automatically within approved scope.
8. Material intelligence escalation requires explicit user approval.
9. A/B execution requires user approval by default.
10. Historical model performance informs but does not dictate routing.
11. Context should be reduced intelligently before blindly demanding a huge context window.
12. Context compression must preserve coherence.
13. Privacy and policy override model quality.
14. Budget limits cannot be bypassed through hidden run splitting.
15. Runtime Watchdog may stop bad runs but cannot grant escalation permission.
16. Checkpoints should be reused after model replacement when safe.
17. Local models are initially reserved primarily for voice-related processing.
18. Every important routing decision is auditable.
19. Model/provider availability is treated as time-varying state.
20. A nonexistent model can never become an executable route merely because an agent named it.

---

# 30. Open design questions

Later implementation specifications must define:

- exact provider adapters;
- catalog refresh frequency;
- pricing-cache TTL;
- capability scoring format;
- model benchmark ingestion;
- historical-performance weighting;
- sufficient-quality thresholds;
- provider health thresholds;
- exact retry limits;
- exact watchdog thresholds;
- cost-estimation formulas;
- local voice model selection;
- catalog persistence schema;
- policy integration schema;
- model simulation UI.

---

# 31. Next document

The next specification should define the overall **System Architecture**.

`06-system-architecture.md` should connect:

- frontend;
- API/backend;
- Orchestrator;
- Policy Engine;
- Memory Engine;
- Obsidian Bridge;
- Model Router;
- Model Catalog Service;
- Runtime Watchdog;
- Agent Runtime;
- tool/plugin layer;
- event system;
- persistence;
- deployment topology;
- Proxmox/local development;
- future SaaS boundaries.
