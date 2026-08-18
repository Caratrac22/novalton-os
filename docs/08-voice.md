# Novalton OS — Voice

> Version: 0.1 — 19 August 2026
>
> Status: Foundational draft

## 1. Purpose

The Voice layer turns Nova into a conversational interface for Novalton OS without creating a second, less-controlled path around the normal system.

Voice is an input/output modality, not a separate authority model.

A request spoken to Nova must be processed under the same orchestration, policy, memory, approval, budgeting, and audit rules as a request typed into the interface.

The design goal is an **enterprise Jarvis-style interaction model**:

- local wake word;
- local speech-to-text;
- free/local text-to-speech;
- low-latency conversational turns;
- continuous follow-up without repeating the wake word;
- spoken daily briefings;
- spoken explanations of approvals;
- UI approval for actions requiring confirmation;
- meeting/class transcription and summarization;
- interruption and barge-in;
- robust false-trigger protection;
- visible operational state.

---

# 2. Core principle

The voice interface must preserve the same trust model as text.

```text
Voice input
   |
   v
Speech-to-Text
   |
   v
Nova / Orchestrator
   |
   +--> Memory Engine
   +--> Policy Engine
   +--> Model Router
   +--> Workflow Runtime
   |
   v
Structured response / action proposal
   |
   +--> Text UI
   +--> Voice output
```

Voice does not bypass Policy Engine decisions.

If a typed command would require approval, the spoken equivalent requires the same approval.

---

# 3. Wake word

The default wake word is:

```text
Nova
```

The wake-word detector should run locally and continuously when voice mode is enabled.

The detector should be lightweight and independent from the main speech-to-text model.

A wake event should open a short-lived voice session rather than immediately interpreting arbitrary ambient audio as a command.

Potential later support:

- custom wake words;
- per-device wake settings;
- push-to-talk only mode;
- disable wake word temporarily;
- headset-specific listening.

---

# 4. Voice session model

Nova should behave like a conversation, not a sequence of isolated voice commands.

Conceptually:

```text
IDLE
  |
"Nova"
  |
LISTENING
  |
user speaks
  |
3 seconds silence
  |
TRANSCRIBING
  |
PROCESSING
  |
SPEAKING
  |
  +--> Nova asks a follow-up?
  |       |
  |       v
  |    LISTENING
  |
  +--> conversation complete
          |
          v
       SESSION_IDLE
```

The user should not need to repeat `Nova` after every response.

If Nova asks a question, requests clarification, or presents an approval-related explanation, the microphone returns to listening state automatically after Nova finishes speaking.

The voice session remains active while the conversation is naturally continuing.

---

# 5. End-of-turn detection

The initial V1 rule is:

> After approximately **3 seconds of detected silence**, Nova treats the current utterance as complete and sends it for transcription/processing.

The implementation should use Voice Activity Detection rather than only raw volume thresholds.

The 3-second value should eventually be configurable.

Important behavior:

- short natural pauses should not prematurely submit speech;
- background noise should not indefinitely hold the microphone open;
- the user may manually submit earlier;
- barge-in should interrupt Nova output and return to listening.

---

# 6. Speech-to-Text architecture

Speech-to-text should be **local by default**.

The STT implementation must be replaceable through a provider interface rather than hard-coded to one model forever.

Conceptually:

```text
Microphone audio
     |
     v
VAD / preprocessing
     |
     v
Local STT Provider
     |
     v
Transcript + metadata
```

Example output:

```json
{
  "text": "Nova, fais-moi le brief d'aujourd'hui",
  "language": "fr",
  "confidence": "high",
  "duration_ms": 2830,
  "segments": []
}
```

The STT provider may expose:

- transcript;
- detected language;
- timestamps;
- segment confidence;
- no-speech probability;
- audio duration;
- partial transcription when available.

---

# 7. Initial STT model direction

The user wants a local speech model in approximately the **~1B parameter class or below when practical**.

The architecture must not assume that the model name remains fixed forever.

At the time of this specification, a strong initial candidate for French/multilingual use is:

```text
OpenAI Whisper large-v3-turbo
~0.8B parameter class
multilingual
local inference capable
```

It may be run through an optimized local runtime such as faster-whisper/CTranslate2 where appropriate.

NVIDIA Parakeet 1.1B-class ASR models are also relevant candidates for the provider catalog, but currently identified 1.1B Parakeet variants are English-focused and therefore should **not** be the default French STT engine.

