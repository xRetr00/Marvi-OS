# Marvi OS

![Marvi OS banner](assets/marvi-os-banner.png)

<p align="center">
  <strong>Your computer, closer to a conversation.</strong><br>
  An always-present Windows assistant for voice, memory, vision, and action.
</p>

<p align="center">
  <a href="https://github.com/xRetr00/Marvi-OS/releases">Explore releases</a>
  ·
  <a href="#what-marvi-can-do">See what Marvi can do</a>
  ·
  <a href="#how-marvi-compares">Compare assistants</a>
  ·
  <a href="#start-with-marvi">Get started</a>
</p>

---

## Meet an assistant that lives with your day

Most assistants wait in a tab. Marvi stays close to what you are doing on Windows. Call her by voice or shortcut, ask naturally, and keep working. A compact **Dynamic Island** shows when she is listening, speaking, acting, or waiting for your approval. Open the control center when you want the full picture.

Marvi can remember a preference you mentioned last week, find a past conversation, help with a file, check on your room, or hand a longer task to a specialist. She can also decide that the useful thing to do is stay quiet.

> **“Marvi, remind me what we decided about the trip, find the document, and let me know when the room is empty.”**
>
> One request can draw on conversation history, connected context, local tools, and room state. Marvi shows the work and asks when an action needs your approval.

### A day with Marvi

| Moment | What you can ask | What happens |
|---|---|---|
| **Starting work** | “What did I leave unfinished yesterday?” | Marvi can search prior conversations and Cortex, then bring the relevant context into a short answer. |
| **Hands full** | “Pause the music, then remind me to call Sam in an hour.” | A voice request can use a local media control and create a durable reminder. |
| **Deep work** | “Fix the failing test while I keep working.” | Harvi takes a scoped job. You can watch its progress, stop it, and review the report. |
| **On the computer** | “Open the app and find the setting I need.” | Jarvi can work through Windows app controls while the Island shows activity and a Stop action. |
| **Away from the desk** | “Did anything important happen?” | A linked Telegram conversation can reach the same assistant and its memory. |
| **In the room** | “Let me know when the room is empty.” | Smart Room events can become a quiet Island update or a deferred announcement. |

These are examples of how Marvi's pieces work together; available actions depend on the capabilities and accounts you enable.

### Why Marvi feels different

| | What it means for you |
|---|---|
| **Voice is the front door** | Speak hands-free, interrupt, or switch to typing when a task needs more detail. |
| **The Island respects your focus** | A small desktop presence expands for speech, progress, alerts, and approvals, then gets out of the way. |
| **Memory is inspectable** | Explore what Marvi remembers, see where it came from, correct it, export it, or erase it. |
| **Action has a visible trail** | Follow delegated work, review activity, stop a task, and approve specific actions in Confirm mode. |
| **Your setup, your models** | Use local models or connect a provider. Add capabilities and accounts as you need them. |
| **Your world is part of the context** | With Smart Room connected, room presence and devices can inform helpful, timely responses. |

## What Marvi can do

### Talk without taking over your screen

Use a wake phrase or a global shortcut to begin. Marvi's voice experience is built around live conversation: she can listen while speaking, respond to interruption, and return to the background when the exchange ends. The voice stack uses local wake detection and local speech components, with the conversational model selected in your provider settings.

Prefer a keyboard? The control center has Chat for longer threads, attachments, images, dictation, source references, and read-aloud. You can move between a quick spoken request and a more detailed written one without changing assistants.

Chat shows provider failures in a retryable card and offers a conversation map
for navigating longer threads. The Sub-agents panel identifies Claude Code and
Codex with their respective logos.

Voice is being qualified against real speaker and microphone behavior. Local wake detection, speech recognition, synthesis, interruption handling, and a local LiveKit session are implemented; the [voice phase](docs/phases/03-full-duplex-voice.md) records the remaining streaming and soak gates.

### See only what matters

