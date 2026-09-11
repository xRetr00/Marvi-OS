# Marvi OS

![Marvi OS — Goddess of Wisdom, Voice & Vision](assets/marvi-os-banner.png)

<p align="center">
  <strong>A private, always-present assistant for Windows.</strong><br>
  Talk naturally. Stay in flow. Let Marvi remember the rest.
</p>

<p align="center">
  <a href="https://github.com/xRetr00/Marvi-OS/releases/latest">Download Marvi OS</a>
  ·
  <a href="#meet-marvi">Meet Marvi</a>
  ·
  <a href="#your-space-your-rules">Privacy & control</a>
  ·
  <a href="LICENSE">MIT License</a>
</p>

---

## Meet Marvi

Marvi OS is a voice-first personal assistant that lives on your Windows desktop—not in another browser tab. Call her with a wake phrase, speak normally, interrupt whenever you need to, and return to what you were doing.

Wake launches preserve the desktop application path when running from a development checkout, so calling Marvi opens the assistant instead of Electron's default screen.

Most of the time, Marvi is a small quiet line at the top edge of your screen. The Dynamic Island becomes a floating capsule only when there is something worth hearing, approving, or acting on. A full control center is there when you want to chat, inspect memory, connect services, manage your room, or tune how Marvi behaves.

Marvi is designed to become more useful without becoming more intrusive. She learns your preferences, remembers what matters, notices meaningful changes, and understands that silence is often the right answer.

## An assistant that feels present

### Talk without managing the conversation

Start hands-free with your own wake phrase. Marvi listens and responds in real time, keeps hearing you while she speaks, and stops when you interrupt. The background wake listener opens no console window; its tray M is blue while listening, green when it hears Marvi, and red if the listener needs attention. Choose how she sounds, tune recognition for your language and hardware, or create a personal voice.

### Voice first. Chat when the work needs room.

Move naturally between spoken conversation and a rich typed workspace. Chat supports long-running threads, branching, files, images, dictation, sources, structured results, and read-aloud—without turning Marvi into a traditional chat app.

### Hand it off and keep talking

Ask for something that takes many steps and Marvi gives it to one of her sub-agents — **Harvi** for code, **Jarvi** for desktop apps, **Talos** for the browser (still under qualification) — and stays in the conversation with you. When the work is done she tells you what happened; if a sub-agent needs your go-ahead to send, delete or overwrite something, she asks, and so does the Island. Letting Harvi change code needs your yes once per job. Claude Code and Codex are still there when you ask for them by name.

### Reach her from your phone

Link a Telegram bot and message Marvi from anywhere. It is the same Marvi, with the same memory, tools and approvals: sensitive actions arrive as Approve and Deny buttons, voice notes are transcribed on your own computer, and each conversation also appears in Chat. The bot answers only the account you link and needs no public address. When she has something to say and nobody is in the room, she can text you instead, and scheduled jobs can deliver their results to Telegram.

### Memory you can actually see

Marvi Cortex turns useful moments into durable context: names, preferences, relationships, recurring patterns, and things you asked her not to forget. Explore those memories as a living graph, trace where each fact came from, correct what is wrong, import knowledge from another assistant, or erase it.

### Awareness beyond the screen

With Smart Room connected, Marvi can understand presence, room conditions, devices, gestures, and familiar faces without sending raw camera footage into the assistant. Ask what is happening, control the room, or let meaningful events surface quietly through the Island.

### The services and tools you already use

Connect accounts such as Gmail, Google Calendar, Slack, Notion, GitHub, and Google Drive. Add skills, plugins, and MCP tools to teach Marvi new kinds of work. Search the web, work with files, use a browser, run scheduled tasks, and bring your own model provider—local or cloud.

### Proactive, not noisy

Marvi can notice an event, remember it, surface it later, or act when the moment is right. Quiet hours, presence, cooldowns, and daily limits keep background intelligence from becoming background chatter. Every autonomous decision has a visible reason.

## Built around your day

- **Dynamic Island** — an ambient, glanceable surface for listening, speaking, proactive announcements, notifications, and approvals. A transparent host and line-to-capsule reveal keep announcements compact; they stay readable briefly, then collapse to a hover-recallable themed orb.
- **Control center** — one place for Voice, Chat, Vision, Room, Activity, Cortex, capabilities, and preferences, with visible model health, a perspective-lit 3D Voice orb, and self-refreshing room devices.
- **Desktop companion** — an optional lightweight character that mirrors Marvi's live state without getting in the way.
- **Marvi Cortex** — inspectable memory, identity, relationships, reflections, and autonomous decisions.
- **Connected world** — accounts, tools, skills, plugins, room devices, and editable scheduled jobs working through one assistant.
- **Personal expression** — choose the theme, typography, window style, Island placement, speech recognition, and voice.

