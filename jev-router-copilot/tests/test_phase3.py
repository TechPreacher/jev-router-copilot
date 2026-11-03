#!/usr/bin/env python3
"""Phase 3 tests (stdlib unittest, offline): Tier 2 MCP server, Tier 3 `size` mode and jevcp, the status line,
and the installer round-trip. The only network peer is tests/fake_jev.py on 127.0.0.1. copilot is a stub on PATH.
Run with: bash tests/run.sh
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
FILES = os.path.join(ROOT, "files")
ADAPTER = os.path.join(FILES, "jev_copilot.py")
MCP = os.path.join(FILES, "jev_mcp.py")
STATUS = os.path.join(FILES, "jev_statusline.py")
JEVCP = os.path.join(FILES, "bin", "jevcp")
INSTALL = os.path.join(ROOT, "install.sh")
UNINSTALL = os.path.join(ROOT, "uninstall.sh")
sys.path.insert(0, TESTS)
import fake_jev  # noqa: E402

SIZE_PROMPT = "Summarise the attached meeting notes into five bullet points for the whole team."
NOTE = "[jev-router] Jev sized this message as"


def run(args, *, env, stdin="", timeout=30):
    return subprocess.run([sys.executable, "-I", *args], input=stdin, capture_output=True, text=True,
                          env=env, timeout=timeout)


class Base(unittest.TestCase):
    server = None

    @classmethod
    def setUpClass(cls):
        cls.server = fake_jev.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="jev-phase3-")
        self.addCleanup(shutil.rmtree, self.home, True)

    def env(self, url_query=""):
        env = dict(os.environ)
        env.pop("JEV_ROUTER_PRESIZED", None)
        env["JEV_ROUTER_HOME"] = self.home
        env["TYPESAFE_API_KEY"] = "test-key"
        env["JEV_ROUTER_URL"] = self.server.url + (("?" + url_query) if url_query else "")
        return env

    def adapter(self, *args, stdin="", url_query="", extra_env=None):
        env = self.env(url_query)
        env.update(extra_env or {})
        return run([ADAPTER, *args], env=env, stdin=stdin)

    def set_router(self, on):
        res = self.adapter("on" if on else "off")
        self.assertEqual(res.returncode, 0, res.stderr)

    def hits(self):
        return self.server.hits


class McpTests(Base):
    def mcp(self, messages):
        stdin = "".join((m if isinstance(m, str) else json.dumps(m)) + "\n" for m in messages)
        res = run([MCP], env=self.env(), stdin=stdin)
        self.assertEqual(res.returncode, 0, res.stderr)
        return [json.loads(line) for line in res.stdout.splitlines()]  # stdout is JSON-RPC only

    def call(self, prompt, has_history=False):
        out = self.mcp([{"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                         "params": {"name": "jev_size", "arguments": {"prompt": prompt,
                                                                      "has_history": has_history}}}])
        return out[0]["result"]["content"][0]["text"]

    def test_handshake_list_ping_and_unknown_method(self):
        out = self.mcp([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "ping"},
            {"jsonrpc": "2.0", "id": 4, "method": "resources/list"},
        ])
        self.assertEqual([m["id"] for m in out], [1, 2, 3, 4])  # the notification gets no reply
        init = out[0]["result"]
        self.assertEqual(init["protocolVersion"], "2025-06-18")
        self.assertIn("tools", init["capabilities"])
        self.assertEqual(init["serverInfo"]["name"], "jev-router")
        tool = out[1]["result"]["tools"][0]
        self.assertEqual(tool["name"], "jev_size")
        self.assertEqual(tool["inputSchema"]["required"], ["prompt"])
        self.assertEqual(out[2]["result"], {})
        self.assertEqual(out[3]["error"]["code"], -32601)

    def test_bad_json_gets_parse_error_and_the_server_keeps_going(self):
        out = self.mcp(["{not json", {"jsonrpc": "2.0", "id": 5, "method": "ping"}])
        self.assertEqual(out[0]["error"]["code"], -32700)
        self.assertEqual(out[1]["id"], 5)

    def test_sized_prompt_returns_the_routing_note(self):
        self.set_router(True)
        self.server.size, self.server.p = "large", 0.9
        text = self.call(SIZE_PROMPT)
        self.assertIn("[jev-router]", text)
        self.assertIn("LARGE", text)
        self.assertIn("`jev-large`", text)
        self.assertEqual(self.state_counts().get("large"), 1)

    def test_when_off_it_says_so_and_writes_nothing(self):
        before = self.hits()
        text = self.call(SIZE_PROMPT)
        self.assertIn("OFF", text)
        self.assertEqual(self.hits(), before)
        self.assertFalse(os.path.exists(os.path.join(self.home, "decisions.log")))

    def test_follow_up_is_kept_by_the_main_model(self):
        self.set_router(True)
        text = self.call("yes", has_history=True)
        self.assertEqual(text, "Jev: kept by main model (short follow-up).")
        self.assertEqual(self.state_counts().get("self_followup"), 1)

    def state_counts(self):
        with open(os.path.join(self.home, "state.json")) as f:
            return json.load(f)["counts"]


class SizeModeTests(Base):
    MODELS = {"tiny": "tiny claude-haiku-5.5 -", "everyday": "everyday claude-sonnet-5.5 -",
              "large": "large claude-opus-5.5 -", "hardest": "hardest claude-opus-5.5 high"}

    def test_each_size_maps_to_its_copilot_model(self):
        self.set_router(True)
        for size, line in self.MODELS.items():
            with self.subTest(size=size):
                out = self.adapter("size", SIZE_PROMPT, url_query=f"size={size}")
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertEqual(out.stdout.strip(), line)

    def test_off_prints_off_and_makes_no_call(self):
        self.set_router(False)
        before = self.hits()
        out = self.adapter("size", SIZE_PROMPT, url_query="size=large")
        self.assertEqual(out.stdout.strip(), "off - -")
        self.assertEqual(self.hits(), before)

    def test_secret_prompt_stays_local(self):
        self.set_router(True)
        before = self.hits()
        out = self.adapter("size", "my key is sk-abcdefghijklmnopqrstuvwx1234 please check it", url_query="size=tiny")
        self.assertEqual(out.stdout.strip(), "local - -")
        self.assertEqual(self.hits(), before)

    def test_unsure_slash_and_control_prompts_stay_local(self):
        self.set_router(True)
        before = self.hits()
        self.assertEqual(self.adapter("size", SIZE_PROMPT, url_query="size=large&p=0.5").stdout.strip(), "local - -")
        self.assertEqual(self.adapter("size", "/help").stdout.strip(), "local - -")
        self.assertEqual(self.adapter("size", "jev router status").stdout.strip(), "local - -")
        self.assertEqual(self.hits(), before + 1)  # only the unsure prompt reached Jev

    def test_presized_env_silences_the_hook(self):
        self.set_router(True)
        before = self.hits()
        payload = json.dumps({"sessionId": "s-pre", "prompt": SIZE_PROMPT, "transformedPrompt": SIZE_PROMPT})
        out = self.adapter("transform", stdin=payload, url_query="size=large",
                           extra_env={"JEV_ROUTER_PRESIZED": "1"})
        self.assertEqual(out.stdout, "")
        self.assertEqual(self.hits(), before)


class SessionHookTests(Base):
    def test_session_mode_returns_the_standing_rule(self):
        out = self.adapter("session")
        self.assertEqual(out.returncode, 0, out.stderr)
        rule = json.loads(out.stdout)["additionalContext"]
        self.assertIn("jev_size", rule)
        self.assertIn("[jev-router]", rule)

    def test_session_template_renders_to_valid_json(self):
        with open(os.path.join(FILES, "hooks", "jev-router-session.json.tmpl"), encoding="utf-8") as f:
            entry = json.loads(f.read().replace("@JR@", "/Users/me/My Copilot"))["hooks"]["sessionStart"][0]
        self.assertEqual(entry["type"], "command")
        self.assertTrue(entry["bash"].endswith(" session"))


class StatusLineTests(Base):
    def status(self, stdin=""):
        return run([STATUS], env={**os.environ, "JEV_ROUTER_HOME": self.home}, stdin=stdin).stdout.strip()

    def write(self, name, text):
        with open(os.path.join(self.home, name), "w", encoding="utf-8") as f:
            f.write(text)

    def decision(self, route, **extra):
        return json.dumps({"t": "2026-10-30T13:20:41", "route": route, "chars": 42, **extra})

    def test_off_when_there_is_no_state(self):
        self.assertEqual(self.status(), "Jev OFF")

    def test_on_without_decisions(self):
        self.write("state.json", json.dumps({"enabled": True}))
        self.assertEqual(self.status(), "Jev ON · no decisions yet")

    def test_last_size_shows_percentage(self):
        self.write("state.json", json.dumps({"enabled": True}))
        self.write("decisions.log", self.decision("tiny", size="tiny", p=0.96) + "\n"
                   + self.decision("large", size="large", p=0.77) + "\n")
        self.assertEqual(self.status(), "Jev ON · large 77%")

    def test_kept_by_main_model_and_invalid_stdin(self):
        self.write("state.json", json.dumps({"enabled": True}))
        self.write("decisions.log", self.decision("self_unsure") + "\n")
        self.assertEqual(self.status(stdin="not json {"), "Jev ON · kept (unsure)")
        self.assertEqual(self.status(stdin=""), "Jev ON · kept (unsure)")

    def test_corrupt_log_fails_open(self):
        self.write("state.json", json.dumps({"enabled": True}))
        self.write("decisions.log", "garbage line\n")
        self.assertEqual(self.status(), "Jev ?")


@unittest.skipIf(os.name == "nt", "bash jevcp; see test_pwsh.py for jevcp.ps1")
class JevcpTests(Base):
    def setUp(self):
        super().setUp()
        self.layout = os.path.join(self.home, "jev-router")  # same shape as an install
        os.makedirs(os.path.join(self.layout, "bin"))
        for src, dst in (("jev_copilot.py", "jev_copilot.py"), ("router.py", "router.py"),
                         ("jev_compat.py", "jev_compat.py"), ("jev_statusline.py", "jev_statusline.py")):
            shutil.copy(os.path.join(FILES, src), os.path.join(self.layout, dst))
        shutil.copy(JEVCP, os.path.join(self.layout, "bin", "jevcp"))
        os.chmod(os.path.join(self.layout, "bin", "jevcp"), 0o755)
        self.stub_dir = os.path.join(self.home, "stub")
        os.makedirs(self.stub_dir)
        self.stub_out = os.path.join(self.home, "stub-argv.txt")
        stub = os.path.join(self.stub_dir, "copilot")
        with open(stub, "w") as f:
            f.write('#!/bin/sh\nprintf "%s\\n" "$@" > "$JEVCP_STUB_OUT"\n'
                    'printf "presized=%s\\n" "${JEV_ROUTER_PRESIZED:-}" >> "$JEVCP_STUB_OUT"\n')
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR)

    def env(self, url_query=""):
        env = super().env(url_query)
        env.pop("JEV_ROUTER_HOME")  # jevcp runs with the adapter's own folder as its state dir, as installed
        env["PATH"] = self.stub_dir + os.pathsep + os.environ.get("PATH", "")
        env["JEVCP_STUB_OUT"] = self.stub_out
        return env

    def adapter_at_layout(self, *args):
        return run([os.path.join(self.layout, "jev_copilot.py"), *args], env=self.env())

    def jevcp(self, *args, url_query="size=tiny"):
        return subprocess.run(["bash", os.path.join(self.layout, "bin", "jevcp"), *args], capture_output=True,
                              text=True, env=self.env(url_query), timeout=30)

    def argv(self):
        with open(self.stub_out) as f:
            return f.read().splitlines()

    def test_sized_prompt_runs_copilot_on_the_chosen_model(self):
        self.assertEqual(self.adapter_at_layout("on").returncode, 0)
        res = self.jevcp(SIZE_PROMPT, url_query="size=large&p=0.9")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("jevcp: large -> claude-opus-5.5", res.stderr)
        self.assertNotIn("TYPESAFE", res.stderr + res.stdout)
        self.assertEqual(self.argv(), ["--model", "claude-opus-5.5", "-p", SIZE_PROMPT, "presized=1"])

    def test_hardest_uses_high_effort_and_interactive_flag(self):
        self.adapter_at_layout("on")
        res = self.jevcp("-i", "--", SIZE_PROMPT, url_query="size=hardest&p=0.9")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.argv(), ["--model", "claude-opus-5.5", "--reasoning-effort", "high",
                                       "-i", SIZE_PROMPT, "presized=1"])

    def test_off_runs_the_default_model(self):
        self.adapter_at_layout("off")
        before = self.server.hits
        res = self.jevcp(SIZE_PROMPT, url_query="size=large")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("jevcp: off -> default model", res.stderr)
        self.assertEqual(self.argv(), ["-p", SIZE_PROMPT, "presized=1"])
        self.assertEqual(self.server.hits, before)

    def test_no_prompt_is_a_usage_error(self):
        res = self.jevcp()
        self.assertEqual(res.returncode, 2)
        self.assertFalse(os.path.exists(self.stub_out))


class ModelConsistencyTests(Base):
    def test_size_output_matches_the_rendered_agent_files(self):
        """The model jevcp picks is the model the helper agent file pins (both come from the same config)."""
        out_dir = os.path.join(self.home, "rendered")
        res = self.adapter("render-agents", out_dir)
        self.assertEqual(res.returncode, 0, res.stderr)
        for size, line in SizeModeTests.MODELS.items():
            with self.subTest(size=size):
                model = line.split()[1]
                with open(os.path.join(out_dir, f"jev-{size}.agent.md"), encoding="utf-8") as f:
                    self.assertIn(f"\nmodel: {model}\n", f.read())


@unittest.skipIf(os.name == "nt", "bash installer; see test_pwsh.py for install.ps1")
class InstallerTests(unittest.TestCase):
    def test_tier2_round_trip_leaves_only_what_was_there(self):
        home = tempfile.mkdtemp(prefix="jev-phase3-cp-")
        self.addCleanup(shutil.rmtree, home, True)
        with open(os.path.join(home, "settings.json"), "w") as f:
            f.write('{"keep": true}\n')
        env = {**os.environ, "COPILOT_HOME": home, "TYPESAFE_API_KEY": "test-key"}
        for args in ([], ["--tier2"], ["--tier2"]):  # the second --tier2 run checks idempotency
            res = subprocess.run(["bash", INSTALL, *args], env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertTrue(os.path.exists(os.path.join(home, "hooks", "jev-router-session.json")))
        self.assertTrue(os.path.exists(os.path.join(home, "jev-router", "jev_mcp.py")))
        self.assertTrue(os.access(os.path.join(home, "jev-router", "bin", "jevcp"), os.X_OK))
        res = subprocess.run(["bash", UNINSTALL], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        left = sorted(os.path.relpath(os.path.join(d, n), home) for d, _, ns in os.walk(home) for n in ns)
        self.assertEqual(left, ["settings.json"])
        with open(os.path.join(home, "settings.json")) as f:
            self.assertEqual(f.read(), '{"keep": true}\n')


if __name__ == "__main__":
    unittest.main()
