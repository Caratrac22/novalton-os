# Novalton OS — Interface

> Version: 0.1 — 19 August 2026
>
> Status: Foundational draft

## 1. Purpose

The Novalton OS interface is the user's operational control surface for projects, agents, workflows, memory, policies, models, tools, and approvals.

It should feel less like a conventional chatbot and more like a **premium enterprise AI command center**: calm, fast, visual, trustworthy, and alive in real time.

The selected product direction is:

> **A modern dark premium “enterprise Jarvis” interface, with a minimal command-center home, real-time operational visibility, restrained 3D, and Nova as the central command console.**

The interface must prioritize clarity over spectacle. 3D and animation are used to reinforce state, hierarchy, and product identity, not to obscure information.

---

# 2. Core experience

The user should be able to understand the state of Novalton OS in a few seconds.

At a glance, the home screen should answer:

- What requires my attention?
- What are my agents doing right now?
- Which projects are moving?
- Which tasks are blocked?
- How much AI budget is being consumed?
- What can Nova do next?

The product should feel continuously active without becoming visually noisy.

---

# 3. Visual direction

The default design direction is **dark, premium, modern, fluid and high-contrast**.

Reference qualities include:

- dense-but-clean financial dashboards;
- restrained motion;
- high-quality typography;
- strong spacing discipline;
- low visual clutter;
- subtle depth;
- fast transitions;
- modern charting and status indicators;
- clean card surfaces;
- deliberate use of glow, glass, gradients, blur and 3D.

The desired feeling is closer to a premium financial/operating system interface than a generic SaaS admin panel.

The design must avoid:

- excessive neon;
- unreadable glassmorphism;
- animated backgrounds that compete with content;
- overuse of floating cards;
- fake “sci-fi HUD” decoration;
- decorative 3D that consumes GPU without improving understanding.

---

# 4. 3D and Three.js

Three.js may be used as a first-class visual layer.

Potential uses:

- ambient command-center visualization;
- subtle agent/network topology;
- project/workflow activity visualization;
- background depth effects;
- interactive system map;
- transitions between major operational states;
- visual identity for Nova.

3D must remain **progressively enhanced**.

If WebGL is unavailable or performance is poor, the UI must remain fully functional.

The application should implement performance controls such as:

```text
HIGH VISUAL QUALITY
BALANCED
REDUCED MOTION / LOW GPU
```

Three.js scenes should pause or reduce rendering when:

- the browser tab is hidden;
- the component is off-screen;
- the device is under load;
- the user enables reduced motion;
- GPU performance is insufficient.

The design goal is premium fluidity, not maximum polygons.

---

# 5. Main navigation

The initial desktop navigation should use a persistent left sidebar.

Primary destinations:

```text
Home
Projects
Agents
Workflows
Memory
Policies
Models
Tools
Activity
Settings
```

Nova remains accessible globally regardless of the active section.

The sidebar should support:

- compact/expanded modes;
- active-state indicators;
- badges for pending approvals or warnings;
- workspace/project context;
- quick access to command palette.

---

# 6. Home — Command Center

The home screen is the main operational dashboard.

It should remain **minimal and highly curated** rather than becoming a wall of widgets.

The initial content hierarchy is:

```text
Critical / actionable alerts
Nova command console
Current AI spend
Live tasks / Kanban
Active projects
Live agent activity
```

Not every module must always be visible.

The Orchestrator may organize and prioritize the home screen based on current context.

Examples:

- a blocked workflow moves upward;
- a pending confirmation becomes prominent;
- an inactive cost widget becomes more compact;
- the project currently being discussed becomes more visible;
- irrelevant cards may temporarily collapse.

The Orchestrator may **reorder, highlight or recommend dashboard modules**, but the user retains control over layout preferences.

---

# 7. Orchestrator-managed home

The home screen is adaptive.

The Orchestrator may produce a lightweight `HomeLayoutProposal` based on:

- current workflow state;
- pending approvals;
- recent user activity;
- project priority;
- deadlines;
- critical alerts;
- current conversation context;
- spending anomalies.

Conceptual example:

```json
{
  "priority_modules": [
    "approval_required",
    "nova_console",
    "live_tasks",
    "project_novalton"
  ],
  "collapsed_modules": [
    "monthly_cost_detail"
  ],
  "reason": "A deployment workflow is waiting for approval"
}
```

