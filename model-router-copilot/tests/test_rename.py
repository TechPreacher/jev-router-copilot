#!/usr/bin/env python3
"""The jev-router -> model-router rename (stdlib unittest, offline): old chat phrases, old environment and state
names, old routing notes in replayed history, and an installer run over an install made under the old name.
Run with: bash tests/run.sh
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
FILES = os.path.join(ROOT, "files")
ADAPTER = os.path.join(FILES, "router_copilot.py")
INSTALL = os.path.join(ROOT, "install.sh")
INSTALL_PS1 = os.path.join(ROOT, "install.ps1")
PWSH = shutil.which("pwsh")
sys.path.insert(0, TESTS)
import fake_jev  # noqa: E402
from test_adapter import transformed  # noqa: E402

PROMPT = "Research the main options for migrating our reporting from Postgres to ClickHouse and write a report."


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class OldNamesTests(unittest.TestCase):
    server = None

    @classmethod
    def setUpClass(cls):
        cls.server = fake_jev.start(size="large")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="router-rename-")
        self.addCleanup(shutil.rmtree, self.home, True)

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("MODEL_ROUTER_", "JEV_"))}
        env.update({"MODEL_ROUTER_HOME": self.home, "TYPESAFE_API_KEY": "test-key", "MODEL_ROUTER_URL": self.server.url})
        env.update(extra)
        return env

    def adapter(self, *args, stdin="", **extra):
        return subprocess.run([sys.executable, "-I", ADAPTER, *args], input=stdin, capture_output=True, text=True,
                              encoding="utf-8", env=self.env(**extra), timeout=30)

    def hook(self, prompt, transformed_text=None, **extra):
        payload = {"sessionId": "r-1", "prompt": prompt,
                   "transformedPrompt": transformed(prompt) if transformed_text is None else transformed_text}
        res = self.adapter("transform", stdin=json.dumps(payload), **extra)
        self.assertEqual(res.returncode, 0, res.stderr)
        return res.stdout

    def test_old_and_short_phrases_still_control_the_router(self):
        for phrase in ("jev router on", "Router Status", "model router off", "jev router model", "router models"):
            out = self.hook(phrase)
            self.assertTrue(out, phrase)
            text = json.loads(out)["modifiedTransformedPrompt"]
            self.assertIn("Reply with exactly the following text", text, phrase)
        self.assertIn("Model router: OFF", json.loads(self.hook("router status"))["modifiedTransformedPrompt"])
        self.assertEqual(self.server.hits, 0, "control phrases are never sized")
        res = self.adapter("size", "jev router on")
        self.assertEqual(res.stdout.strip(), "local - -")

    def test_old_note_in_replayed_history_is_not_sized_again(self):
        self.adapter("on")
        before = self.server.hits
        old = transformed(PROMPT) + "\n\n[jev-router] Jev sized this message as LARGE (p=0.90). Delegate ..."
        self.assertEqual(self.hook(PROMPT, transformed_text=old), "")
        self.assertEqual(self.server.hits, before)
        self.assertIn("[model-router] Sized as LARGE", json.loads(self.hook(PROMPT))["modifiedTransformedPrompt"])

    def test_old_environment_names_are_honoured(self):
        legacy_home = tempfile.mkdtemp(prefix="router-legacy-home-")
        self.addCleanup(shutil.rmtree, legacy_home, True)
        env = self.env()
        del env["MODEL_ROUTER_HOME"]
        env["JEV_ROUTER_HOME"] = legacy_home
        res = subprocess.run([sys.executable, "-I", ADAPTER, "on"], capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(os.path.exists(os.path.join(legacy_home, "state.json")), "state went to JEV_ROUTER_HOME")
        env["JEV_ROUTER_URL"] = env.pop("MODEL_ROUTER_URL")  # only the old URL override set: the fake must still be hit
        payload = {"sessionId": "r-2", "prompt": PROMPT, "transformedPrompt": transformed(PROMPT)}
        before = self.server.hits
        res = subprocess.run([sys.executable, "-I", ADAPTER, "transform"], input=json.dumps(payload), capture_output=True,
                             text=True, env=env, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("[model-router] Sized as LARGE", json.loads(res.stdout)["modifiedTransformedPrompt"])
        self.assertEqual(self.server.hits, before + 1, "JEV_ROUTER_URL still redirects the sizing call")
        res = subprocess.run([sys.executable, "-I", os.path.join(FILES, "router_statusline.py")], capture_output=True,
                             text=True, env=env, timeout=30)
        self.assertTrue(res.stdout.startswith("Router ON"), "the status line reads state from JEV_ROUTER_HOME too")
        self.adapter("on")
        self.assertEqual(self.hook(PROMPT, JEV_ROUTER_PRESIZED="1"), "", "the old PRESIZED name still silences the hook")
        res = self.adapter("status", JEV_AZURE_ENDPOINT="https://x.services.ai.azure.com", JEV_AZURE_DEPLOYMENT="d")
        self.assertIn("backend: Microsoft Decision-1", res.stdout, "old Azure names select the Azure backend")
        res = self.adapter("status", JEV_AZURE_ENDPOINT="https://x.services.ai.azure.com", JEV_AZURE_DEPLOYMENT="d",
                           JEV_BACKEND="typesafe")
        self.assertIn("backend: TypeSafe Jev", res.stdout)

    def test_old_state_file_counts_carry_over(self):
        with open(os.path.join(self.home, "state.json"), "w") as f:
            json.dump({"enabled": True, "counts": {"tiny": 3}, "jev_calls": 7, "input_tokens": 700, "errors": 0,
                       "last_error": None, "since": "2026-11-01 09:00"}, f)
        res = self.adapter("status")
        self.assertIn("sizing: 7 calls, 700 input tokens", res.stdout)
        self.hook(PROMPT)
        with open(os.path.join(self.home, "state.json")) as f:
            state = json.load(f)
        self.assertEqual(state["sizing_calls"], 8)
        self.assertNotIn("jev_calls", state)


class MigrationTests(unittest.TestCase):
    """The installers move an install made under the old name and clean up its files."""

    def old_layout(self):
        home = tempfile.mkdtemp(prefix="router-migrate-")
        self.addCleanup(shutil.rmtree, home, True)
        old = os.path.join(home, "jev-router")
        os.makedirs(os.path.join(old, "bin"))
        os.makedirs(os.path.join(old, "agents"))
        os.makedirs(os.path.join(home, "hooks"))
        os.makedirs(os.path.join(home, "agents"))
        os.makedirs(os.path.join(home, "skills", "jev-router"))
        with open(os.path.join(old, "models.json"), "w") as f:
            json.dump({"hardest": {"model": "claude-sonnet-5.5", "label": "Sonnet", "effort": None, "policy": "required"}}, f)
        with open(os.path.join(old, "state.json"), "w") as f:
            json.dump({"enabled": True, "counts": {"tiny": 2}, "jev_calls": 2, "input_tokens": 80, "errors": 0,
                       "last_error": None, "since": "2026-11-01 09:00"}, f)
        for rel in ("jev_copilot.py", "jev_compat.py", "jev_mcp.py", "bin/jevcp", "bin/jevcp.ps1",
                    "agents/jev-tiny.agent.md.tmpl"):  # jev_mcp.py: the old install had Tier 2
            with open(os.path.join(old, rel), "w") as f:
                f.write("old\n")
        for rel in ("hooks/jev-router.json", "hooks/jev-router-session.json", "agents/jev-tiny.agent.md",
                    "skills/jev-router/SKILL.md"):
            with open(os.path.join(home, rel), "w") as f:
                f.write("old\n")
        with open(os.path.join(home, "settings.json"), "w") as f:
            f.write('{"statusLine": {"type": "command", "command": "python3 -I jev-router/jev_statusline.py"}}\n')
        return home

    def check(self, home, out):
        new = os.path.join(home, "model-router")
        self.assertIn("migrated the jev-router install", out)
        self.assertFalse(os.path.exists(os.path.join(home, "jev-router")))
        with open(os.path.join(new, "models.json")) as f:
            self.assertEqual(json.load(f)["hardest"]["model"], "claude-sonnet-5.5")
        self.assertIn("\nmodel: claude-sonnet-5.5\n", read(os.path.join(home, "agents", "router-hardest.agent.md")))
        with open(os.path.join(new, "state.json")) as f:
            self.assertTrue(json.load(f)["enabled"], "the on/off switch survived")
        for rel in ("jev_copilot.py", "jev_compat.py", "jev_mcp.py", "bin/jevcp", "bin/jevcp.ps1",
                    "agents/jev-tiny.agent.md.tmpl"):
            self.assertFalse(os.path.exists(os.path.join(new, rel)), rel)
        self.assertTrue(os.path.exists(os.path.join(new, "router_mcp.py")), "Tier 2 kept under its new name")
        self.assertTrue(os.path.exists(os.path.join(home, "hooks", "model-router-session.json")))
        self.assertIn("Tier 2 installed", out)
        for rel in ("hooks/jev-router.json", "hooks/jev-router-session.json", "agents/jev-tiny.agent.md", "skills/jev-router"):
            self.assertFalse(os.path.exists(os.path.join(home, rel)), rel)
        self.assertTrue(os.path.exists(os.path.join(home, "hooks", "model-router.json")))
        self.assertTrue(os.path.exists(os.path.join(home, "skills", "model-router", "SKILL.md")))
        self.assertIn("still points at jev-router/", out)
        self.assertIn("jev-router/jev_statusline.py", read(os.path.join(home, "settings.json")), "settings.json untouched")

    @unittest.skipIf(os.name == "nt", "bash installer")
    def test_bash_installer_migrates(self):
        home = self.old_layout()
        env = {**os.environ, "COPILOT_HOME": home, "TYPESAFE_API_KEY": "test-key"}
        env.pop("MODEL_ROUTER_HOME", None)
        res = subprocess.run(["bash", INSTALL], env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.check(home, res.stdout)

    @unittest.skipUnless(PWSH, "pwsh not on PATH")
    def test_powershell_installer_migrates(self):
        home = self.old_layout()
        env = {**os.environ, "COPILOT_HOME": home, "TYPESAFE_API_KEY": "test-key"}
        env.pop("MODEL_ROUTER_HOME", None)
        res = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", INSTALL_PS1],
                             env=env, capture_output=True, text=True, encoding="utf-8", timeout=180)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.check(home, res.stdout)


if __name__ == "__main__":
    unittest.main()
