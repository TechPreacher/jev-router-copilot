---
name: jev-router
description: Turn the Jev model router on or off, show its status, reset its stats, show or change the model used for a size (tiny, everyday, large, hardest), or list the usable models by size. Use when the user types /jev-router on|off|status|reset, /jev-router model, /jev-router model <size> <model-id>, or /jev-router models.
---

Run exactly one shell command and show its output to the user verbatim, with nothing added:

    @PY@ -I "@JR@/jev_copilot.py" <on|off|status|reset|model [<size> <model-id> [--label "Name"] [--effort low|medium|high|none] [--policy required|preferred]]|model reset|models>

Pass the user's arguments through unchanged; default to `status`. `model` alone shows the current table, `models`
lists the models the account can use, grouped by the size they fit. Do not do anything else.