Adaptive organization must not silently delete user widgets or permanently rewrite user preferences.

User layout preferences remain authoritative.

---

# 8. Customizable dashboard

The user may customize the home screen.

Capabilities should eventually include:

- drag-and-drop widgets;
- resize widgets;
- pin/unpin;
- saved layouts;
- project-specific views;
- role-specific views;
- custom filters;
- custom KPI cards;
- custom Kanban views.

There are two layout layers:

```text
USER PREFERENCES
        +
ORCHESTRATOR TEMPORARY PRIORITIZATION
```

The Orchestrator may adapt the current presentation while respecting user-defined locked positions and pinned content.

---

# 9. Nova central command console

Nova is the primary natural-language control surface of Novalton OS.

The command console should be accessible:

- prominently on Home;
- through a global drawer/panel;
- through the command palette;
- from project pages;
- from workflow pages.

Nova should not behave like a plain chat box.

Responses may contain interactive operational objects such as:

- workflow proposals;
- task cards;
- agent cards;
- approval requests;
- simulations;
- cost estimates;
- memory references;
- project updates;
- diffs;
- warnings.

Example:

```text
Nova

I propose this workflow:

1. Legal research
2. Offer draft
3. User review
4. Email preparation

Agents: Legal, Commercial
Estimated AI cost: €0.06
External actions: none until step 4

[Approve]
[Modify]
[Reject]
[Simulate]
```

Nova is the **central command console**, not the only interface.

---

# 10. Alerts

The home screen should show a clean actionable alerts area.

Alert classes:

```text
INFO
ACTION_REQUIRED
WARNING
CRITICAL
```

The interface should distinguish between:

- information;
- something that deserves attention;
- something waiting for user input;
- something that requires immediate intervention.

Only `ACTION_REQUIRED` and `CRITICAL` should aggressively interrupt the user by default.

Alerts should support actions directly from the card when safe.

Example:

```text
Model escalation requested
Developer worker cannot complete architecture review reliably.

Current: DeepSeek V4 Flash Free
Proposed: premium reasoning model
Estimated additional cost: €0.08

[Approve]
[Choose model]
[Reject]
```

---

# 11. AI spending widget

AI cost must be visible without dominating the interface.

The home widget may display:

- current workflow spend;
- today's spend;
- monthly spend;
- remaining configured budget;
- abnormal increases;
- model distribution.

Example:

```text
AI Spend
Today      €0.14
This month €2.31 / €5.00
```

Detailed model/provider economics belong in the Models section.

---

# 12. Live task Kanban

Tasks should have a modern Kanban view suitable for both project management and real-time agent execution.

Default columns may include:

```text
BACKLOG
READY
RUNNING
REVIEW
BLOCKED
DONE
```

Cards may display:

- task title;
- project;
- assigned agent or human;
- current worker/model;
- progress;
- priority;
- deadline;
- cost;
- latest event;
- approval state;
- warning state.

Real-time events update cards without full-page reloads.

Example:

```text
Implement auth refresh
Developer Manager
Running • 68%
DeepSeek V4 Flash Free
Latest: backend tests running
€0.00
```

Tasks should be movable manually when policy allows.

---

# 13. Projects

Projects should feel like operational workspaces rather than static folders.

A project page may contain:

- project status;
- Nova project console;
- project Kanban;
- milestones;
- active workflows;
- assigned agents;
- recent decisions;
- relevant memory;
- recent artifacts;
- spend;
- risks and blockers;
- activity timeline.

The same project information may have multiple views:

```text
Overview
Board
Timeline
Workflows
Memory
Files / Artifacts
Activity
Settings
```

---

# 14. Agent interface

Agents should be represented as operational entities, not cartoon characters.

The Agents screen uses clean live cards.

Each card may show:

- agent name;
- role;
- status;
- number of active runs;
- current task;
- selected model;
- current spend;
- health/watchdog state;
- latest meaningful event.

Example:

```text
Developer Manager
RUNNING
2 workers active
Project: Novalton OS
€0.03

Backend Worker  82%
QA Worker       waiting
```

Opening an agent shows:

- definition;
- capabilities;
- permissions;
- active runs;
- historical runs;
- performance;
- operational lessons;
- model history;
- activity.

---

