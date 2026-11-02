#!/usr/bin/env python3
"""Jev model router for Claude Code.

Hook mode (UserPromptSubmit):  router.py hook   < hook JSON on stdin
CLI mode:                      router.py on | off | status | reset

The hook must never block or slow a message: every failure path exits 0 with no output,
and the Jev call has a hard timeout. Typing exactly "jev router on|off|status" in Claude
Code is handled by the hook itself (the message is not sent to the model).
"""
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager

HOME = os.environ.get("JEV_ROUTER_HOME", os.path.expanduser("~/.claude/jev-router"))
STATE = os.path.join(HOME, "state.json")
LOG = os.path.join(HOME, "decisions.log")

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
TIMEOUT_S = 1.5
USD_PER_INPUT_TOKEN = 0.042 / 1_000_000
MIN_SURE = 0.60
MAX_CHARS = 6000  # long pastes: size from the first part, keeps Jev fast

# size -> (helper agent, model it runs on), smallest to biggest
SIZES = {
    "tiny": ("jev-tiny", "Claude Haiku 5.5"),
    "everyday": ("jev-everyday", "Claude Sonnet 5.5"),
    "large": ("jev-large", "Claude Opus 5.5"),
    "hardest": ("jev-hardest", "Claude Fable 5.1"),
}

QUESTION = {
    "size": {
        "type": "choice",
        "instructions": "What is the smallest AI model size that can do the job in `message` well?",
        "criteria": {
            "tiny": "A lookup, a rename, or a one-line answer",
            "everyday": "A normal email, post, or short document",
            "large": "A multi-step build, research, or a full report",
            "hardest": "Strategy, or a job where a wrong call is expensive",
        },
    }
}

FOLLOWUP_START = re.compile(
    r"^\s*(yes|yeah|yep|yup|no|nope|ok|okay|sure|go ahead|do (it|that|this)|thanks|thank you|"
    r"same|again|continue|go on|perfect|great|nice|agreed|correct|right)\b", re.I)
FOLLOWUP_REF = re.compile(
    r"\b(that|this|it|those|these|them|above|previous|earlier|last one|again|instead|"
    r"shorter|longer|simpler|more|less)\b", re.I)
SECRETS = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|\bpassword\s*[:=]|\bapi[_ -]?key\s*[:=]|"
    r"\bgh[pousr]_[A-Za-z0-9]{20,})", re.I)

EMPTY = {"enabled": False, "counts": {}, "jev_calls": 0, "input_tokens": 0, "errors": 0,
         "last_error": None, "since": None}


@contextmanager
def locked_state():
    os.makedirs(HOME, exist_ok=True)
    with open(STATE + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(STATE) as f:
                state = {**EMPTY, **json.load(f)}
        except (OSError, ValueError):
            state = dict(EMPTY, counts={})
        yield state
        tmp = STATE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, STATE)


def read_state():
    try:
        with open(STATE) as f:
            return {**EMPTY, **json.load(f)}
    except (OSError, ValueError):
        return dict(EMPTY, counts={})


def status_text(s):
    cost = s["input_tokens"] * USD_PER_INPUT_TOKEN
    c = s.get("counts", {})
    lines = [f"Jev router: {'ON' if s['enabled'] else 'OFF'}" + (f" (stats since {s['since']})" if s.get("since") else "")]
    for size, (agent, model) in SIZES.items():
        lines.append(f"  {size:<9} -> {agent:<13} {model:<18} {c.get(size, 0)} msg")
    lines.append(f"  kept by main model: unsure {c.get('self_unsure', 0)}, short reply {c.get('self_followup', 0)}, "
                 f"skipped (secret-looking) {c.get('skipped_private', 0)}, Jev error/slow {c.get('self_error', 0)}")
    lines.append(f"  Jev: {s['jev_calls']} calls, {s['input_tokens']} input tokens, ${cost:.6f} total")
    if s.get("last_error"):
        lines.append(f"  last error: {s['last_error']}")
    return "\n".join(lines)


def set_enabled(on):
    with locked_state() as s:
        s["enabled"] = on
        if on and not s.get("since"):
            s["since"] = time.strftime("%Y-%m-%d %H:%M")
        return status_text(s)


def is_followup(prompt, has_history):
    if not has_history:
        return False
    words = len(prompt.split())
    if words <= 12 and FOLLOWUP_START.search(prompt):
        return True
    return words <= 12 and bool(FOLLOWUP_REF.search(prompt))