The STT provider catalog should record:

- supported languages;
- model size;
- latency;
- VRAM/RAM usage;
- word error performance where known;
- streaming capability;
- punctuation quality;
- local runtime support;
- license;
- current availability.

---

# 8. Local-only default for voice recognition

For V1, spoken audio should remain local by default.

Cloud STT must not silently become a fallback simply because local inference fails.

Possible later policy:

```text
LOCAL_ONLY
LOCAL_PREFERRED
CLOUD_ALLOWED_WITH_CONFIRMATION
```

Default:

```text
LOCAL_ONLY
```

This avoids sending ambient speech, meetings, classes, or sensitive conversations to external providers without an explicit policy decision.

---

# 9. Text-to-Speech

TTS should be free/local by default.

The TTS provider must be replaceable.

V1 priorities:

1. good French intelligibility;
2. low latency;
3. fully local/free execution;
4. acceptable naturalness;
5. interruption support;
6. manageable CPU/GPU usage.

The architecture should not depend on a commercial voice API.

Conceptually:

```text
Nova response
   |
   v
Speech formatter
   |
   v
Local TTS provider
   |
   v
Audio playback
```

A future workspace may optionally install additional local voices.

---

# 10. Voice output formatting

Nova should not blindly read the exact UI response aloud.

Voice responses should be optimized for listening.

For example, a UI may display:

```text
7 tasks
3 warnings
2 approvals
API spend today: €0.14
```

Nova may say:

> Aujourd'hui, tu as sept tâches actives. Trois demandent ton attention et deux nécessitent une approbation. Les dépenses IA du jour sont d'environ quatorze centimes.

The spoken version and visible version should remain semantically consistent.

Important details should remain visible on screen even when summarized aloud.

---

# 11. Daily Brief flow

A central voice workflow is:

> "Nova, fais-moi le brief d'aujourd'hui."

Expected flow:

```text
User asks for daily brief
       |
       v
Orchestrator gathers relevant context
       |
       +--> projects
       +--> tasks
       +--> calendar/context where permitted
       +--> alerts
       +--> agent activity
       +--> spending
       +--> pending approvals
       |
       v
Nova presents spoken brief
       |
       v
Nova reaches items requiring a decision
       |
       v
Explains them conversationally
       |
       v
UI displays required approval popup
       |
       v
Nova remains available for discussion
```

Example:

```text
Nova:
"Tu as deux éléments qui nécessitent ton approbation.
Le Developer veut passer sur un modèle plus puissant pour terminer l'audit backend.
Je peux t'expliquer pourquoi."

User:
"Pourquoi ?"

Nova:
"Le modèle actuel a échoué deux fois sur la même analyse..."

[UI popup remains visible]
```

The user should not have to say `Nova` again during this exchange.

---

# 12. Voice commands have the same semantic authority as text

A spoken request and a typed request are equivalent expressions of user intent.

Example:

```text
Typed:
"Crée une tâche pour revoir le contrat demain."

Spoken:
"Nova, crée une tâche pour revoir le contrat demain."
```

Both follow the same workflow and policy evaluation.

Voice is not treated as inherently less authoritative than text.

However, **approval mechanisms may differ by risk level**.

---

# 13. Approval rule

If Policy Engine returns:

```text
REQUIRE_CONFIRMATION
```

Nova may explain the action verbally, but final confirmation is performed through the UI popup by default.

Example:

```text
Nova:
"Le commercial veut envoyer cet email au client. Je t'affiche la demande d'approbation."

+-----------------------------------------+
| Send email to client@example.com        |
| Risk: external communication            |
|                                         |
| [Approve] [Modify] [Reject]              |
+-----------------------------------------+
```

This applies especially to:

- destructive actions;
- external communications;
- paid model escalation;
- permission changes;
- secret access;
- publishing;
- payments;
- high-impact workflow changes.

Voice discussion may continue while the popup remains pending.

---

# 14. Barge-in / interruption

The user must be able to interrupt Nova while it is speaking.

Example:

```text
Nova: "Aujourd'hui tu as sept tâches et le projet..."
User: "Attends, parle-moi seulement de Novalton."
```

Expected behavior:

1. detect user speech;
2. stop or duck TTS playback;
3. capture the new utterance;
4. preserve conversational context;
5. process the interruption;
6. continue from the updated intent.

Barge-in should feel immediate.

---

# 15. Conversation continuity

