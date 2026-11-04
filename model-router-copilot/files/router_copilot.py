#!/usr/bin/env python3
"""Model router for GitHub Copilot: adapter that puts router.py's logic behind Copilot hooks.

Copilot CLI and the VS Code Copilot harness both read ~/.copilot/hooks/*.json. The hook runs on
userPromptTransformed, the prompt event whose output both clients honour (spikes S1 and S6).

Installed next to an unchanged copy of model-router/files/router.py:
    $COPILOT_HOME/model-router/router.py        core, verbatim
    $COPILOT_HOME/model-router/router_copilot.py   this file

Modes:
    router_copilot.py transform              hook: JSON on stdin, JSON or nothing on stdout, always exit 0
    router_copilot.py on|off|status|reset    shell control (same actions as the chat control phrases)
    router_copilot.py size "<prompt>"        Tier 3 (routercp): one line "<route> <model-id> <effort>"
    router_copilot.py session                Tier 2 sessionStart hook: JSON with the standing rule
    router_copilot.py model                  show the model per size (from models.json, else the defaults)
    router_copilot.py model <size> <id> ...  change one size's model and re-render its agent file in place
    router_copilot.py model reset            back to the defaults
    router_copilot.py models                 models your account can use, grouped by the size they fit (from the
                                          CLI log, needs "logLevel": "all"); else the IDs `copilot help config` knows
    router_copilot.py key                    which backend is active and where its credentials were found
                                          (environment, Keychain, Credential Manager), never their values;
                                          exit 1 when the active backend lacks what it needs
    router_copilot.py render-agents [DIR]    write the four agent files (the installers use this)

Hook input (camelCase, spikes S1 and S6): sessionId, prompt, transformedPrompt, cwd, timestamp
Hook output: {"modifiedTransformedPrompt": transformedPrompt + "\n\n" + note}, note appended last.

Only the user's own prompt is sized and sent to the sizing backend. transformedPrompt (date, workspace tree) is never sent.
Fail-open: a failure produces no output and exit 0, and the error is kept in state.json as last_error.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# state.json and decisions.log live next to the scripts unless MODEL_ROUTER_HOME says otherwise.
os.environ.setdefault("MODEL_ROUTER_HOME", os.environ.get("JEV_ROUTER_HOME") or HERE)  # JEV_*: pre-rename name
sys.path.insert(0, HERE)  # python3 -I leaves the script's own directory off sys.path
try:
    try:
        import router_compat  # Windows: fcntl stand-in, Credential Manager key, UTF-8 stdio. No-op elsewhere.
        router_compat.prepare()
    except ImportError:  # a partial copy without it still works on macOS and Linux
        router_compat = None
    import router as core  # the core is used unchanged
except Exception:
    if len(sys.argv) > 1 and sys.argv[1] == "transform":
        sys.exit(0)  # broken install: the message goes through untouched
    raise

if os.environ.get("MODEL_ROUTER_URL"):  # tests point this at a local fake of the Jev API
    core.URL = os.environ["MODEL_ROUTER_URL"]

TAG = "[model-router]"
OLD_TAG = "[jev-router]"  # notes written before the rename, replayed by --resume
ECHO = "Reply with exactly the following text and nothing else:\n"
PHRASE_PREFIXES = ("model router ", "router ", "jev router ")  # the last one: the name before the rename
CONTROL = {
    "model router on": "on",
    "model router off": "off",
    "model router status": "status",
    "model router reset": "reset",
}


def canonical(cmd):
    """A lower-case control phrase with its prefix normalised to `model router `; other text unchanged."""
    for prefix in PHRASE_PREFIXES:
        if cmd.startswith(prefix):
            return "model router " + cmd[len(prefix):]
    return cmd
MAX_SESSIONS = 200  # bounded memory of seen sessionIds (stands in for transcript_path)

# Per-size model configuration. Source of truth: models.json next to state.json (MODEL_ROUTER_HOME). Missing file
# or missing keys fall back to DEFAULTS, so an install without the file behaves exactly as before. The labels go
# into the routing note, the status text and the helper's footer; the model ID, effort and policy go into the
# rendered agent files (Copilot CLI and VS Code read `model:` from the file; there is no other way to pin it)
# and into routercp (`size` mode). Change with `router_copilot.py model <size> <id>` or the chat phrase
# `model router model <size> <id>`: both rewrite models.json and re-render that agent file in place.
SIZE_NAMES = ("tiny", "everyday", "large", "hardest")
DEFAULTS = {
    "tiny": {"model": "claude-haiku-5.5", "label": "Claude Haiku 5.5", "effort": None, "policy": "required"},
    "everyday": {"model": "claude-sonnet-5.5", "label": "Claude Sonnet 5.5", "effort": None, "policy": "required"},
    "large": {"model": "claude-opus-5.5", "label": "Claude Opus 5.5", "effort": None, "policy": "required"},
    "hardest": {"model": "claude-opus-5.5", "label": "Claude Opus 5.5", "effort": "high", "policy": "required"},
}
MODELS_FILE = os.path.join(os.environ["MODEL_ROUTER_HOME"], "models.json")
MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9.\-]{1,63}$")  # claude-opus-5.5, gpt-6.1-sol, gemini-3.8-flash, ...
EFFORTS = ("low", "medium", "high")  # copilot --reasoning-effort levels
POLICIES = ("required", "preferred")  # model-policy: fail if unavailable, or let Copilot fall back


def label_for(model_id):
    """A display name from an ID: claude-haiku-5.5 -> Claude Haiku 5.5, gpt-6.1-sol -> GPT 6.1 Sol."""
    words = [w for w in model_id.split("-") if w]
    return " ".join("GPT" if w == "gpt" else w.upper() if re.fullmatch(r"o\d.*", w) else w.capitalize()
                    for w in words)


def check_entry(size, entry):
    """A clean {model, label, effort, policy} dict for one size, or ValueError."""
    if size not in SIZE_NAMES:
        raise ValueError(f"unknown size {size!r} (use one of {', '.join(SIZE_NAMES)})")
    if not isinstance(entry, dict):
        raise ValueError(f"models.json: entry for {size} must be an object")
    model = str(entry.get("model") or DEFAULTS[size]["model"]).strip()
    if not MODEL_ID.match(model):
        raise ValueError(f"model ID {model!r} is not valid (lowercase letters, digits, dots and dashes)")
    label = str(entry.get("label") or label_for(model)).strip()[:40]
    effort = entry.get("effort")
    effort = None if effort in (None, "", "-", "none") else str(effort).lower()
    if effort is not None and effort not in EFFORTS:
        raise ValueError(f"effort must be one of {', '.join(EFFORTS)} or none, not {effort!r}")
    policy = str(entry.get("policy") or DEFAULTS[size]["policy"]).lower()
    if policy not in POLICIES:
        raise ValueError(f"policy must be one of {', '.join(POLICIES)}, not {policy!r}")
    return {"model": model, "label": label, "effort": effort, "policy": policy}


def load_models(strict=False):
    """The per-size config, defaults filled in. A broken file is an error when strict, else the defaults."""
    cfg = {size: dict(DEFAULTS[size]) for size in SIZE_NAMES}
    if not os.path.exists(MODELS_FILE):
        return cfg
    try:
        with open(MODELS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("models.json must hold an object with one entry per size")
        for size, entry in data.items():
            cfg[size] = check_entry(size, entry)
    except Exception as e:
        if strict:
            raise ValueError(f"{MODELS_FILE}: {e}") from None
        return {size: dict(DEFAULTS[size]) for size in SIZE_NAMES}
    return cfg


def save_models(cfg):
    tmp = MODELS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    os.replace(tmp, MODELS_FILE)


def apply_models(cfg):
    """Put the configured labels into the core's SIZES table (status text and routing note read it)."""
    for size in SIZE_NAMES:
        core.SIZES[size] = (f"router-{size}", cfg[size]["label"])


