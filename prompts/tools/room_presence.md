<!--
name: "Tool: room_presence"
description: "Who is in the room, weighing sensors that disagree."
-->
Who is in the room, weighing sensors that disagree. This is the tool for who is there --
not room_state's presence field, which is one sensor's opinion. It says whether the
sensors agreed: when the answer is unknown, say unknown rather than rounding it to yes
or no. A sensor with no reading is silent, not reporting an empty room.