The Voice Session stores short-lived conversational context.

It should know:

- what Nova just said;
- what question Nova asked;
- which approval is being discussed;
- which project is currently in focus;
- whether Nova expects a response;
- whether TTS was interrupted.

This context belongs to the active session and should not automatically become durable long-term memory.

Important decisions may be extracted later by the Memory Engine under normal rules.

---

# 16. False-trigger protection

Wake-word detection alone is not enough.

Voice activation should combine multiple safeguards where practical:

- local wake-word detector;
- wake confidence threshold;
- Voice Activity Detection;
- short command capture window;
- echo suppression;
- rejection of obvious playback echo;
- optional known-device/microphone restrictions;
- optional speaker verification later;
- clear UI indication when listening.

A television, YouTube video, meeting recording, or Nova's own TTS must not easily trigger actions.

---

# 17. Echo and self-trigger prevention

Nova must not hear its own synthesized voice and interpret it as the user.

The audio layer should support:

- acoustic echo cancellation where available;
- output-reference subtraction where practical;
- temporary wake-word suppression during TTS;
- barge-in channel that distinguishes new user speech from playback;
- timestamp correlation between played audio and microphone input.

This is a runtime requirement, not merely a prompt rule.

---

# 18. Listening state UX

The interface must always make microphone state understandable.

Suggested states:

```text
OFF
WAKE_WORD_ARMED
LISTENING
PROCESSING_AUDIO
THINKING
SPEAKING
AWAITING_REPLY
MUTED
ERROR
```

The Command Center should display a subtle but unmistakable visual indicator.

Three.js effects may enhance this state representation, for example a responsive Nova orb, but functional state must remain understandable without 3D.

---

# 19. Nova visual voice object

A central voice visual may represent Nova as a premium interactive object rather than a generic microphone button.

Possible behavior:

```text
Idle        -> subtle slow movement
Wake        -> focused animation
Listening   -> reactive waveform/orb
Thinking    -> restrained processing animation
Speaking    -> audio-reactive visualization
Warning     -> visible state change
Approval    -> directs attention to popup
```

The visual must remain lightweight enough not to affect speech latency.

---

# 20. Meeting / Class Mode

Novalton OS should support a dedicated **Meeting / Class Mode**.

The objective is to listen, transcribe, organize, and summarize without automatically executing actions based on ambient speech.

Conceptually:

```text
Meeting / Class audio
       |
       v
Local STT
       |
       v
Transcript
       |
       +--> speakers if available
       +--> timeline
       +--> important concepts
       +--> decisions
       +--> action-item candidates
       +--> questions
       +--> summary
       |
       v
Review
```

The mode may be used for:

- business meetings;
- project discussions;
- calls;
- lessons/classes;
- brainstorming sessions;
- personal notes.

---

# 21. Meeting mode safety

Meeting/Class Mode is **observation-first**.

By default:

```text
TRANSCRIBE        -> allowed
SUMMARIZE         -> allowed
EXTRACT TASKS     -> allowed as proposals
STORE NOTES       -> according to memory policy
EXECUTE ACTIONS   -> disabled by default
SEND MESSAGES     -> disabled by default
```

If someone in a meeting says:

> "Supprime le projet demain."

Nova may record that sentence as part of the transcript, but must not interpret it as an authorized command.

Only explicit interaction with Nova in an active command session can create actionable user intent.

---

# 22. Class Mode

Class Mode may specialize Meeting Mode for learning.

Possible outputs:

- chronological notes;
- key concepts;
- definitions;
- formulas;
- examples;
- teacher instructions;
- homework candidates;
- unclear points;
- revision questions;
- flashcard candidates;
- compact lesson summary.

The user should be able to review before any extracted item becomes durable memory or a task where appropriate.

This mode must respect applicable recording/privacy rules and workspace policies.

---

# 23. Recording indicator

When Meeting/Class Mode records or transcribes continuous audio, the UI must make the recording state obvious.

The system should not implement hidden recording as a normal product behavior.

Visible controls:

```text
Start session
Pause capture
Resume
Stop
Discard
Save transcript
Generate summary
```

---

# 24. Transcript architecture

Long-form sessions should be stored in segments rather than one giant text field.

Conceptual structure:

```yaml
session_id: voice_session_123
mode: class
started_at: ...
ended_at: ...
segments:
  - segment_id: seg_001
    start_ms: 0
    end_ms: 8200
    speaker: unknown
    text: "..."
```

