<!--
name: "System Prompt: Memory Import Pack"
description: "Groups imported facts into one batch for review."
-->
Write out everything you know about me as a single JSON file I can import into
another assistant. Reply with ONLY the JSON, no commentary, in this format:

{
  "format": "marvi-memory-pack/v1",
  "subject": {"display_name": "...", "preferred_name": "...", "aliases": ["..."]},
  "entries": [
    {
      "kind": "fact | preference | goal | instruction",
      "category": "identity | work | health | projects | ... (your choice)",
      "text": "One complete sentence, third person, about me.",
      "stable": true,
      "sensitivity": "normal | personal | sensitive"
    }
  ]
}

Rules:
- One fact per entry. Write each as a full sentence that makes sense on its own.
- Include preferences about how I like to be talked to, my work, my projects,
  my hardware, and anything standing you have been told to do or avoid.
- NEVER include passwords, API keys, tokens, security answers, card or bank
  numbers, or national ID numbers. Leave them out entirely.
- Mark anything medical, financial or legal as "sensitive".
- Do not invent anything. If you are unsure, leave it out.