The **Dynamic Island** is Marvi's glanceable home. It shows a live voice state, a concise announcement, a confirmation, or the progress of computer work. Background events do not pull the main window into focus. Quiet hours, cooldowns, presence, and Windows presentation state help Marvi choose when to speak and when to wait.

The control center gives you dedicated places for Voice, Chat, Vision, Smart Room, Activity, Cortex, connected capabilities, and preferences.

You can change global shortcuts for summoning Marvi, stopping her, opening Chat, showing the control center, and viewing shortcuts. The optional desktop companion mirrors Marvi's live state when you want a more expressive presence.

### Build a memory you can trust

**Marvi Cortex** connects useful facts, people, preferences, relationships, and recurring patterns. Memories retain their sources so you can ask *why* Marvi knows something. Inspect the graph, edit your identity and preferences, forget a fact, or export memory for your own use.

Your assistant's personality is yours to shape. Marvi keeps her editable identity separate from what she learns about you, so a preference does not silently rewrite her character.

Cortex has durable episodic and semantic memory, a graph view, provenance, reflection, and explicit forgetting. A memory export can create an Obsidian-friendly vault. Marvi also offers read-only memory recall to other tools over MCP, so useful context does not have to stay trapped in one interface.

### Turn requests into work

Marvi can search the web, work with files, use clipboard and media controls, schedule jobs, and call connected tools. File changes made through Marvi's file tools keep a checkpoint you can restore from Activity.

Longer tasks can go to a specialist while you keep talking:

| Specialist | Helps with | What you see |
|---|---|---|
| **Harvi** | Code and workspace tasks | A live job card with steps, status, and a final report |
| **Jarvi** | Windows apps and desktop actions | Island activity, Stop, and a private-input handoff |
| **Talos** | Browser tasks | Browser workspace and task progress |

Marvi can also hand coding work to supported outside agents through the Agent Client Protocol. Confirmations travel back to the same approval surface instead of disappearing inside a background process.

For browser work, the visible browser workspace keeps profiles, tabs, and a private-login handoff together. For computer work, Jarvi uses native Windows app controls and a clearly labeled agent pointer. You can stop the work or take over sensitive input yourself. Both paths have working implementations and ongoing acceptance checks.

### Connect the digital and physical worlds

Connect accounts and tools through supported integrations, skills, plugins, and MCP. Marvi can use connected information as context while treating content from pages, messages, files, and services as untrusted data. A linked Telegram bot lets you reach the same Marvi away from your desk, including memory and approvals.

With **Smart Room**, Marvi can understand room presence, conditions, devices, gestures, and familiar faces. Camera analysis stays with the local room system; Marvi receives bounded observations and events rather than raw camera streams.

Connected accounts can bring email, calendars, documents, and other services into reach through supported connectors. Marvi separates what an external source *says* from what you *instructed* her to do, then routes actions through the same tool and confirmation controls.

### Make time work for you

Create one-time reminders, repeating schedules, or bounded agent jobs. Choose the model and tools a job may use, review its run history, pause it, or run it on demand. Marvi's proactive mind can surface a meaningful event, defer it until a better moment, or leave you uninterrupted.

Schedules support one-time times, intervals, local daily times, and cron expressions. Each run has a durable result and history. Proactive decisions also have a reason: quiet hours, active conversation, cooldown, presence, and daily budget can all lead Marvi to wait.

## How Marvi works

```mermaid
flowchart LR
    A["You speak, type, or schedule"] --> B["Marvi understands the request"]
    C["Memory, room, and connected context"] --> B
    B --> D{"What helps now?"}
    D --> E["Answer in voice or Chat"]
    D --> F["Show a quiet Island update"]
    D --> G["Use a tool or delegate a task"]
    G --> H["Ask for approval when required"]
    E --> I["Consider useful context for Cortex"]
    F --> I
    H --> I
```