## Your space, your rules

Always-on access should never mean giving up control.

Raw microphone and camera streams stay on your machine. Camera processing belongs to your local room system, and connected content is treated as information—not as an instruction Marvi is allowed to obey. When you choose a cloud model, only the text and context needed for that request are sent to that provider.

You decide how actions work:

- **Confirm mode** asks for approval before sensitive actions. Approval is tied to the exact action Marvi proposed.
- **YOLO mode** removes approval prompts when you explicitly want full autonomy, while validation and local activity history remain active.

Marvi also gives you direct control over the folders tools may access, the services that can connect, what gets remembered, when proactive speech is allowed, and whether the microphone or camera is available. Wake-word recovery is visible and user-controlled: it retries a crashed listener by default, while Settings can turn recovery off or stop the listener completely. Credentials stay out of model conversations, and account sign-in happens through the provider's own authorization page.

## Make Marvi yours

Marvi's personality lives in a plain, editable soul file. Your standing preferences live separately, so you can shape who Marvi is without mixing that identity with everything she learns about you.

Use the models you prefer. Keep thinking local, connect a hosted provider, or give different jobs to different models. Add capabilities over time without rebuilding your assistant around a single company or ecosystem.

## Get Marvi OS

Marvi OS is built for Windows and is under active development.

1. Open the [latest release](https://github.com/xRetr00/Marvi-OS/releases/latest).
2. Download and run `marvi-bootstrap.exe`.
3. Follow the guided setup to choose your hardware, connect a model provider, and add the capabilities you want.

You can begin with Chat and local tools using only a model provider. Voice, vision, browser automation, and additional capabilities can be added when you are ready. Downloads are verified and resumable, unchanged dependencies are reused after a verified install, and failed updates preserve the last working installation.

Installed builds can update from **About → Updates** or from a terminal with
`marvi update`. Use `marvi update --check` to inspect the selected release or
nightly channel without applying it.

## The idea behind Marvi

In development: a visible Chromium workspace with saved profiles, tabs, private
login handoff, pause/resume, downloads and Browser/Island controls. The implementation
is under qualification; it is not yet release-qualified. OBS login/resume works,
but OBS required another login after closing and reopening its profile. Read the
[current architecture review](docs/BROWSER-ARCHITECTURE-REVIEW.md) and
[browser delivery plan](docs/phases/14-browser-computer-use.md). The user reported
browser acceptance on 2026-09-09; computer use now has a separate
[Cua Driver integration](docs/phases/15-computer-use.md).

The desktop now hosts its agent-controlled browser in an isolated Electron
WebContentsView, with Playwright driving the same visible tabs. Chrome cookie
JSON and password CSV imports are available for closed profiles; imported
passwords are encrypted locally and filled only through private user input.
Historical automated qualification limits are recorded in the phase document;
see the [Hermes Desktop v0.21.0 review](docs/HERMES-DESKTOP-BROWSER-REVIEW.md).

For computer use, run `marvi setup`, install **Computer use (Cua Driver)**,
enable **Computer use and app control** under capabilities, and restart Marvi.
App discovery, launch, inspection, window management and input use the local
driver. In conversation Marvi hands multi-step desktop work to Jarvi and keeps
talking; Dynamic Island shows **Jarvi is using the computer** and provides Stop,
Private input and Resume. Browser tasks retain the embedded Playwright browser.
Targeted computer actions display Cua's separate agent pointer with a **Marvi**
badge. It fades when idle and is removed on Stop or Private input. Foreground
input may still use your normal mouse pointer.
Computer activity updates on state changes. Timed-out actions retire their old
worker before private input can start; uncertain outcomes are shown explicitly.
Native app-control and recovery checks pass; live voice-to-Island visual
acceptance is still tracked in the [computer-use phase](docs/phases/15-computer-use.md).

The best assistant is not the one demanding the most attention. It is the one that is there when needed, stays quiet when not, remembers the right things, and earns the trust required to act.

Marvi OS is an attempt to build exactly that: one private, expressive presence for your conversations, computer, connected life, and physical space.

---

<p align="center">
  <strong>Voice. Vision. Memory. Action.</strong><br>
  Your computer should know how to help without getting in your way.
</p>