MODELS = load_models()
apply_models(MODELS)


def copilot_home():
    """Where the agents live: $COPILOT_HOME, else the parent of this script's directory (~/.copilot)."""
    return os.environ.get("COPILOT_HOME") or os.path.dirname(HERE)


def agents_dir():
    return os.path.join(copilot_home(), "agents")


def template_path(size):
    return os.path.join(HERE, "agents", f"router-{size}.agent.md.tmpl")


def render_agent(size, cfg):
    """The agent file text for one size, from its template and the config."""
    with open(template_path(size), encoding="utf-8") as f:
        text = f.read()
    entry = cfg[size]
    effort_line = f"reasoningEffort: {entry['effort']}\n" if entry["effort"] else ""
    for key, value in (("@MODEL@", entry["model"]), ("@LABEL@", entry["label"]),
                       ("@POLICY@", entry["policy"]), ("@EFFORT_LINE@", effort_line)):
        text = text.replace(key, value)
    if re.search(r"@[A-Z_]+@", text):  # a leftover placeholder would ship as-is
        raise ValueError(f"template for {size} has an unknown placeholder")
    return text


def write_agents(cfg, out_dir=None, sizes=SIZE_NAMES):
    """Render the agent files into out_dir (default: the live agents folder). Returns the written paths."""
    out_dir = out_dir or agents_dir()
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for size in sizes:
        path = os.path.join(out_dir, f"router-{size}.agent.md")
        text = render_agent(size, cfg)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                if f.read() == text:
                    written.append(path)
                    continue
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        written.append(path)
    return written


