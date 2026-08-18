# Novalton OS — Voice

> Version: 0.2 — 19 August 2026
>
> Status: Foundational draft

## 1. Purpose

The Voice layer turns Nova into a conversational interface for Novalton OS without creating a second, less-controlled path around the normal system.

Voice is an input/output modality, not a separate authority model.

A request spoken to Nova must be processed under the same orchestration, policy, memory, approval, budgeting, and audit rules as a request typed into the interface.

The design goal is an **enterprise Jarvis-style interaction model**:

- local wake word;
- local speech-to-text;
- local-first text-to-speech;
- low-latency conversational turns;
- continuous follow-up without repeating the wake word;
- spoken daily briefings;
- spoken explanations of approvals;
- UI approval for actions requiring confirmation;
- meeting/class transcription and summarization;
- interruption and barge-in;
- robust false-trigger protection;
- visible operational state;
- automatic lifecycle management of local AI models.

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

The STT provider may expose transcript, detected language, timestamps, segment confidence, no-speech probability, audio duration, and partial transcription when available.

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

NVIDIA Parakeet 1.1B-class ASR models are relevant candidates for the provider catalog, but currently identified 1.1B variants are English-focused and therefore should not be the default French STT engine.

The STT provider catalog should record supported languages, model size, latency, VRAM/RAM usage, streaming capability, punctuation quality, local runtime support, license, and current availability.

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

---

# 9. Text-to-Speech

TTS is **local-first and free by default**.

The normal operating path should be:

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

A commercial or cloud TTS provider must never be required for normal operation.

Cloud TTS may exist later as an optional provider, but only when explicitly enabled by workspace policy or the user.

V1 priorities:

1. good French intelligibility;
2. low latency;
3. fully local/free execution;
4. natural voice quality;
5. interruption/barge-in support;
6. manageable CPU/GPU usage;
7. streaming or low first-audio latency where practical.

The TTS provider must be replaceable, and additional local voices should be installable through the Local Model Manager.

---

# 10. Local Model Manager

Novalton OS should include a dedicated **Local Model Manager** as a cross-cutting system service.

Its purpose is to make local AI infrastructure behave like a managed platform instead of requiring the user to manually download models, find files, update runtimes, and clean caches.

The Local Model Manager is used by Voice for STT/TTS, but its architecture should support other local models later.

```text
Local Model Catalog
       |
       v
Compatibility Resolver
       |
       +--> GPU / VRAM
       +--> RAM
       +--> CPU
       +--> OS
       +--> runtime
       +--> disk space
       |
       v
Local Model Manager
       |
       +--> install
       +--> download
       +--> verify
       +--> activate
       +--> update
       +--> rollback
       +--> uninstall
       +--> repair
       +--> clean cache
       +--> health check
```

---

# 11. Local model catalog

The system should maintain a live catalog of known local models and runtimes.

A catalog entry may contain:

```yaml
model_id: whisper-large-v3-turbo
kind: stt
provider: local
languages:
  - fr
  - en
parameter_class: 0.8B
runtime_options:
  - faster-whisper
  - ctranslate2
hardware:
  min_ram_gb: ...
  recommended_vram_gb: ...
license: ...
source: ...
version: ...
status: available
```

The catalog must not treat model names, download URLs, runtime versions, or compatibility assumptions as permanent truths.

Metadata should be refreshable and versioned.

---

# 12. Automatic installation flow

When a local capability is required but not installed, Nova may propose or automatically perform installation according to policy.

Example:

```text
Voice setup requires French STT
       |
       v
Local Model Manager checks installed models
       |
       v
No compatible STT found
       |
       v
Select compatible candidate
       |
       v
Show download size + disk impact + hardware fit
       |
       v
Policy evaluation
       |
       v
Download
       |
       v
Checksum / integrity validation
       |
       v
Runtime validation
       |
       v
Smoke test
       |
       v
Activate
```

Large downloads, major runtime changes, or actions with meaningful disk/network impact may require confirmation according to Policy Engine rules.

---

# 13. Updates and rollback

The Local Model Manager should periodically detect available model/runtime updates.

It must distinguish:

```text
MODEL WEIGHTS UPDATE
RUNTIME UPDATE
CONFIG UPDATE
VOICE PACKAGE UPDATE
SECURITY UPDATE
```