KEYCHAIN_SERVICE = "TYPESAFE_API_KEY"


def get_key():
    """TYPESAFE_API_KEY from the environment, else from the macOS Keychain.

    The desktop app launches hooks without the user's shell environment, so the env var set in
    fish/zsh is absent there. Store once with:
        security add-generic-password -U -a "$USER" -s TYPESAFE_API_KEY -w
    """
    key = os.environ.get("TYPESAFE_API_KEY")
    if key:
        return key
    try:
        out = subprocess.run(["/usr/bin/security", "find-generic-password", "-w", "-s", KEYCHAIN_SERVICE],
                             capture_output=True, text=True, timeout=1.0)
    except (OSError, subprocess.TimeoutExpired):
        return None
    key = out.stdout.strip() if out.returncode == 0 else ""
    return key or None


def ask_jev(prompt):
    key = get_key()
    if not key:
        raise RuntimeError("TYPESAFE_API_KEY not set (env or Keychain)")
    body = {"model": MODEL, "state": {"message": prompt[:MAX_CHARS]}, "questions": QUESTION}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        data = json.load(resp)
    ms = (time.perf_counter() - t0) * 1000
    ans = data["answers"]["size"]
    return ans["choice"], ans["probabilities"][ans["choice"]], ans.get("confidence"), \
        data.get("usage", {}).get("input_tokens", 0), ms


def decide(prompt, has_history):
    """Returns (route, info). route is a size name or a self_* / skipped_* reason."""
    if SECRETS.search(prompt):
        return "skipped_private", {}
    if is_followup(prompt, has_history):
        return "self_followup", {}
    try:
        size, p, conf, tokens, ms = ask_jev(prompt)
    except Exception as e:  # slow, offline, bad key, schema change: carry on as if absent
        return "self_error", {"error": f"{type(e).__name__}: {e}"[:200]}
    info = {"size": size, "p": p, "confidence": conf, "tokens": tokens, "ms": ms}
    return (size if p >= MIN_SURE and size in SIZES else "self_unsure"), info


def record(route, info, prompt):
    with locked_state() as s:
        s["counts"][route] = s["counts"].get(route, 0) + 1
        if "tokens" in info:
            s["jev_calls"] += 1
            s["input_tokens"] += info["tokens"]
        if "error" in info:
            s["errors"] += 1
            s["last_error"] = time.strftime("%H:%M ") + info["error"]
    with open(LOG, "a") as f:
        f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "route": route,
                            "chars": len(prompt), **info}) + "\n")


def hook():
    payload = json.load(sys.stdin)
    prompt = (payload.get("prompt") or "").strip()

    cmd = prompt.lower().rstrip(".!")
    if cmd in ("jev router on", "jev router off", "jev router status"):
        text = status_text(read_state()) if cmd.endswith("status") else set_enabled(cmd.endswith("on"))
        print(json.dumps({"decision": "block", "reason": text}))
        return

    if not prompt or prompt.startswith(("/", "!")) or not read_state()["enabled"]:
        return

    tp = payload.get("transcript_path") or ""
    has_history = bool(tp) and os.path.exists(tp) and os.path.getsize(tp) > 0
    route, info = decide(prompt, has_history)
    record(route, info, prompt)
    if route not in SIZES:
        return

    agent, model = SIZES[route]
    ctx = (f"[jev-router] Jev sized this message as {route.upper()} (p={info['p']:.2f}). "
           f"Delegate the job to the `{agent}` subagent (Agent tool, subagent_type \"{agent}\", runs on {model}). "
           f"Give it a self-contained prompt: the user's message plus any conversation context it needs. "
           f"Relay its result to the user as-is, keeping its final 'Done by' line. Don't redo the work yourself. "
           f"If the subagent is unavailable or fails, do the job yourself and say the router fell back.")
    print(json.dumps({
        "systemMessage": f"Jev → {route} ({info['p']:.0%}) → {agent}",
        "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx},
    }))


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "status"
    if arg == "hook":
        try:
            hook()
        except Exception:
            pass  # never block a message
        sys.exit(0)
    if arg in ("on", "off"):
        print(set_enabled(arg == "on"))
    elif arg == "reset":
        with locked_state() as s:
            enabled = s["enabled"]
            s.clear()
            s.update(dict(EMPTY, counts={}, enabled=enabled))
        print(status_text(read_state()))
    else:
        print(status_text(read_state()))


if __name__ == "__main__":
    main()