The local Gateway keeps sessions, tool execution, confirmations, and the activity trail together. The desktop presents that state; it does not need to stay open for Marvi's background services to keep working. You can see what she is doing, stop work, and decide what she may remember.

For example, a request to “find the notes from our last conversation and make a reminder” starts with conversation recall, then proposes a scheduled action. The answer appears in the conversation; the reminder has its own durable record. If Marvi needs approval for an action, the Island and voice can present the same exact request.

## Privacy and control are part of the experience

Raw microphone and camera streams stay local. A local wake listener and Smart Room process those signals on your machine. When you select a cloud model, the text and context needed for that request go to that provider; choose local models and local-only mode when you want model calls to remain on your machine.

| Your choice | How Marvi responds |
|---|---|
| **Confirm mode** | Marvi requests approval for actions she marks as needing it. A spoken answer or Island action can approve the exact request. |
| **YOLO mode** | Approval prompts are bypassed, with an unmistakable persistent indicator. Validation and activity history remain in place. |
| **Private input** | Pause browser or computer observation while you enter sensitive information yourself, then resume with a fresh view. |
| **Memory controls** | Inspect, correct, export, or delete what Cortex retains. |
| **Capability controls** | Choose connected accounts, models, tools, accessible folders, voice behavior, and proactive speech. |

## How Marvi compares

The agent ecosystem is moving quickly, and several projects do things Marvi does not yet do. This comparison uses each project's own documentation, checked in September 2026. **OpenAgent** here means [the-open-agent/openagent](https://github.com/the-open-agent/openagent); **OpenAgents** is a separate project.

