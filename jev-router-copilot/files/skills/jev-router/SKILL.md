---
name: jev-router
description: Turn the Jev model router on or off, show its status, reset its stats, or show or change the model used for a size (tiny, everyday, large, hardest). Use when the user types /jev-router on|off|status|reset, /jev-router model, or /jev-router model <size> <model-id>.
---

Run exactly one shell command and show its output to the user verbatim, with nothing added:

    python3 -I "@JR@/jev_copilot.py" <on|off|status|reset|model [<size> <model-id> [--label "Name"] [--effort low|medium|high|none] [--policy required|preferred]]|model reset|models>

Pass the user's arguments through unchanged; default to `status`. `model` alone shows the current table, `models`
lists the model IDs this Copilot CLI knows. Do not do anything else.
