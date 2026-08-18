# Novalton OS — Foundations

> Version: 0.1 — 18 August 2026
>
> Status: Foundational draft

## 1. Vision

Novalton OS is an AI-native operating system for entrepreneurs and businesses.

Its purpose is to let a human pilot a coordinated team of specialized AI agents from a single interface. Agents can research, reason, prepare work, manage projects, write and test code, analyze documents, perform legal research, assist with outreach, and interact with connected tools.

Novalton OS is not designed as a simple chatbot. It is designed as an operational layer between a user, AI models, business data, projects, memory, and external tools.

The long-term goal is to make the system usable first as a personal workspace, while keeping the architecture compatible with a future multi-tenant SaaS product.

## 2. Core challenge

The goal is not to build a product with the largest possible number of agents or features.

The core challenge is:

> Build an AI team that inspires more trust than a conventional chatbot.

Every important feature should therefore improve at least one of the following:

- usefulness;
- reliability;
- transparency;
- controllability;
- traceability;
- interoperability;
- long-term extensibility.

## 3. Fundamental architecture model

Novalton OS separates intelligence, coordination, authorization, memory, specialized capabilities, and actions.

```text
User
  |
  v
Interface
  |
  v
Orchestrator
  |
  +----> Specialized Agents
  |
  +----> Memory Engine
  |
  +----> Model Router
  |
  +----> Policy Engine
             |
             v
           Tools
```

The responsibilities are intentionally separated:

- **LLMs** provide interpretation, reasoning, generation, classification, and planning.
- **The Orchestrator** decides which agent or capability should work next.
- **The Policy Engine** determines whether an action is allowed, blocked, or requires human confirmation.
- **The Memory Engine** stores, indexes, retrieves, versions, and contextualizes knowledge.
- **Agents** provide specialized capabilities.
- **Tools** perform real actions against files, services, APIs, repositories, email, calendars, browsers, or other systems.

No single AI model should own the entire system.

---

# 4. The 11 founding principles

## Principle 1 — The human remains the final authority

Novalton OS may analyze, plan, recommend, prepare, coordinate, and execute tasks within allowed boundaries.

However, the user remains the ultimate authority over the system.

For actions that require approval, Novalton OS must clearly explain what it intends to do before execution.

Approval must be scoped to the described action or approved plan. A previous approval must never be interpreted as unlimited permission for unrelated future actions.

## Principle 2 — Actions must be understandable

Before an action requiring confirmation, Novalton OS should provide an operational summary containing, when relevant:

- what will happen;
- why the action is proposed;
- which agent requested it;
- which tool will be used;
- which data will be involved;
- external or irreversible effects;
- expected cost when applicable.

Novalton OS does not need to expose private model reasoning. It must instead expose a concise and useful explanation of the proposed operation.

## Principle 3 — Memory must distinguish knowledge from assumption

The Memory Engine must not silently transform an inference into a fact.

Stored knowledge should support explicit confidence and provenance states such as:

- confirmed fact;
- observed fact;
- inference;
- hypothesis;
- disputed information;
- obsolete information.

Important memories should retain enough provenance to answer:

> Where did this information come from?

When information changes, previous versions should remain available in history rather than being silently destroyed.

## Principle 4 — Agents are specialized, models are replaceable

An agent is not a model.

For example, the Developer Agent must not be permanently equivalent to a particular provider or model.

The system should reason in terms of capabilities:

```text
Task
  -> Required capabilities
  -> Eligible agent
  -> Eligible model(s)
  -> Selected model
```

This allows Novalton OS to switch between OpenRouter models, Gemini, future providers, or local models without redesigning the agent architecture.

## Principle 5 — Agents collaborate through structured results

Agents should not maintain uncontrolled free-form conversations with one another.

A typical flow is:

```text
Agent
  -> Structured result
  -> Orchestrator evaluation
  -> Next agent or action
```

An agent result may include:

- conclusions;
- artifacts;
- sources;
- risks;
- confidence;
- unresolved questions;
- recommended next steps.

The orchestrator then determines which capability should continue the workflow.

## Principle 6 — Least privilege for every agent

Every agent has explicit permissions.

Agents should receive only the capabilities required for their mission.

Examples of permissions include:

- reading email;
- sending email;
- reading files;
- writing files;
- running commands;
- accessing Git repositories;
- using web research;
- creating or deleting data;
- spending API credits;
- interacting with business systems.

A Legal Agent should not automatically receive repository write access. A Developer Agent should not automatically receive permission to send customer emails.

## Principle 7 — Cost and resource usage are visible

Novalton OS should make AI consumption observable.

Where the provider exposes the necessary information, tasks may report:

- model used;
- input/output token usage;
- estimated monetary cost;
- execution time;
- local compute usage where relevant.