# 15. Workflow interface

Workflow execution should support two complementary representations.

## 15.1 Graph view

A modern node-based graph shows:

- workflow steps;
- dependencies;
- parallel branches;
- managers and workers;
- waiting approvals;
- failures;
- completed nodes;
- newly proposed steps.

The visual language should remain minimal and modern.

## 15.2 Timeline/list view

The timeline is optimized for operational reading.

Example:

```text
09:41 Developer Manager started
09:42 Backend Worker started
09:42 Frontend Worker started
09:46 Backend Worker requested tool
09:47 QA waiting for dependencies
09:49 Backend Worker completed
```

Users can switch between Graph and Timeline without losing state.

---

# 16. Detailed live execution

By default, the UI shows only concise operational events.

Example:

```text
Developer → preparing implementation plan
Backend Worker → modifying API schema
QA → running integration tests
Orchestrator → evaluating QA warning
```

A dedicated **Execution Detail** button may reveal deeper operational telemetry.

It may include:

- tool calls;
- structured agent outputs;
- retries;
- model selection;
- watchdog warnings;
- context-package metadata;
- cost/token usage;
- checkpoints;
- validation failures;
- escalation decisions.

It must not expose private chain-of-thought.

The purpose is observability, not dumping raw model reasoning.

---

# 17. Watchdog UI

When the Runtime Watchdog detects abnormal behavior, the interface should clearly communicate what happened.

Example:

```text
Worker intervention

Backend Worker was stopped after repeated non-progressing output.

Detected:
- repeated plan generation
- no tool calls
- high token consumption

Recovery:
- checkpoint preserved
- retry attempted once

Next recommendation:
Escalate model capability

[Review details]
[Approve escalation]
[Stop workflow]
```

The user should never have to inspect logs to understand why a worker disappeared.

---

# 18. Simulation interface

Simulation is a first-class interface pattern across the product.

It should be available from:

- Policies;
- Memory;
- Workflows;
- model escalation when useful;
- high-impact configuration changes.

Simulation results should use before/after or expected-impact visualization.

Example:

```text
Policy Simulation

27 actions evaluated
20 unchanged
5 now require confirmation
2 blocked

Affected agents:
Commercial
Personal Assistant

[Inspect changes]
[Apply]
[Cancel]
```

Simulation is visually distinct from real execution.

The user should never confuse simulated changes with applied changes.

---

# 19. Policies interface

The Policies section should make powerful rules understandable.

It should support:

- natural-language policy creation;
- structured policy editor;
- scope filters;
- enabled/disabled state;
- priority visualization;
- expiration;
- simulation;
- audit history.

Example interaction:

```text
User:
"Never allow the Commercial agent to send emails without asking me."

Nova translates:
commercial_agent + email.send
→ REQUIRE_CONFIRMATION

[Simulate]
[Activate]
[Edit]
```

---

# 20. Memory interface

Memory should be understandable to a human.

The Memory section may include:

```text
Explore
Entities
Timeline
Contradictions
Sources
Obsidian Sync
Integrity
```

Memory items should expose:

- value;
- knowledge state;
- provenance;
- scope;
- validity period;
- confidence;
- relationships;
- historical versions.

Useful actions:

```text
View source
Correct
Pin
Mark obsolete
Archive
Delete
Change sensitivity
Open in Obsidian
```

Obsidian sync should have a dedicated status panel and simulation view.

---

# 21. Models interface

The Models screen should expose the current Model Catalog and routing behavior.

It may show:

- available models;
- provider;
- health;
- cost;
- context window;
- capabilities;
- allowed tier;
- historical success;
- current usage;
- model route events.

The interface must distinguish:

```text
CURRENTLY AVAILABLE
DEGRADED
UNAVAILABLE
DISABLED BY USER
DISALLOWED BY POLICY
```

Users should not have to manually maintain model lists for normal operation.

---

# 22. Tools interface

Tools/plugins should have clear capability and permission visibility.

Each tool should show:

- status;
- connection state;
- capabilities;
- authorized scopes;
- which agents can request it;
- recent calls;
- policy restrictions.

Sensitive tools should surface their permission impact clearly.

---

# 23. Activity center

The Activity screen is the full operational timeline across Novalton OS.

Filters may include:

- project;
- agent;
- workflow;
- tool;
- severity;
- action type;
- date;
- model;
- approval state.