Updates should not blindly replace a working setup.

Preferred flow:

1. detect update;
2. check release/source metadata;
3. estimate compatibility and disk impact;
4. download to a staging location;
5. verify integrity;
6. run a smoke test;
7. switch active version;
8. keep previous version temporarily for rollback;
9. remove old versions later according to storage policy.

If the new version fails, Novalton OS should automatically return to the last known-good version when technically possible.

---

# 14. Uninstall and cleanup

The user should be able to ask:

> "Nova, désinstalle les modèles vocaux que je n'utilise plus."

The system should first simulate the effect and show dependencies.

Example:

```text
Model: local_tts_fr_v2
Used by: Nova Voice default profile
Disk usage: 1.8 GB

Removing it would disable local TTS until another provider is selected.
```

Uninstall should clean:

- model weights;
- model-specific caches;
- stale runtime files when no longer shared;
- temporary downloads;
- obsolete versions;

Shared runtimes or assets must not be deleted if another installed model still depends on them.

---

# 15. Hardware-aware selection

The Local Model Manager must understand the machine it is running on.

It should maintain a hardware profile containing, where available:

- GPU vendor/model;
- VRAM;
- CUDA/DirectML/other acceleration availability;
- system RAM;
- CPU architecture;
- available disk space;
- operating system;
- supported runtime versions.

Before installation it should classify candidates such as:

```text
RECOMMENDED
SUPPORTED
SUPPORTED_BUT_SLOW
INSUFFICIENT_MEMORY
INCOMPATIBLE_RUNTIME
INSUFFICIENT_DISK
UNKNOWN
```

The goal is to prevent Nova from downloading a beautiful 40 GB model onto hardware that will contemplate its existence at 0.3 tokens per geological era.

---

# 16. Local model health

Installed models should expose health information.

Possible state:

```yaml
status: healthy
active_version: ...
runtime: ...
last_smoke_test: ...
avg_latency_ms: ...
last_error: null
```

The manager may detect:

- corrupt weights;
- missing runtime dependencies;
- incompatible runtime upgrades;
- repeated crashes;
- GPU OOM;
- unusually slow inference;
- missing files;
- failed initialization.

Repair should prefer restoring a known-good installation rather than repeatedly retrying a broken setup forever.

---

# 17. Model storage management

Local model storage should be centralized and understandable.

The UI should show:

```text
Local AI storage
STT        3.2 GB
TTS        1.4 GB
Wake word  120 MB
Cache      850 MB
Old versions 2.1 GB
```

The user may trigger a safe cleanup simulation.

The system should support configurable storage locations later, including a fast local SSD for active models and slower storage for archived versions where appropriate.

---

# 18. Security and provenance of local models

The Local Model Manager should not download arbitrary model files merely because an agent generated a URL.

Downloads must originate from approved catalog sources or explicit user-authorized sources.

The manager should preserve:

- source URI/reference;
- model/revision identifier;
- checksum when available;
- license metadata;
- install timestamp;
- installed-by actor/workflow;
- runtime version;
- verification result.

Local model installation and removal are auditable system actions.

---

# 19. Voice output formatting

Nova should not blindly read the exact UI response aloud.

Voice responses should be optimized for listening while remaining semantically consistent with the visible response.

Important details should remain visible on screen even when summarized aloud.

---

# 20. Daily Brief flow

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

The user should not have to say `Nova` again during this exchange.

---

# 21. Voice commands have the same semantic authority as text

A spoken request and a typed request are equivalent expressions of user intent.

Both follow the same workflow and policy evaluation.

Voice is not treated as inherently less authoritative than text.

---

# 22. Approval rule

If Policy Engine returns `REQUIRE_CONFIRMATION`, Nova may explain the action verbally, but final confirmation is performed through the UI popup by default.

This applies especially to destructive actions, external communications, paid model escalation, permission changes, secret access, publishing, payments, and high-impact workflow changes.

Voice discussion may continue while the popup remains pending.

---

# 23. Barge-in / interruption

The user must be able to interrupt Nova while it is speaking.

Expected behavior:

1. detect user speech;
2. stop or duck TTS playback;
3. capture the new utterance;
4. preserve conversational context;
5. process the interruption;
6. continue from the updated intent.