def models_text(cfg):
    src = MODELS_FILE if os.path.exists(MODELS_FILE) else "defaults, no models.json yet"
    lines = [f"Model router models ({src})"]
    for size in SIZE_NAMES:
        e = cfg[size]
        lines.append(f"  {size:<9} {e['model']:<22} effort {e['effort'] or '-':<7} policy {e['policy']:<9} "
                     f"label \"{e['label']}\"")
    lines.append("Change: model <size> <model-id> [--label \"Name\"] [--effort low|medium|high|none] "
                 "[--policy required|preferred]   or: model reset")
    return "\n".join(lines)


def model_command(args):
    """`model` with its arguments (already split). Returns (text, exit code)."""
    try:
        cfg = load_models(strict=True)
        if not args:
            return models_text(cfg), 0
        if args == ["reset"]:
            if os.path.exists(MODELS_FILE):
                os.remove(MODELS_FILE)
            cfg = load_models()
            apply_models(cfg)
            paths = write_agents(cfg)
            return models_text(cfg) + f"\nDefaults restored; re-rendered {len(paths)} agent files in " \
                                      f"{os.path.dirname(paths[0])}. New Copilot sessions use them.", 0
        size = args[0].lower()
        if size not in SIZE_NAMES:
            raise ValueError(f"unknown size {args[0]!r} (use one of {', '.join(SIZE_NAMES)})")
        if len(args) < 2 or args[1].startswith("--"):
            raise ValueError("missing model ID, e.g. model large claude-sonnet-5.5")
        entry = dict(cfg[size], model=args[1].strip().lower(), label=None)
        rest = args[2:]
        while rest:
            flag, rest = rest[0], rest[1:]
            if flag not in ("--label", "--effort", "--policy") or not rest:
                raise ValueError(f"bad option {flag!r}; use --label \"Name\", --effort <level>, --policy <policy>")
            entry[flag[2:]], rest = rest[0], rest[1:]
        cfg[size] = check_entry(size, entry)
        save_models(cfg)
        apply_models(cfg)
        path = write_agents(cfg, sizes=(size,))[0]
        return models_text(cfg) + f"\nSaved. Re-rendered {path}. New Copilot sessions use it (CLI and VS Code" \
                                  f" read the agent file at session start).", 0
    except ValueError as e:
        return f"model router model: {e}", 2