The Model Router should eventually be able to choose between different models according to quality, latency, availability, privacy, and cost constraints.

## Principle 8 — Important information should be verifiable

For high-impact domains such as legal, financial, security, contractual, or technical decisions, Novalton OS should preserve reliable source references whenever possible.

The system must be able to represent uncertainty and disagreement.

It is valid for an agent to report:

- insufficient information;
- conflicting sources;
- uncertain conclusion;
- requirement for human review.

Producing a confident-looking answer is never more important than producing a reliable answer.

## Principle 9 — Provider failure must not break the architecture

Novalton OS should not depend structurally on a single AI provider.

The Model Router should eventually support multiple routes, for example:

```text
Novalton OS
   |
   +---- Gemini
   +---- OpenRouter
   +---- Local models
   +---- Future providers
```

A provider may be unavailable, expensive, deprecated, rate-limited, or unsuitable for a specific task. The architecture must allow substitution.

## Principle 10 — SaaS compatibility from the beginning

The first version may run for a single user, but core data models should avoid assumptions that make multi-tenant operation impossible later.

Important resources should therefore be capable of belonging to a workspace/tenant context, including:

- users;
- projects;
- agents;
- memories;
- documents;
- tasks;
- credentials;
- policies;
- audit logs.

This does not mean building billing, enterprise administration, or complex multi-tenancy in the first release. It means avoiding architectural dead ends.

## Principle 11 — Control policies belong to the user, not the model

The LLM may assess risk and recommend whether confirmation is appropriate, but it cannot override user-defined restrictions.

Example:

> Never send an email without asking me first.

Even if an AI model judges a particular email harmless, the user policy still requires confirmation.

Likewise, the user may explicitly allow low-risk operations such as creating project folders inside an approved workspace without repeated confirmation.

The Policy Engine, not the language model, is the final technical authority for permissions.

---

# 5. Dynamic confirmation model

Novalton OS does not require a confirmation dialog for every microscopic operation.

Instead, confirmation is determined through a combination of:

1. user-defined policies;
2. agent permissions;
3. tool permissions;
4. action type;
5. reversibility;
6. external impact;
7. data sensitivity;
8. monetary cost;
9. contextual risk;
10. model-provided risk assessment as an advisory signal only.

A simplified risk model may contain levels such as:

```text
LOW
  -> may execute automatically if policy allows

MEDIUM
  -> confirmation may be required depending on context and policy

HIGH
  -> explicit confirmation required

BLOCKED
  -> cannot execute
```

Examples:

| Action | Typical baseline |
|---|---|
| Read a user-provided document | LOW |
| Create a temporary internal file | LOW |
| Modify project source code | MEDIUM |
| Send an external email | HIGH |
| Delete large amounts of user data | HIGH |
| Initiate a payment | HIGH |

These are defaults, not immutable rules. User policy can always make a permission stricter.

# 6. Approved workflow execution

The user may approve a complete workflow rather than confirming every internal agent transition.

Example:

```text
1. Legal Agent analyses the request
2. Project Agent creates a backlog proposal
3. Developer Agent proposes the technical architecture
4. Tester Agent reviews the proposal
5. Orchestrator produces the final synthesis
```

Once this plan is approved, the orchestrator may transition between the approved internal stages automatically.

A new confirmation is required when:

- the workflow attempts an action outside the approved scope;
- an action is classified as requiring mandatory confirmation;
- a user policy explicitly requires approval;
- the orchestrator materially changes the approved plan;
- the expected external impact changes.

This makes long multi-agent workflows usable without weakening human control.

# 7. Memory philosophy

The goal of Novalton OS memory is not to claim perfect or literally infinite memory.

The goal is to preserve source information while making relevant knowledge efficiently retrievable over long periods.

The system should distinguish several layers.

## 7.1 Source memory

Original information should be preserved whenever appropriate:

- conversations;
- uploaded documents;
- agent reports;
- actions;
- project events;
- decisions;
- external source references.

## 7.2 Structured memory

Useful facts, entities, relationships, decisions, preferences, constraints, and project state may be extracted into structured records.

## 7.3 Derived memory

Summaries, embeddings, indexes, inferred relationships, and compressed context may be generated from source data.

Derived memory must remain traceable to its source whenever possible.

## 7.4 Temporal memory

Memories should support time and versioning.

For example:

```text
Old value
  -> retained in history

New value
  -> current active value
```

The system should not erase contradictory history merely to maintain a convenient current answer.

## 7.5 Retrieval

A future Memory Engine may combine:

- relational queries;
- full-text search;
- semantic/vector search;
- recency;
- project scope;
- entity relationships;
- confidence;
- source quality.

The model should receive the smallest useful context rather than the entire history.