This is where deep auditability lives without cluttering Home.

---

# 24. Notification center

Notifications should have a polished dedicated center.

They may be grouped by:

```text
Needs action
Warnings
Workflow updates
System
History
```

Notifications should support:

- mark read;
- resolve;
- open related object;
- approve/reject when appropriate;
- mute category where policy allows.

The interface should make important events visible without turning every worker completion into a notification storm.

---

# 25. Command palette

`Ctrl+K` is a global command surface.

Potential commands:

```text
Ask Nova
Open project
Create task
Search memory
Open agent
Open workflow
Simulate policy
Pause workflow
Open approvals
Switch workspace
Search activity
```

The palette should support fuzzy search and keyboard navigation.

It should feel instantaneous.

---

# 26. Approvals UX

Approvals are a core product interaction.

Approval cards should explain:

- what will happen;
- why it is requested;
- what agent/workflow requested it;
- risk level;
- cost impact;
- affected resources;
- expiration where relevant.

Example:

```text
Approval requested

Allow Developer Worker to push branch `feature/auth`?

Scope: this workflow only
Risk: medium
Additional AI cost: none
Requested by: Developer Manager

[Approve once]
[Approve for workflow]
[Reject]
[Details]
```

Avoid generic “Are you sure?” dialogs wherever richer context is available.

---

# 27. Pause and Stop controls

Active workflows should expose visible controls:

```text
Pause
Stop
```

Pause:

- completes current atomic operations when safe;
- preserves checkpoints;
- prevents new steps from starting.

Stop:

- requests immediate termination;
- cancels cancellable operations;
- clearly indicates anything that cannot be reversed.

The UI must show the resulting state immediately.

---

# 28. Interaction motion

Motion should communicate state.

Useful animation examples:

- a card subtly transitions when a worker changes state;
- graph edges animate when work is active;
- completion gives a restrained success transition;
- warnings pulse once rather than continuously;
- layout reprioritization animates smoothly;
- Nova response objects appear progressively.

Animation should be short and interruptible.

Reduced-motion preferences must be respected.

---

# 29. Performance requirements

The interface should feel responsive even while many backend operations are active.

Guidelines:

- optimistic UI where safe;
- event-driven incremental updates;
- virtualized long lists;
- lazy loading;
- code splitting;
- controlled Three.js rendering;
- avoid unnecessary React rerenders;
- client state separated from durable backend truth.

The backend remains authoritative for workflow state.

---

# 30. Desktop-first V1

V1 is desktop-first.

Desktop is the primary environment for:

- project management;
- workflow graph inspection;
- agent management;
- memory administration;
- policy editing;
- configuration;
- development operations.

Responsive fundamentals should not be intentionally broken, but a complete mobile product is **not a V1 requirement**.

---

# 31. Mobile V2

Mobile is explicitly planned for V2.

The mobile experience should prioritize:

- Nova conversation;
- approval requests;
- alerts;
- task overview;
- project status;
- active agents;
- workflow progress;
- Pause / Stop controls;
- notifications.

Complex configuration and graph editing may remain desktop-focused.

---

# 32. Accessibility

Premium design must remain usable.

Requirements should include:

- keyboard navigation;
- focus states;
- adequate contrast;
- screen-reader labels;
- reduced motion;
- non-color-only status indicators;
- scalable text;
- usable zoom;
- semantic HTML where possible.

3D must never become the only representation of critical information.

---

# 33. Suggested frontend stack

The current architecture direction remains:

```text
Next.js
React
TypeScript
Tailwind CSS
shadcn/ui or equivalent headless components
Three.js / React Three Fiber where justified
WebSocket / SSE client
```

Potential supporting categories:

- drag/drop library;
- graph/node-flow library;
- animation library;
- charting library;
- command palette primitive;
- virtualization library.

Exact package choices should be verified at implementation time rather than frozen prematurely.

---

# 34. Design system

Novalton OS should have a coherent design system from the beginning.

Tokens should include:

- surfaces;
- borders;
- typography;
- spacing;
- radius;
- shadow/depth;
- motion durations;
- severity states;
- workflow states;
- agent states;
- focus states.

The interface should avoid one-off CSS when a reusable token/component can express the same concept.

---

# 35. Core reusable components