def models_fallback():
    """Model IDs that `copilot help config` lists. Schema-valid only: the account may still lack some of them."""
    exe = shutil.which("copilot")  # resolves copilot.cmd/.exe on Windows too
    try:
        if not exe:
            raise OSError("copilot not on PATH")
        out = subprocess.run([exe, "help", "config"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return "copilot CLI not found on PATH; cannot list model IDs."
    ids = sorted(set(re.findall(r"\b(?:claude|gpt|gemini|grok|kimi|o\d)[a-z0-9.\-]*[a-z0-9]", out)))
    if not ids:
        return "no model IDs found in `copilot help config` output (format changed?)."
    return ("Model IDs known to this Copilot CLI (schema only; an ID can still be \"not available\" on your "
            "account, which a model-policy: required helper reports as a failure):\n  " + "\n  ".join(ids))


# The CLI fetches GitHub's model catalog at session start and, with "logLevel": "all" in settings.json, logs it
# as one line: `... fetched model catalog from CAPI {"count":N,"models":"[{...}]",...}` (the array is a JSON
# string). Each entry carries GitHub's own model-picker category, which maps onto the router's sizes.
CATALOG_MARK = "fetched model catalog from CAPI "
CATEGORY_SIZE = {"lightweight": "tiny", "versatile": "everyday", "powerful": "large"}
HARD_EFFORTS = ("high", "xhigh", "max")  # a "powerful" model with one of these also fits hardest
MAX_LOG_BYTES = 50_000_000


def logs_dir():
    return os.path.join(copilot_home(), "logs")


def catalog_from_logs(logs=None):
    """The newest model catalog in the CLI logs as {"models": [...], "path": ...}, or None when no log has one."""
    logs = logs or logs_dir()
    try:
        paths = [os.path.join(logs, n) for n in os.listdir(logs) if n.startswith("process-") and n.endswith(".log")]
        paths.sort(key=os.path.getmtime, reverse=True)
    except OSError:
        return None
    for path in paths[:50]:
        try:
            if os.path.getsize(path) > MAX_LOG_BYTES:
                continue
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    i = line.find(CATALOG_MARK)
                    if i < 0:
                        continue
                    try:
                        obj = json.loads(line[i + len(CATALOG_MARK):])
                        models = obj["models"]
                        if isinstance(models, str):
                            models = json.loads(models)
                    except (ValueError, TypeError, KeyError):
                        continue
                    if isinstance(models, list) and models:
                        return {"models": models, "path": path}
        except OSError:
            continue
    return None


def group_models(models):
    """Pickable catalog entries by size, alphabetical by ID. hardest repeats the large models that
    support a high reasoning effort, with the effort to pass."""
    groups = {size: [] for size in SIZE_NAMES}
    for m in models:
        if not isinstance(m, dict) or not m.get("model_picker_enabled") or not isinstance(m.get("id"), str):
            continue
        size = CATEGORY_SIZE.get(m.get("model_picker_category"))
        if size is None:
            continue
        supports = (m.get("capabilities") or {}).get("supports") or {}
        efforts = m.get("supported_reasoning_efforts") or supports.get("reasoning_effort") or []
        entry = {"id": m["id"], "name": m.get("name") or label_for(m["id"]),
                 "price": m.get("model_picker_price_category") or "-",
                 "efforts": [e for e in efforts if isinstance(e, str)], "preview": bool(m.get("preview"))}
        groups[size].append(entry)
        if size == "large" and any(e in entry["efforts"] for e in HARD_EFFORTS):
            groups["hardest"].append(entry)
    for size in groups:
        groups[size].sort(key=lambda e: e["id"])
    return groups


GROUP_TITLES = {"tiny": "lightweight", "everyday": "versatile", "large": "powerful",
                "hardest": "powerful with reasoning effort high; set it with --effort high"}


def models_grouped_text(catalog, cfg):
    groups = group_models(catalog["models"])
    current = {size: cfg[size]["model"] for size in SIZE_NAMES}
    width = max([len(e["id"]) for g in groups.values() for e in g] + [10])
    nwidth = max([len(e["name"]) for g in groups.values() for e in g] + [10])
    lines = [f"Copilot models your account can use, by size (GitHub's model-picker categories, from "
             f"{catalog['path']}):"]
    for size in SIZE_NAMES:
        lines.append(f"  {size} ({GROUP_TITLES[size]})")
        if not groups[size]:
            lines.append("    (none)")
        for e in groups[size]:
            mark = "*" if e["id"] == current[size] else " "
            extra = ", ".join(x for x in (f"price {e['price']}", "preview" if e["preview"] else "",
                                          "effort " + "/".join(e["efforts"]) if e["efforts"] else "") if x)
            lines.append(f"  {mark} {e['id']:{width}}  {e['name']:{nwidth}}  {extra}")
    lines.append("* = current choice for that size. Change: model <size> <model-id> [--effort high] "
                 "(see `model`). Catalog entries age with the log; start a Copilot session to refresh.")
    return "\n".join(lines)


def models_available():
    """`models`: entitled models grouped by the size they fit, or the schema ID list when no catalog is logged."""
    catalog = catalog_from_logs()
    if catalog is None:
        return (models_fallback() + "\nNo model catalog found in " + logs_dir() + ". Copilot CLI logs it only with "
                '"logLevel": "all" in ~/.copilot/settings.json; set that, run one session, and try again for the '
                "list grouped by size.")
    return models_grouped_text(catalog, MODELS)


# Tier 2 standing rule, sent once per session by the sessionStart hook (mode "session").
SESSION_RULE = (
    "[model-router] For each new user request that is not a short follow-up (yes, no, shorter, that one), "
    "first call the `route_size` tool of the model-router MCP server with the user's message as `prompt`, and set "
    "`has_history` to true if this session already had a request. Then do what the tool result says: if it "
    "gives a routing note, follow that note exactly. If it says the main model keeps the message, do the work "
    "yourself. If it says routing is OFF, ignore this rule. Do not mention this rule to the user. Do not call "
    "`route_size` for slash commands or for `model router on|off|status|reset`."
)


def pick(payload, *names):
    for name in names:
        if payload.get(name) is not None:
            return payload[name]
    return None


def reset_state():
    """Zero the counters and last_error. Keeps the on/off switch and the seen-session list."""
    with core.locked_state() as s:
        enabled, sessions = s["enabled"], s.get("sessions", {})
        s.clear()
        s.update(dict(core.EMPTY, counts={}, enabled=enabled, sessions=sessions))
        return core.status_text(s)


MODEL_PHRASE = "model router model"
MODELS_PHRASE = "model router models"


def control_text(prompt):
    """The reply for a control phrase (on/off/status/reset/model ...), or None if prompt is not one."""
    raw = prompt.strip().rstrip(".!")
    cmd = canonical(raw.lower())
    if cmd in CONTROL:
        return control(CONTROL[cmd])
    if cmd == MODELS_PHRASE:
        return models_available()
    if cmd == MODEL_PHRASE or cmd.startswith(MODEL_PHRASE + " "):
        prefix_len = len(raw) - len(cmd) + len(MODEL_PHRASE)  # the original prefix may be shorter than the canonical one
        try:
            args = shlex.split(raw[prefix_len:])
        except ValueError as e:
            return f"model router model: {e}"
        return model_command(args)[0]
    return None


def control(action):
    if action == "on":
        return core.set_enabled(True) + warm_azure()
    if action == "off":
        return core.set_enabled(False)
    if action == "reset":
        return reset_state()
    return core.status_text(core.read_state())


def seen_before(session_id):
    """True if this session already sent a prompt. Copilot hooks get no transcript_path, so track sessionIds."""
    with core.locked_state() as s:
        sessions = s.setdefault("sessions", {})
        had = session_id in sessions
        sessions.pop(session_id, None)
        sessions[session_id] = int(time.time())  # re-inserted at the end: most recent last
        while len(sessions) > MAX_SESSIONS:
            del sessions[next(iter(sessions))]
    return had


def note_for(route, info):
    agent = core.SIZES[route][0]
    return (f"{TAG} Sized as {route.upper()} (p={info['p']:.2f}). "
            f"Delegate the job to the `{agent}` custom agent via the task tool. "
            "Give it a self-contained prompt: the user's message plus any context it needs. "
            "Relay its result to the user as-is, keeping its final 'done by' line. "
            "Don't redo the work yourself. If the agent is unavailable or fails, do the job "
            "yourself and say the router fell back.")


def transform(payload):
    """The modifiedTransformedPrompt text, or None to leave the prompt untouched."""
    prompt = str(pick(payload, "prompt") or "").strip()
    transformed = pick(payload, "transformedPrompt", "transformed_prompt")
    if not isinstance(transformed, str):
        raise ValueError("hook input has no transformedPrompt string")

    # Copilot runs this hook for a subagent's own first prompt too (payload then carries agentId,
    # agentType and parentAgentId). Never size or annotate those: it would nest a routing note
    # inside the helper and risk a delegation loop.
    if any(payload.get(k) for k in ("parentAgentId", "agentId", "agentType")):
        return None

    reply = control_text(prompt)
    if reply is not None:
        return ECHO + reply  # the action is done here; the model only echoes the text

    session_id = str(pick(payload, "sessionId", "session_id") or "")
    has_history = seen_before(session_id) if session_id else False
    # PRESIZED: routercp already sized this prompt and starts copilot with the chosen model. Sizing again
    # would double the sizing calls and add a delegation note the main model must not follow.
    if (not prompt or prompt.startswith(("/", "!")) or TAG in transformed or OLD_TAG in transformed
            or core.setting("MODEL_ROUTER_PRESIZED") or not core.read_state()["enabled"]):
        return None
    route, info = core.decide(prompt, has_history)
    core.record(route, info, prompt)
    if route not in core.SIZES:
        return None
    return transformed + "\n\n" + note_for(route, info)


def warm_azure():
    """After `on` with the Azure backend: fetch the Entra token now, so the first routed message is not lost.
    Inside the hook this only starts the background refresh. Returns a note line, or an empty string."""
    try:
        if core.backend()[0] != "azure" or core.secret("MODEL_ROUTER_AZURE_API_KEY"):
            return ""
        core.azure_token()
        return ""
    except Exception as e:
        return f"\n  Azure token: {e}"


def record_error(message):
    with core.locked_state() as s:
        s["last_error"] = time.strftime("%H:%M ") + message[:200]


def run_transform():
    core.HOOK_MODE = True  # never wait for an Azure token here; use the cache and refresh in the background
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            raise ValueError("hook input is not a JSON object")
        text = transform(payload)
    except Exception as e:  # fail open: the message goes through unchanged, and nothing is printed
        try:
            record_error(f"hook {type(e).__name__}: {e}")
        except Exception:
            pass
        return
    if text is not None:
        print(json.dumps({"modifiedTransformedPrompt": text}))


def size_line(prompt):
    """Tier 3: decide() and record() for one prompt, as one line for routercp.

    "<route> <model-id> <effort>" for a helper size, or "local - -" when the main model keeps the
    prompt, or "off - -" when the router is OFF. Control phrases and slash/bang commands are left to
    the hook (local), so they are not sent to the sizing backend. routercp starts a new session, so there is no history.
    """
    prompt = prompt.strip()
    try:
        if (not prompt or prompt.startswith(("/", "!")) or canonical(prompt.lower().rstrip(".!")) in CONTROL
                or canonical(prompt.lower()).startswith(MODEL_PHRASE)):
            return "local - -"
        if not core.read_state()["enabled"]:
            return "off - -"
        route, info = core.decide(prompt, False)
        core.record(route, info, prompt)
    except Exception as e:
        try:
            record_error(f"size {type(e).__name__}: {e}")
        except Exception:
            pass
        return "local - -"
    if route not in MODELS:
        return "local - -"
    entry = MODELS[route]
    return f"{route} {entry['model']} {entry['effort'] or '-'}"


def key_status():
    """Which backend is active and where its credentials come from, never their values."""
    store = "Windows Credential Manager" if sys.platform == "win32" else "macOS Keychain"
    found = dict(router_compat.sources) if router_compat else {}

    def where(name):
        if name in found:
            return found[name]
        if os.environ.get(name):
            return "environment"
        return store if core.secret(name) else None

    kind, _ = core.backend()
    names = ("TYPESAFE_API_KEY",) if kind == "typesafe" else ("MODEL_ROUTER_AZURE_ENDPOINT", "MODEL_ROUTER_AZURE_DEPLOYMENT",
                                                                "MODEL_ROUTER_AZURE_API_KEY")
    lines, rc = [], 0
    for name in names:
        source = where(name)
        optional = name == "MODEL_ROUTER_AZURE_API_KEY"
        if source:
            lines.append(f"{name}: found ({source})")
        elif optional:
            lines.append(f"{name}: not set (an Entra token from the az CLI is used instead)")
        else:
            lines.append(f"{name}: missing (not in the environment, not in the {store})")
            rc = 1
    if kind == "azure" and not where("MODEL_ROUTER_AZURE_API_KEY"):
        token, expires_on = core.read_token_cache()
        if core.setting("MODEL_ROUTER_AZURE_TOKEN"):
            lines.append("Azure token: MODEL_ROUTER_AZURE_TOKEN (environment)")
        elif token and expires_on > time.time():
            lines.append("Azure token: cached until " + time.strftime("%Y-%m-%d %H:%M", time.localtime(expires_on)))
        elif shutil.which("az"):
            lines.append("Azure token: not cached yet; `router_copilot.py on` or `router.py azure-token` fetches it")
        else:
            lines.append("Azure token: az CLI not on PATH (install it, or set MODEL_ROUTER_AZURE_API_KEY)")
            rc = 1
    lines.append(f"backend: {core.backend_text()}")
    return "\n".join(lines), rc


def main(argv):
    mode = argv[1] if len(argv) > 1 else "status"
    if mode == "transform":
        run_transform()
        return 0
    if mode in ("on", "off", "status", "reset"):
        print(control(mode))
        return 0
    if mode == "size":
        print(size_line(argv[2] if len(argv) > 2 else ""))
        return 0
    if mode == "session":
        print(json.dumps({"additionalContext": SESSION_RULE}))
        return 0
    if mode == "model":
        text, rc = model_command(argv[2:])
        print(text, file=sys.stdout if rc == 0 else sys.stderr)
        return rc
    if mode == "models":
        print(models_available())
        return 0
    if mode == "key":
        text, rc = key_status()
        print(text)
        return rc
    if mode == "render-agents":
        try:
            paths = write_agents(load_models(strict=True), argv[2] if len(argv) > 2 else None)
        except ValueError as e:
            print(f"render-agents: {e}", file=sys.stderr)
            return 2
        print("\n".join(paths))
        return 0
    print("usage: router_copilot.py transform|on|off|status|reset|size \"<prompt>\"|session|model [...]|models|key|"
          "render-agents [DIR]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
