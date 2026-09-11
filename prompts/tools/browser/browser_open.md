<!--
name: "Tool: browser_open"
description: "Open a visible saved browser profile for a task the user asked for."
-->
Open a visible saved browser profile for a task the user asked for. Returns a receipt,
not a browser: read browser_status until the state is ready before acting. One browser
per profile -- if it refuses, it names the existing session, so use that one or close
it. For a question the web can answer, search instead.
