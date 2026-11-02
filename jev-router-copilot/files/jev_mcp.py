#!/usr/bin/env python3
"""Tier 2 fallback: stdio MCP server with one tool, jev_size, for Copilot CLI.

Use only when the userPromptTransformed hook (Tier 1) stops working. The sessionStart hook tells the model
to call jev_size for each new request. The tool runs decide() and record() from the unchanged router core
and returns the same routing note as the hook.

Transport: newline-delimited JSON-RPC 2.0 on stdin/stdout (MCP spec 2025-06-18, basics only). stdout carries
JSON-RPC and nothing else; diagnostics go to stderr. Register with:
    {"mcpServers": {"jev-router": {"type": "local", "command": "python3", "args": ["-I", "<dir>/jev_mcp.py"],
                                   "tools": ["*"]}}}
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("JEV_ROUTER_HOME", HERE)
sys.path.insert(0, HERE)  # python3 -I leaves the script's own directory off sys.path
import jev_copilot as adapter  # noqa: E402  (imports the unchanged router core, sets the Tier 1 labels)

core = adapter.core
PROTOCOL = "2025-06-18"
SERVER_INFO = {"name": "jev-router", "version": "1.0.0"}
TOOL = {
    "name": "jev_size",
    "description": ("Size a user request with Jev (tiny, everyday, large or hardest) and return the routing "
                    "note to follow. Call it once per new user request, not for short follow-up replies."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "The user's message, as typed."},
            "has_history": {"type": "boolean",
                            "description": "True if this session already had a request before this one."},
        },
        "required": ["prompt"],
    },
}
REASONS = {"self_unsure": "unsure", "self_followup": "short follow-up", "skipped_private": "secret-looking",
           "self_error": "Jev error or slow"}


def log(message):
    sys.stderr.write(f"jev_mcp: {message}\n")
    sys.stderr.flush()


def text_result(text):
    return {"content": [{"type": "text", "text": text}]}


def size_text(args):
    if not core.read_state()["enabled"]:
        return ("Jev router is OFF, so this message is not sized. Keep the work with the main model. "
                "Turn routing on from the shell: python3 -I jev_copilot.py on")
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return "Jev: empty prompt, kept by main model."
    route, info = core.decide(prompt, args.get("has_history") is True)
    core.record(route, info, prompt)
    if route in core.SIZES:
        return adapter.note_for(route, info)
    return f"Jev: kept by main model ({REASONS.get(route, route)})."


def handle(msg):
    """The reply dict for one JSON-RPC message, or None when no reply is due (notifications)."""
    if "id" not in msg:
        return None  # notifications, e.g. notifications/initialized
    mid, method, params = msg["id"], msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        version = params.get("protocolVersion") if isinstance(params.get("protocolVersion"), str) else PROTOCOL
        result = {"protocolVersion": version, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        if params.get("name") != TOOL["name"]:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}}
        args = params.get("arguments") or {}
        try:
            result = text_result(size_text(args if isinstance(args, dict) else {}))
        except Exception as e:  # sizing failed: the main model keeps the message
            log(f"jev_size failed: {type(e).__name__}: {e}")
            result = text_result("Jev: sizing failed, kept by main model.")
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def reply(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            continue
        if not isinstance(msg, dict):
            reply({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}})
            continue
        out = handle(msg)
        if out is not None:
            reply(out)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
