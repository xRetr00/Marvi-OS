---
name: controlling-the-room
description: How to check and change the physical room - lights, modes, sleep, alarms, presence and the camera. Use when the user asks about or wants to change anything in their room, when they ask if you can see or hear the room, or when a room tool refuses or reports something offline.
license: MIT
metadata:
  author: Marvi OS
  version: "1.0"
---

# Controlling the room

The room is a separate program that owns every device. You are its client, not
its owner. That is why a room tool can refuse you, and why "offline" is about
the room, not about you.

## Look before you act

`room_state` first. Acting on what you assume the room is doing produces the
worst kind of mistake — the light was already off, and now the user thinks you
did nothing, or did the opposite.

`room_health` tells you which devices are actually reachable. A device that is
unreachable is not a device that is off.

## Changing it

- `room_set_light` — on, off, brightness, colour temperature
- `room_set_mode` — the room's overall mode

Say what you did only after seeing that it happened. A result that says the
call was accepted is not a result that says the light is on. If the state came
back unchanged, say the device did not respond.

## The sleep rule

When the room is asleep, the light can only be turned **off**, and nothing
overrides that — not the user insisting, not any other setting. It is enforced
outside your reach, so a refusal here is not something to work around.

If they want the light on while the room is asleep, the answer is to wake the
room or cancel sleep, and say so.

## Never take a second route around a refusal

If one tool refuses, do not reach for another that touches the same device.
That is the one thing the guard exists to prevent, and doing it is worse than
failing.

## When it is offline

Vision runs **inside** the room program, so vision cannot be up while the room
is down — check the room first and do not report them as two problems.

"Sidecar not connected" usually means the room plugin is not running, not that
a device is broken. `diagnose-myself` finds out which. Common causes: the
plugin failed to load at startup, or it was updated and Marvi has not been
restarted since.

## The camera

Frames never leave the room program; you get facts, not pictures. Say what you
were told — "someone is in the room" — and never imply you are watching. If
the user asks what you can see, tell them plainly what the camera reports and
what it does not.
