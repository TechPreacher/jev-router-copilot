#!/usr/bin/env python3
"""Copilot CLI status line: one line with the router state and the last routing decision.

Configure in ~/.copilot/settings.json (install.sh prints the exact snippet; it does not write it):
    "statusLine": {"type": "command", "command": "python3 -I \"<dir>/jev_statusline.py\""}
Copilot passes the session status as JSON on stdin. It is ignored here, so the script never waits on stdin.
Reads state.json and the last line of decisions.log only. Fail-open: any error prints "Jev ?".
"""
import json
import os
import sys

for _stream in (sys.stdout, sys.stderr):  # the arrow in "Jev → large" must survive a Windows console code page
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

HOME = os.environ.get("JEV_ROUTER_HOME") or os.path.dirname(os.path.abspath(__file__))
SIZES = ("tiny", "everyday", "large", "hardest")
KEPT = {"self_unsure": "kept (unsure)", "self_followup": "kept (follow-up)",
        "skipped_private": "kept (secret)", "self_error": "kept (Jev error)"}


def router_on():
    try:
        with open(os.path.join(HOME, "state.json"), encoding="utf-8") as f:
            return bool(json.load(f).get("enabled"))
    except FileNotFoundError:
        return False


def last_decision():
    """The last decisions.log entry as a dict, or None when the log is missing or empty."""
    try:
        with open(os.path.join(HOME, "decisions.log"), "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4096))  # the last lines are short, so 4 KB is plenty
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
    except FileNotFoundError:
        return None
    return json.loads(lines[-1].decode("utf-8")) if lines else None


def render():
    if not router_on():
        return "Jev OFF"
    rec = last_decision()
    if rec is None:
        return "Jev ON · no decisions yet"
    route = rec.get("route")
    if route in SIZES:
        pct = f" {round(float(rec['p']) * 100)}%" if rec.get("p") is not None else ""
        return f"Jev ON · {route}{pct}"
    return f"Jev ON · {KEPT.get(route, 'kept (' + str(route) + ')')}"


def main():
    try:
        line = render()
    except Exception:
        line = "Jev ?"
    print(line)


if __name__ == "__main__":
    main()
