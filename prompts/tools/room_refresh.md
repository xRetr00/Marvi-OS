<!--
name: "Tool: room_refresh"
description: "Reconnect room devices and refresh their state."
-->
Reconnect room devices and refresh their state. Use it after room_health shows something
unreachable, before telling the user a device is broken. It is a retry, not a fix -- if
it comes back unreachable again, say so.