---

# 24. Conversation continuity

The Voice Session stores short-lived conversational context such as what Nova just said, what question it asked, which approval is being discussed, which project is in focus, whether Nova expects a response, and whether TTS was interrupted.

This context belongs to the active session and should not automatically become durable long-term memory.

---

# 25. False-trigger protection

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

A television, video, meeting recording, or Nova's own TTS must not easily trigger actions.

---

# 26. Echo and self-trigger prevention

Nova must not hear its own synthesized voice and interpret it as the user.

The audio layer should support acoustic echo cancellation where available, output-reference subtraction where practical, temporary wake-word suppression during TTS, a barge-in channel, and timestamp correlation between played audio and microphone input.

---

# 27. Listening state UX

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

Three.js effects may enhance this state representation, but functional state must remain understandable without 3D.

---

# 28. Meeting / Class Mode

Novalton OS should support a dedicated **Meeting / Class Mode**.

The objective is to listen, transcribe, organize, and summarize without automatically executing actions based on ambient speech.

Possible outputs include speakers if available, timeline, important concepts, decisions, action-item candidates, questions, and summaries.

---

# 29. Meeting mode safety

Meeting/Class Mode is observation-first.

```text
TRANSCRIBE        -> allowed
SUMMARIZE         -> allowed
EXTRACT TASKS     -> allowed as proposals
STORE NOTES       -> according to memory policy
EXECUTE ACTIONS   -> disabled by default
SEND MESSAGES     -> disabled by default
```

Ambient speech is never treated as authorized command intent by default.

---

# 30. Class Mode

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

The user should be able to review before extracted items become durable memory or tasks where appropriate.

---

# 31. Recording indicator

When Meeting/Class Mode records or transcribes continuous audio, the UI must make the recording state obvious.

Visible controls should include Start, Pause, Resume, Stop, Discard, Save transcript, and Generate summary.

---

# 32. Transcript architecture

Long-form sessions should be stored in segments rather than one giant text field, supporting timeline navigation, partial correction, semantic search, provenance, summaries, and later speaker diarization.

---

# 33. Voice and Memory Engine

Voice transcripts are source data. They do not automatically become confirmed facts.

Candidate extraction into facts, decisions, tasks, preferences, or notes follows normal Memory Engine validation rules.

---

# 34. Voice and the Orchestrator

Nova Voice uses the normal Orchestrator rather than directly sending transcripts to arbitrary agents.

This keeps context, policies, budgets, and agent coordination consistent between voice and text.

---

# 35. Voice and Model Router

The Model Router still selects reasoning models normally.

Local STT/TTS engines are infrastructure providers and should not be confused with the reasoning model that interprets the user's request.

The Model Router may ask the Local Model Manager for local capability availability, but local voice model lifecycle is owned by the Local Model Manager.

---

# 36. Voice latency

Novalton OS should measure wake detection latency, end-of-turn delay, STT latency, orchestration latency, first-token latency, TTS first-audio latency, and full response latency.

The UI may show `Thinking` immediately after end-of-turn detection so the system never appears frozen.

---

# 37. Streaming response

Where supported, Nova should stream spoken responses using phrase/sentence buffering into local TTS.

For sensitive outputs, Nova may wait for validated structured results before speaking.

---

# 38. Voice failure behavior

Examples:

```text
Wake detector unavailable
→ push-to-talk remains available

STT model unavailable
→ Local Model Manager attempts repair or reports local voice error
→ do not silently upload audio to cloud

TTS unavailable
→ Local Model Manager attempts repair/fallback to another installed local provider
→ display text response if unavailable

Microphone permission denied
→ text interface remains functional
```

Voice failure must never block the core Novalton OS interface.

---

# 39. Privacy and retention

Default V1 direction:

- process audio locally;
- avoid retaining raw microphone audio for ordinary commands;
- retain command transcript only as needed for conversation/audit policy;
- Meeting/Class Mode may retain transcript according to explicit session settings;
- long-term memory extraction follows Memory Engine rules.

---

# 40. Runtime events

Relevant events may include:

```text
voice.wake_detected
voice.session_started
voice.listening_started
voice.transcription_completed
voice.barge_in
voice.tts_started
voice.tts_interrupted
voice.tts_completed
voice.awaiting_reply
voice.meeting_started
voice.meeting_stopped
local_model.install_started
local_model.install_completed
local_model.update_available
local_model.update_started
local_model.rollback_completed
local_model.health_failed
local_model.repair_completed
local_model.uninstalled
```

---

# 41. Device abstraction

Voice should not be tied to one microphone or computer.

Future devices may include desktop microphone, headset, laptop microphone, dedicated room device, mobile V2, browser client, and local satellite microphones.

---

# 42. V1 deployment direction

Initial V1 voice execution is expected to run primarily on the desktop machine because it has the more suitable GPU for interactive local inference.

The backend/orchestrator may remain on the Novalton OS server while the desktop Voice Client handles microphone capture, wake-word detection, VAD, local STT, local TTS, speaker playback, and local model runtime integration.

The Local Model Manager may have a central control plane in Novalton OS and a per-device runtime component so each machine reports what it can run.

---

# 43. Voice Client security

A Voice Client must authenticate with the Novalton backend and should not be trusted merely because it is on the same LAN.

Local model installation actions should also be scoped to authorized devices and audited.

---

# 44. V1 capabilities

Voice V1 should prioritize:

1. local wake word `Nova`;
2. local French-capable STT;
3. local-first/free French-capable TTS;
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
16. Local Model Manager for STT/TTS installation, update, repair, rollback and uninstall;
17. hardware-aware local model selection;
18. local model storage management;
19. failure fallback to text UI.

---

# 45. V2 / later capabilities

Later versions may add mobile voice client, speaker identification, multi-user rooms, multilingual improvements, custom wake words, voice profiles, richer local TTS voices, diarization, live meeting chapters, real-time collaborative transcripts, optional offline command execution, and room microphone satellites.

The Local Model Manager may also expand beyond voice into embeddings, OCR, vision, coding, reranking, or compact reasoning models where local execution is useful.

---

# 46. Invariants

1. Voice and text share the same Policy Engine.
2. Voice commands do not bypass confirmation requirements.
3. Confirmation-required actions use UI approval by default.
4. The wake word is `Nova` by default.
5. Ordinary STT is local by default.
6. TTS is local-first and free by default.
7. Cloud STT/TTS is never a silent fallback.
8. Follow-up conversation does not require repeating the wake word.
9. Approximately 3 seconds of silence closes an utterance in the initial design.
10. Nova may be interrupted while speaking.
11. Nova must not trigger itself from its own TTS.
12. Meeting/Class Mode does not automatically execute ambient instructions.
13. Voice transcripts are sources, not automatically confirmed facts.
14. Long-term memory extraction follows Memory Engine rules.
15. Voice failure must not disable the text interface.
16. Local voice models are replaceable providers.
17. Local model names and download locations are not permanent hard-coded truth.
18. The Local Model Manager validates compatibility before activation.
19. Local model updates support safe rollback where practical.
20. Uninstall must respect shared dependencies.
21. Local model lifecycle actions are auditable.
22. Audio retention is minimized by default.
23. Continuous recording must be visibly indicated.
24. High-risk uncertainty results in clarification rather than guessing.

---

# 47. Open design questions

Later implementation work must decide:

- exact wake-word engine;
- exact VAD implementation;
- benchmark of Whisper large-v3-turbo on target hardware;
- final local French TTS engine and voice;
- Local Model Manager package/runtime format;
- approved local model catalog sources;
- model checksum/signature strategy;
- update cadence;
- disk cleanup defaults;
- whether model downloads are centralized or per-device;
- audio device selection UX;
- echo cancellation implementation;
- streaming STT/TTS strategy;
- Meeting/Class Mode diarization;
- transcript retention defaults;
- wake-word confidence thresholds;
- session timeout;
- offline behavior when the server is unreachable.

---

# 48. Next document

The next specification should define **SaaS foundations**.

`09-saas-foundations.md` should cover tenant/workspace models, users and roles, authentication, authorization boundaries, tenant isolation, billing-ready usage accounting, quotas, secrets isolation, model/API key ownership, deployment modes, local/hybrid/cloud operation, audit requirements, migrations from single-user V1 to SaaS, feature flags, and plans/entitlements without prematurely implementing billing.