Initial shared components may include:

```text
NovaConsole
CommandPalette
AgentCard
AgentRunCard
WorkflowGraph
WorkflowTimeline
TaskCard
KanbanBoard
ApprovalCard
AlertCard
SimulationDiff
CostWidget
ProjectCard
MemoryItem
PolicyCard
ModelCard
RuntimeEvent
StatusBadge
WatchdogAlert
```

These are product concepts rather than permanent implementation names.

---

# 36. Real-time state model

The UI receives runtime events and updates visible state incrementally.

Conceptually:

```text
Backend Runtime
      |
Event Stream
      |
Frontend Event Store
      |
Derived UI State
      |
Cards / Graph / Timeline / Alerts
```

The frontend should recover from missed events by refetching authoritative snapshots.

Real-time transport failure must not leave the UI permanently inconsistent.

---

# 37. Trust-oriented UX

Novalton OS should make autonomy understandable.

Important actions should answer:

```text
WHAT is happening?
WHO requested it?
WHY?
WHAT will it affect?
HOW MUCH will it cost?
DO I need to approve it?
CAN I stop it?
```

Users should not need to infer whether an agent is merely drafting something or actually sending it.

The interface should make this distinction visually obvious.

---

# 38. Initial Home layout example

Conceptual desktop layout:

```text
┌───────────────────────────────────────────────────────────┐
│ Sidebar │ Alerts / action required                       │
│         ├─────────────────────────────────────────────────┤
│         │ Nova Command Console                            │
│         │ "What do you want to accomplish?"              │
│         ├──────────────────────┬──────────────────────────┤
│         │ Live Kanban          │ AI Spend                 │
│         │                      │                          │
│         ├──────────────────────┴──────────────────────────┤
│         │ Active Projects / Live Agents                   │
│         │                                                 │
└───────────────────────────────────────────────────────────┘
```

The exact layout remains adaptable and user-customizable.

---

# 39. V1 interface priorities

V1 should prioritize:

1. dark premium design system;
2. sidebar navigation;
3. Command Center home;
4. Nova console;
5. actionable alerts;
6. live Kanban;
7. projects;
8. agents and agent runs;
9. workflows graph + timeline;
10. approvals;
11. simulation UI;
12. costs;
13. Activity center;
14. Policy UI;
15. Memory UI;
16. Model Catalog visibility;
17. command palette;
18. real-time event updates;
19. watchdog visibility;
20. restrained Three.js visual layer.

Advanced dashboard customization may evolve progressively after the core experience is reliable.

---

# 40. Invariants

1. Nova is the central command console, not the entire product.
2. Home remains curated rather than becoming an uncontrolled widget wall.
3. The Orchestrator may adapt presentation but cannot silently override persistent user layout preferences.
4. Real-time progress is visible.
5. Deep execution telemetry is available through a dedicated detail view.
6. Private chain-of-thought is not displayed.
7. Simulation is visually distinct from real execution.
8. Approvals explain impact, reason, scope and cost.
9. Tasks support a real-time Kanban experience.
10. Graph and timeline views coexist for workflows.
11. Critical state must not depend on 3D visualization.
12. Three.js is progressive enhancement.
13. Performance is part of the design requirement.
14. V1 is desktop-first.
15. Mobile is planned for V2.
16. Accessibility and reduced motion are supported.
17. User control remains visible even during autonomous workflows.

---

# 41. Open design questions

Later design and implementation work should decide:

- exact visual identity and color system;
- typography;
- Nova 3D identity/visual metaphor;
- exact Three.js scenes;
- graph library;
- charting library;
- Kanban drag/drop behavior;
- dashboard widget schema;
- layout persistence model;
- orchestration rules for adaptive Home layout;
- exact notification delivery channels;
- notification grouping;
- animation library;
- keyboard shortcut map;
- information density presets;
- accessibility testing workflow;
- V2 mobile navigation.

---

# 42. Next document

The next specification should define the **Voice layer**.

`08-voice.md` should cover:

- local speech-to-text;
- wake word / activation;
- Nova voice interaction;
- text-to-speech;
- streaming latency;
- interruption / barge-in;
- confirmation for risky actions;
- voice identity;
- audio privacy;
- local-first voice processing;
- integration with the same Policy Engine;
- voice UI states;
- failure and fallback behavior.
