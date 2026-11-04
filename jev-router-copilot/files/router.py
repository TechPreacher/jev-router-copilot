#!/usr/bin/env python3
"""Jev model router for Claude Code.

Hook mode (UserPromptSubmit):  router.py hook   < hook JSON on stdin
CLI mode:                      router.py on | off | status | reset | azure-token

The hook must never block or slow a message: every failure path exits 0 with no output,
and the Jev call has a hard timeout. Typing exactly "jev router on|off|status" in Claude
Code is handled by the hook itself (the message is not sent to the model).

Backends: TypeSafe's hosted Jev (default, TYPESAFE_API_KEY) or a Microsoft Decision-1 deployment in
Azure AI Foundry, used when JEV_AZURE_ENDPOINT and JEV_AZURE_DEPLOYMENT are set (environment or Keychain;
both are treated as secrets). Azure auth is an Entra bearer token from `az account get-access-token`,
cached next to state.json, or an api-key header when JEV_AZURE_API_KEY is set. The hook never waits for
`az`: it uses the cached token and refreshes it in a detached background process.
"""
import fcntl
import json
import os
import re
import shutil
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
AZURE_SCOPE = "https://ai.azure.com/.default"  # override with JEV_AZURE_SCOPE
AZURE_TOKEN_FILE = os.path.join(HOME, "azure-token.json")
AZURE_REFRESH_S = 600  # refresh in the background when the cached token has less than this left
AZURE_MIN_LEFT_S = 60  # a token this close to expiry is not used
AZURE_FETCH_TIMEOUT_S = 40  # az CLI, outside the hook only
HOOK_MODE = False  # set by hook() and by the Copilot adapter: never wait for az, fail open instead
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


def backend_text():
    """One line naming the backend, never its endpoint or deployment (they are treated as secrets)."""
    kind, _ = backend()
    if kind == "azure":
        return "Microsoft Decision-1 in Azure AI Foundry (JEV_AZURE_ENDPOINT / JEV_AZURE_DEPLOYMENT)"
    return f"TypeSafe Jev ({MODEL})"


def status_text(s):
    cost = s["input_tokens"] * USD_PER_INPUT_TOKEN
    c = s.get("counts", {})
    lines = [f"Jev router: {'ON' if s['enabled'] else 'OFF'}" + (f" (stats since {s['since']})" if s.get("since") else "")]
    lines.append(f"  backend: {backend_text()}")
    for size, (agent, model) in SIZES.items():
        lines.append(f"  {size:<9} -> {agent:<13} {model:<18} {c.get(size, 0)} msg")
    lines.append(f"  kept by main model: unsure {c.get('self_unsure', 0)}, short reply {c.get('self_followup', 0)}, "
                 f"skipped (secret-looking) {c.get('skipped_private', 0)}, Jev error/slow {c.get('self_error', 0)}")
    lines.append(f"  Jev: {s['jev_calls']} calls, {s['input_tokens']} input tokens, ${cost:.6f} total "
                 f"(at TypeSafe's list price; Azure bills the deployment)")
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
AZURE_NAMES = ("JEV_AZURE_ENDPOINT", "JEV_AZURE_DEPLOYMENT", "JEV_AZURE_API_KEY")


def secret(name):
    """A value from the environment, else from the macOS Keychain item with that service name.

    The desktop app launches hooks without the user's shell environment, so the env var set in
    fish/zsh is absent there. Store once with:
        security add-generic-password -U -a "$USER" -s <NAME> -w
    (On Windows the Copilot adapter loads the same names from the Credential Manager first.)
    """
    value = os.environ.get(name)
    if value:
        return value
    try:
        out = subprocess.run(["/usr/bin/security", "find-generic-password", "-w", "-s", name],
                             capture_output=True, text=True, timeout=1.0)
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = out.stdout.strip() if out.returncode == 0 else ""
    return value or None


def get_key():
    """TYPESAFE_API_KEY from the environment, else from the macOS Keychain."""
    return secret(KEYCHAIN_SERVICE)


def azure_url(endpoint):
    """The Decision-1 request URL for a Foundry resource endpoint, with or without the provider path."""
    base = endpoint.strip().rstrip("/")
    if base.endswith("/v1/systemone"):
        base = base[:-len("/v1/systemone")]
    if not base.endswith("/providers/microsoft"):
        base += "/providers/microsoft"
    return base + "/v1/systemone"


def backend():
    """("azure", {"url", "deployment"}) when JEV_AZURE_ENDPOINT and JEV_AZURE_DEPLOYMENT are set, else
    ("typesafe", None). JEV_BACKEND=typesafe forces TypeSafe even when the Azure values exist."""
    if os.environ.get("JEV_BACKEND", "").lower() == "typesafe":
        return "typesafe", None
    endpoint = secret("JEV_AZURE_ENDPOINT")
    deployment = secret("JEV_AZURE_DEPLOYMENT") if endpoint else None
    if endpoint and deployment:
        return "azure", {"url": azure_url(endpoint), "deployment": deployment}
    return "typesafe", None