This supports:

- timeline navigation;
- partial correction;
- semantic search;
- source provenance;
- chapter/section summaries;
- speaker diarization later.

---

# 25. Voice and Memory Engine

Voice transcripts are source data.

They do not automatically become confirmed facts.

Flow:

```text
Voice transcript
     |
     v
Source Memory
     |
     v
Candidate extraction
     |
     +--> fact
     +--> decision
     +--> task
     +--> preference
     +--> note
     |
     v
Memory validation rules
```

Example:

A teacher saying "the exam may be Friday" should not become:

```text
Exam date = Friday [CONFIRMED_FACT]
```

It may instead be stored as an observation or candidate until confirmed.

---

# 26. Voice and the Orchestrator

Nova Voice should use the normal Orchestrator rather than directly sending transcripts to arbitrary agents.

```text
Speech
  |
Transcript
  |
Orchestrator
  |
  +--> simple response
  +--> workflow
  +--> memory retrieval
  +--> specialist agent
  +--> approval request
```

This keeps context, policies, budgets, and agent coordination consistent between voice and text.

---

# 27. Voice and Model Router

The Model Router still selects reasoning models normally.

The local STT/TTS engines are infrastructure providers and should not be confused with the reasoning model that interprets the user's request.

Example:

```text
Whisper Turbo
→ "Nova, résume le projet et dis-moi ce qui bloque"

Reasoning Model selected by Model Router
→ interprets request
→ Orchestrator gathers project state

Local TTS
→ speaks final answer
```

---

# 28. Voice latency targets

Voice interaction should feel responsive.

Rather than defining unrealistic hard guarantees at the architecture stage, Novalton OS should measure separate latency components:

```text
wake detection latency
end-of-turn delay
STT latency
orchestration latency
first-token latency
TTS first-audio latency
full response latency
```

The UI may start showing `Thinking` immediately after end-of-turn detection so the system never appears frozen.

---

# 29. Streaming response

Where supported, Nova should stream spoken responses rather than waiting for the complete final text.

Possible pipeline:

```text
Reasoning output stream
       |
Sentence / phrase buffer
       |
Local TTS
       |
Playback
```

However, the system must avoid speaking speculative fragments that are later contradicted by the completed response.

For sensitive outputs, Nova may wait for validated structured results before speaking.

---

# 30. Voice failure behavior

Failures must degrade clearly.

Examples:

```text
Wake detector unavailable
→ push-to-talk remains available

STT model unavailable
→ show local voice error
→ do not silently upload audio to cloud

TTS unavailable
→ display text response

Microphone permission denied
→ text interface remains functional

Transcription uncertain
→ show transcript and ask for clarification
```

Voice failure must never block the core Novalton OS interface.

---

# 31. Uncertain transcription handling

If STT uncertainty could materially change the action, Nova should not guess.

Example:

```text
Transcript candidate A:
"archive le projet"

Transcript candidate B:
"arrive le projet"
```

For a potentially destructive interpretation:

```text
→ do not execute
→ show what was heard
→ ask the user to clarify
```

The normal risk model applies after transcription.

---

# 32. Privacy and retention

Voice data may be highly sensitive.

The workspace should eventually support policies such as:

```text
retain raw audio: no
retain transcript: yes
retain meeting transcript: 30 days
retain summaries: durable
store locally only: yes
```

Default V1 direction:

- process audio locally;
- avoid retaining raw microphone audio for ordinary commands;
- retain command transcript only as needed for conversation/audit policy;
- Meeting/Class Mode may retain transcript according to explicit session settings;
- long-term memory extraction follows Memory Engine rules.

---

# 33. Voice audit events

Relevant runtime events may include:

```text
voice.wake_detected
voice.session_started
voice.listening_started
voice.utterance_completed
voice.transcription_started
voice.transcription_completed
voice.transcription_uncertain
voice.barge_in
voice.tts_started
voice.tts_interrupted
voice.tts_completed
voice.awaiting_reply
voice.session_closed
voice.meeting_started
voice.meeting_paused
voice.meeting_stopped
```

Do not store unnecessary raw audio in general event logs.

---

# 34. Device abstraction

Voice should not be tied to one microphone or computer.

Future devices may include:

- desktop microphone;
- headset;
- laptop microphone;
- dedicated room device;
- mobile device in V2;
- browser client;
- local satellite microphone.

A Voice Device registry may track:

```yaml
device_id: desktop_main
microphone: ...
speaker: ...
wake_enabled: true
meeting_mode_allowed: true
workspace_id: default
```

---

# 35. V1 deployment direction

Initial V1 voice execution is expected to run primarily on the user's desktop machine because it has the more suitable GPU for interactive local inference.

The backend/orchestrator may remain hosted on the Novalton OS server while the desktop Voice Client handles:

```text
microphone capture
wake-word detection
VAD
local STT
local TTS
speaker playback
```

Conceptually:

```text
Desktop Voice Client
   |
   | structured transcript/events
   v
Novalton Backend / Orchestrator
   |
   | structured response
   v
Desktop Voice Client
   |
Local TTS
```

This keeps heavy real-time audio processing close to the user while preserving centralized orchestration.

---

# 36. Voice Client security

A Voice Client must authenticate with the Novalton backend.

It should not be trusted merely because it is on the same LAN.

Requirements:

- authenticated device identity;
- encrypted transport when crossing network boundaries;
- revocable device authorization;
- scoped workspace permissions;
- session IDs;
- replay protection for sensitive commands where practical.

---

# 37. V1 capabilities

Voice V1 should prioritize:

1. local wake word `Nova`;
2. local French-capable STT;
3. local/free French-capable TTS;
4. push-to-talk fallback;
5. ~3-second silence end-of-turn detection;
6. conversational follow-ups without repeating the wake word;
7. interruption/barge-in;
8. Daily Brief spoken flow;
9. UI approval popup for confirmation-required actions;
10. same Policy Engine rules as text;
11. visible listening/thinking/speaking states;
12. Meeting/Class Mode;
13. transcript + summary generation;
14. action extraction as proposals only in Meeting/Class Mode;
15. local-only audio processing by default;
16. failure fallback to text UI.

---

# 38. V2 / later capabilities

Later versions may add:

- mobile voice client;
- speaker identification;
- multi-user rooms;
- multilingual auto-switching improvements;
- custom wake words;
- voice profiles;
- richer local TTS voices;
- speaker diarization;
- live meeting chapters;
- real-time collaborative transcripts;
- optional offline command execution;
- room microphone satellites;
- headset-specific mode;
- personalized acoustic adaptation.

---

# 39. Invariants

1. Voice and text share the same Policy Engine.
2. Voice commands do not bypass confirmation requirements.
3. Confirmation-required actions use UI approval by default.
4. The wake word is `Nova` by default.
5. Ordinary STT is local by default.
6. TTS is free/local by default.
7. Cloud STT is never a silent fallback.
8. Follow-up conversation does not require repeating the wake word.
9. Approximately 3 seconds of silence closes an utterance in the initial design.
10. Nova may be interrupted while speaking.
11. Nova must not trigger itself from its own TTS.
12. Meeting/Class Mode does not automatically execute ambient instructions.
13. Voice transcripts are sources, not automatically confirmed facts.
14. Long-term memory extraction follows Memory Engine rules.
15. Voice failure must not disable the text interface.
16. Local voice models are replaceable providers.
17. Model capabilities and language support must be verified before selection.
18. Audio retention is minimized by default.
19. Continuous recording must be visibly indicated.
20. High-risk uncertainty results in clarification rather than guessing.

---

# 40. Open design questions

Later implementation work must decide:

- exact wake-word engine;
- exact VAD implementation;
- benchmark of Whisper large-v3-turbo on target hardware;
- whether a smaller STT model is preferable for ultra-low-latency commands;
- final local French TTS engine and voice;
- audio device selection UX;
- echo cancellation implementation;
- streaming STT strategy;
- streaming TTS buffer size;
- Meeting/Class Mode diarization;
- transcript retention defaults;
- wake-word confidence thresholds;
- session timeout after Nova stops expecting a reply;
- whether local audio runs in a native desktop client, sidecar, or browser companion;
- offline behavior when the server is unreachable.

---

# 41. Next document

The next specification should define **SaaS foundations**.

`09-saas-foundations.md` should cover:

- tenant model;
- workspace model;
- users and roles;
- authentication;
- authorization boundaries;
- tenant isolation;
- billing-ready usage accounting;
- quotas;
- secrets isolation;
- model/API key ownership;
- deployment modes;
- local/hybrid/cloud operation;
- audit requirements;
- migrations from single-user V1 to SaaS;
- feature flags;
- plans/entitlements without prematurely implementing billing.
