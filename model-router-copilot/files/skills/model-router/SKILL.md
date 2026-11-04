---
name: model-router
description: Turn the Model router on or off, show its status, reset its stats, show or change the model used for a size (tiny, everyday, large, hardest), or list the usable models by size. Use when the user types /model-router on|off|status|reset, /model-router model, /model-router model <size> <model-id>, or /model-router models.
---

Run exactly one shell command and show its output to the user verbatim, with nothing added:

    @PY@ -I "@JR@/router_copilot.py" <on|off|status|reset|model [<size> <model-id> [--label "Name"] [--effort low|medium|high|none] [--policy required|preferred]]|model reset|models>

Pass the user's arguments through unchanged; default to `status`. `model` alone shows the current table, `models`
lists the models the account can use, grouped by the size they fit. Do not do anything else.
