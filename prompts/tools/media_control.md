<!--
name: "Tool: media_control"
description: "Play, pause, skip, or change the volume."
-->
Press the keyboard's media keys -- play_pause, next, previous, stop, mute, volume_up,
volume_down -- or set the volume outright with action volume_set and level 0 to 100. Use
it for "pause the music", "skip this", "turn it down", "set the volume to thirty": it
works on whatever player is active (Spotify, a browser tab, the system) and is instant,
so never hand this to a sub-agent or the computer tools. One up or down step is two
percent; for anything relative read media_status first and set the level you want. It
cannot tell you what is playing.