def read_token_cache():
    try:
        with open(AZURE_TOKEN_FILE, encoding="utf-8") as f:
            data = json.load(f)
        token, expires_on = data.get("token"), float(data.get("expires_on", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return None, 0.0
    return (token or None), expires_on


def write_token_cache(token, expires_on):
    """Owner-only file, written atomically. The token is a secret; so is this file."""
    os.makedirs(HOME, exist_ok=True)
    tmp = AZURE_TOKEN_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"token": token, "expires_on": expires_on}, f)
    os.replace(tmp, AZURE_TOKEN_FILE)


def fetch_azure_token():
    """Run `az account get-access-token` (blocking), cache the token, return it. Raises on failure."""
    az = shutil.which("az")
    if not az:
        raise RuntimeError("az CLI not found on PATH (needed for the Azure token; or set JEV_AZURE_API_KEY)")
    scope = os.environ.get("JEV_AZURE_SCOPE") or AZURE_SCOPE
    try:
        out = subprocess.run([az, "account", "get-access-token", "--scope", scope, "-o", "json"],
                             capture_output=True, text=True, timeout=AZURE_FETCH_TIMEOUT_S)
        if out.returncode != 0:
            reason = (out.stderr or out.stdout).strip().splitlines()
            raise RuntimeError("az account get-access-token failed: " + (reason[-1] if reason else "no output"))
        data = json.loads(out.stdout)
        token = data["accessToken"]
        expires_on = float(data.get("expires_on") or 0)
        if not expires_on:  # older az prints only the local-time string
            expires_on = time.mktime(time.strptime(data["expiresOn"][:19], "%Y-%m-%d %H:%M:%S"))
    finally:
        try:
            os.remove(AZURE_TOKEN_FILE + ".refresh")
        except OSError:
            pass
    write_token_cache(token, expires_on)
    return token


def refresh_token_in_background():
    """Start `router.py azure-token` detached, at most one at a time. Never raises."""
    marker = AZURE_TOKEN_FILE + ".refresh"
    try:
        if os.path.exists(marker) and time.time() - os.path.getmtime(marker) < AZURE_FETCH_TIMEOUT_S + 20:
            return
        os.makedirs(HOME, exist_ok=True)
        with open(marker, "w"):
            pass
        kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                  "close_fds": True}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), "azure-token"], **kwargs)
    except Exception:
        pass


def azure_token():
    """The cached Entra token. In hook mode a missing or stale token starts a background refresh and
    raises, so the message goes through unrouted once; outside the hook, az is called and waited for."""
    token, expires_on = read_token_cache()
    left = expires_on - time.time()
    if token and left > AZURE_MIN_LEFT_S:
        if left < AZURE_REFRESH_S:
            refresh_token_in_background()
        return token
    if HOOK_MODE:
        refresh_token_in_background()
        raise RuntimeError("Azure token not cached yet (refreshing in the background; try again)")
    return fetch_azure_token()


def azure_auth():
    """The auth header for the Azure call: api-key when JEV_AZURE_API_KEY is set, else a bearer token
    (JEV_AZURE_TOKEN in the environment, else the az CLI cache)."""
    api_key = secret("JEV_AZURE_API_KEY")
    if api_key:
        return {"api-key": api_key}
    token = os.environ.get("JEV_AZURE_TOKEN") or azure_token()
    return {"Authorization": f"Bearer {token}"}


def ask_jev(prompt):
    kind, azure = backend()
    if kind == "azure":
        url, model, headers = azure["url"], azure["deployment"], azure_auth()
    else:
        key = get_key()
        if not key:
            raise RuntimeError("TYPESAFE_API_KEY not set (env or Keychain)")
        url, model, headers = URL, MODEL, {"Authorization": f"Bearer {key}"}
    body = {"model": model, "state": {"message": prompt[:MAX_CHARS]}, "questions": QUESTION}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={**headers, "Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        data = json.load(resp)
    ms = (time.perf_counter() - t0) * 1000
    ans = data["answers"]["size"]
    return ans["choice"], ans["probabilities"][ans["choice"]], ans.get("confidence"), \
        data.get("usage", {}).get("input_tokens", 0), ms, kind


def decide(prompt, has_history):
    """Returns (route, info). route is a size name or a self_* / skipped_* reason."""
    if SECRETS.search(prompt):
        return "skipped_private", {}
    if is_followup(prompt, has_history):
        return "self_followup", {}
    try:
        size, p, conf, tokens, ms, kind = ask_jev(prompt)
    except Exception as e:  # slow, offline, bad key, schema change: carry on as if absent
        return "self_error", {"error": f"{type(e).__name__}: {e}"[:200]}
    info = {"size": size, "p": p, "confidence": conf, "tokens": tokens, "ms": ms, "backend": kind}
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
    global HOOK_MODE
    HOOK_MODE = True
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
        if arg == "on" and backend()[0] == "azure" and not secret("JEV_AZURE_API_KEY"):
            try:  # warm the token cache so the first routed message does not go through unrouted
                azure_token()
            except Exception as e:
                print(f"  Azure token: {e}")
    elif arg == "azure-token":
        try:
            fetch_azure_token()
            _, expires_on = read_token_cache()
            print("Azure token cached until " + time.strftime("%Y-%m-%d %H:%M", time.localtime(expires_on)))
        except Exception as e:
            print(f"azure-token: {e}", file=sys.stderr)
            sys.exit(1)
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