# 8. Orchestration philosophy

The orchestrator is responsible for deciding what capability should work next.

It may:

- decompose a user request;
- propose a plan;
- select agents;
- select models through the Model Router;
- inspect structured results;
- choose the next step;
- detect missing information;
- stop a workflow;
- request human input;
- request approval through the Policy Engine.

The orchestrator does not automatically inherit the permissions of every agent and tool.

# 9. Policy Engine philosophy

The Policy Engine should be deterministic wherever possible.

It evaluates a proposed action against explicit policy rather than trusting an LLM to decide whether it is allowed.

Conceptually:

```text
Proposed action
      |
      v
Policy Engine
      |
      +---- User policies
      +---- Workspace policies
      +---- Agent permissions
      +---- Tool permissions
      +---- Risk classification
      |
      v
ALLOW / REQUIRE_CONFIRMATION / BLOCK
```

Language models may provide contextual information to help classify actions, but they cannot bypass hard policy constraints.

# 10. Product design challenge

Every significant Novalton OS feature should be challenged with five questions before implementation:

1. **Does this make Novalton OS meaningfully more useful?**
2. **Can the user understand what will happen?**
3. **Does the system distinguish certainty from uncertainty?**
4. **Can this feature remain model/provider independent?**
5. **Does this decision create an unnecessary obstacle to a future SaaS architecture?**

If the answer exposes a serious weakness, the design should be reconsidered before implementation.

# 11. Reliability principle

Novalton OS should optimize for producing a correct and useful result, not merely for producing an answer.

The system should therefore be comfortable stopping and reporting:

- missing context;
- uncertain information;
- contradictory evidence;
- unavailable tools;
- insufficient permissions;
- excessive risk;
- requirement for human review.

A refusal to guess can be a successful system outcome.

# 12. Initial product scope

The first implementation is intended primarily for one user running Novalton OS on personal hardware, while allowing cloud AI APIs.

The target environment currently includes:

- a Lenovo IdeaPad Gaming 3 development workstation;
- a separate Proxmox server for services;
- OpenCode for AI-assisted development;
- OpenRouter for access to interchangeable models;
- Gemini API for web-connected research;
- optional local models for lightweight workloads, including future voice components.

The initial AI budget target is intentionally small. Efficient model routing and use of free/local models are therefore product requirements rather than afterthoughts.

# 13. Initial agent families

The architecture should support at least the following first agent roles:

- Orchestrator;
- Project Manager;
- Developer;
- Tester / QA;
- Legal Research Assistant;
- Outreach / Commercial Assistant;
- Personal Assistant.

Future roles should be addable without modifying the core orchestration engine.

# 14. Voice direction

Voice is a first-class future interface, not a separate product.

The architecture should eventually support:

```text
Microphone
   -> Local speech recognition when possible
   -> Novalton OS
   -> Agent workflow
   -> Response
   -> Text-to-speech
```

Local speech recognition is preferred where practical to reduce latency, preserve privacy, and lower API cost.

The voice layer must use the same Policy Engine as the graphical interface. A spoken instruction must never bypass confirmation requirements.

# 15. Non-goals for the first implementation

The first version does **not** need to provide:

- dozens of agents;
- autonomous financial transactions;
- fully autonomous external communication;
- perfect memory;
- enterprise billing;
- complete ERP functionality;
- complex organization administration;
- support for every AI provider;
- a production-scale SaaS infrastructure.

The first objective is to prove that the core loop works reliably:

```text
User request
  -> plan
  -> approval when required
  -> specialized agent work
  -> structured results
  -> orchestration
  -> safe tool execution
  -> durable memory
  -> visible final result
```

# 16. Next design documents

This document intentionally defines principles rather than implementation details.

The next specifications should be created separately:

1. `01-agent-model.md` — exact definition and lifecycle of an agent;
2. `02-task-workflow-model.md` — tasks, plans, dependencies, states, and execution;
3. `03-policy-engine.md` — permissions, risk, approval scopes, and enforcement;
4. `04-memory-engine.md` — storage, provenance, versioning, retrieval, and RAG;
5. `05-model-router.md` — provider abstraction, routing, fallbacks, and budgets;
6. `06-system-architecture.md` — services, APIs, databases, queues, and deployment;
7. `07-interface.md` — chat, project views, live agent activity, and approval UX;
8. `08-voice.md` — STT, wake word, TTS, local execution, and permissions;
9. `09-saas-foundations.md` — tenant isolation and future SaaS constraints;
10. `10-roadmap.md` — milestones from prototype to usable V1.

---

## Foundational rule

> Novalton OS must never confuse autonomy with absence of control.

Its purpose is to reduce the amount of work the human must perform while preserving the human's authority, visibility, and ability to intervene.