| Project | What it is built around | Where it is stronger today | Why choose Marvi instead |
|---|---|---|---|
| **Marvi OS** | A Windows-first voice and vision presence, with the Dynamic Island, Cortex, Smart Room, desktop action, and one approval path | Its differentiator is the way these surfaces work together in a local Windows experience; voice, browser, and computer use still have qualification gates | You want the assistant to be part of your desktop and room, available without living in a terminal or message thread |
| [**Hermes Agent**](https://hermes-agent.nousresearch.com/) | A self-improving agent across desktop, CLI, and messaging | Broader messaging reach, cross-platform desktop support, reusable skills, browser tools, and mature delegated workflows | You care most about an ambient Windows surface, local room awareness, and visible voice and computer handoffs |
| [**OpenHuman**](https://github.com/tinyhumansai/openhuman) | A local-first personal memory system and durable multi-agent orchestrator | Its documented Memory Tree, Obsidian wiki, extensive integrations, auto-fetch, and restartable agent graphs go further than Marvi's current scope | You want a focused Windows companion whose voice, Island, room context, and approvals are the main experience |
| [**OpenClaw**](https://docs.openclaw.ai/) | A self-hosted gateway that reaches you through messaging apps | Many more channels, plugin routes, webhooks, and remote chat surfaces | Your primary interaction is the Windows desktop, with speech and a glanceable Island before messaging |
| [**OpenAgent**](https://github.com/the-open-agent/openagent) | A self-hostable agent platform with RAG knowledge bases, models, tools, and APIs | Its single-binary deployment, document RAG, administration, and programmable platform surface fit knowledge-base and team workflows | You want a personal ambient desktop experience at the center |
| [**Agent Zero**](https://github.com/agent0ai/agent-zero) | An agent with a Dockerized Linux desktop and browser work environment | An isolated full Linux computer, document cowork, project workspaces, and a broad plugin ecosystem | You want an assistant integrated with your actual Windows session and physical room |
| [**OpenAgents**](https://github.com/openagents-org/openagents) | A shared workspace where multiple agents and people collaborate | Shared threads, files, and browser access across many agent runtimes | You want one personal assistant to coordinate your day, with specialists behind it when needed |

Marvi does **not** claim the broadest channel list, the largest integration catalog, or the most mature agent graph. Its bet is more specific: **an assistant that can listen, remember, act on your Windows computer, understand your room, and give your attention back when the moment passes.**

### Compare by the job you need done

| If your priority is… | Start by looking at… |
|---|---|
| An ambient Windows voice companion with room context and visible approvals | **Marvi OS** |
| One agent across desktop, terminal, and many messaging services | **Hermes Agent** |
| Deep local memory, account ingestion, and durable agent orchestration | **OpenHuman** |
| A self-hosted assistant reached through many chat apps | **OpenClaw** |
| RAG, document workflows, and an agent platform API | **OpenAgent** |
| A full isolated Linux desktop for agent work | **Agent Zero** |
| A workspace where multiple coding agents collaborate | **OpenAgents** |

## Where the project stands

Marvi OS is in active development. Here is the practical distinction between what is implemented and what still needs qualification:

| Experience | Current state |
|---|---|
| **Desktop shell and Dynamic Island** | Complete, with background behavior, focus rules, and a control center |
| **Cortex memory and proactive behavior** | Implemented, with graph inspection, provenance, forgetting, and quiet-hours policy |
| **Smart Room and Vision integration** | Implemented; native Windows hardware soak remains a separate gate |
| **Scheduled jobs** | Complete, with editable jobs and durable run history |
| **Telegram** | Implemented; more messaging channels are researched but not shipped |
| **Voice conversation** | Working local wake, speech, and interruption path; the real speaker double-talk and long soak gates remain open |
| **Visible browser** | Embedded browser and handoff implemented; qualification continues |
| **Native computer use** | Windows app control and Island handoff implemented; final live acceptance continues |
| **Specialist agents** | Harvi and Jarvi have real-host evidence; Talos still needs a real-host run |
| **Jobs board** | Planned |

See the [delivery phase index](docs/phases/README.md) for the latest acceptance status and evidence. A feature can be present in the codebase before every hardware, account, and recovery gate is complete.

## Questions people ask

**Does Marvi need the cloud?** You can choose local models and enable local-only mode for model calls. If you choose a hosted provider, Marvi sends the request's required text and context to that provider. Raw microphone and camera streams stay local.

**Can I see what Marvi remembers?** Yes. Cortex exposes memories and relationships, and you can correct, forget, or export them. The Identity page keeps your standing preferences separate from Marvi's editable personality.

**Can Marvi act without asking me?** Confirm and YOLO are explicit user choices. Confirm lets Marvi request approval for specific actions. YOLO bypasses approval prompts and keeps a persistent indicator and audit trail.

**What happens if I need to type a password?** Private input pauses browser or computer observation, gives you the controls, and resumes from a fresh state when you are done.

**Is Marvi a coding agent?** Marvi is a personal assistant. Harvi can take a scoped coding job, and supported external coding agents can be called through the Agent Client Protocol, while Marvi remains your conversational front door.

## Start with Marvi

1. Visit [Marvi OS releases](https://github.com/xRetr00/Marvi-OS/releases) for available Windows builds.
2. Run the Marvi bootstrap and follow setup to choose the components your machine needs.
3. Connect a model provider or select a local model, then add voice, room, browser, computer, and account capabilities as you want them.
4. Call Marvi by voice or shortcut. The Island is ready when you are.

Start with a model provider and Chat, then add the components that make sense for your machine. Voice adds local wake and speech components. Smart Room adds physical-space awareness through its own local service. Browser and computer capabilities can be enabled when you want Marvi to act on visible work.

Setup verifies downloads and can resume interrupted ones. The control center helps you manage providers and capabilities later, so your first configuration does not have to be final. For setup details and current requirements, see [Setup](docs/SETUP.md).

---

<p align="center">
  <strong>Voice. Vision. Memory. Action.</strong><br>
  More help when it matters. More space when it doesn't.
</p>

<p align="center">
  <a href="https://github.com/xRetr00/Marvi-OS/releases">Explore releases</a>
  ·
  <a href="docs/phases/README.md">See progress</a>
  ·
  <a href="LICENSE">MIT License</a>
</p>
