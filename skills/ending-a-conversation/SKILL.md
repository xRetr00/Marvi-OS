---
name: ending-a-conversation
description: How to tell that a spoken conversation is over and close it properly. Use when the user says goodbye, thanks, that's all, you can go, stop, later, or otherwise signals they are finished - and when you are unsure whether a pause or the word "stop" means the conversation has ended. Not when "stop" interrupts you mid-sentence, and not when it names something to stop - a timer, music, a light.
license: MIT
metadata:
  author: Marvi OS
  version: "1.0"
---

# Ending a conversation

A voice session stays open until something closes it. The wake word starts one;
it is not a password on every sentence. Between those two points every turn
reaches you, so nothing needs to end a conversation except the user meaning to.

## Deciding it is over

Judge the meaning, not the words.

**Over:** "that's all", "thanks, bye", "you can go", "I'll handle it from
here", "talk later", "goodnight".

**Not over:**

- "stop" in the middle of a sentence about something else — that is a word in
  a sentence, not a dismissal.
- "stop" while you are speaking — that is an interruption. Stop talking, stay
  in the room, listen.
- A pause. Silence is thinking. Never end a conversation because nobody said
  anything.
- "okay" or "thanks" mid-task. That is acknowledgement, not farewell.

When it is genuinely ambiguous, finish your sentence and wait. Ending too
early costs the user a whole re-entry; ending too late costs a few seconds.

## Doing it

1. Say a short farewell first — a few words, not a summary of the session.
2. Then call `end_conversation`.

In that order. The tool closes the session, and anything you were going to say
after it is not said.

## What "ended" has to mean

The user must actually be out. If the farewell plays and they are still in the
room with the microphone live, the conversation did not end — it went quiet,
which is worse than not ending at all, because they cannot tell whether you
are still listening.

If you called `end_conversation` and the session is plainly still open, say so
rather than pretending. That is a fault worth reporting, and
`diagnose-myself` covers finding it.

## Before you go

If something is still in flight — a confirmation waiting, a tool you said you
would run — say what will happen to it. Do not leave an action half-announced.
