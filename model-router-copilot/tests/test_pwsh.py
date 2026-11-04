#!/usr/bin/env python3
"""PowerShell twins (stdlib unittest, offline): install.ps1 and uninstall.ps1 round trips in a temporary
COPILOT_HOME, routercp.ps1 with a stub copilot, and a parse check of every .ps1 file. Runs wherever pwsh is on PATH
(GitHub's Ubuntu, macOS and Windows runners all have it); skipped otherwise. Run with: bash tests/run.sh
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
INSTALL = os.path.join(ROOT, "install.ps1")
UNINSTALL = os.path.join(ROOT, "uninstall.ps1")
ROUTERCP = os.path.join(FILES, "bin", "routercp.ps1")
PWSH = shutil.which("pwsh")
SCRIPTS = [INSTALL, UNINSTALL, ROUTERCP, os.path.join(TESTS, "run.ps1")]
sys.path.insert(0, TESTS)
import fake_jev  # noqa: E402

SIZE_PROMPT = "Summarise the attached meeting notes into five bullet points for the whole team."
PARSE = ("$bad = 0; foreach ($f in ($env:MR_PS_FILES -split [System.IO.Path]::PathSeparator)) { $t = $null; $e = $null; "
         "$null = [System.Management.Automation.Language.Parser]::ParseFile($f, [ref]$t, [ref]$e); "
         "if ($e.Count) { $bad++; $e | ForEach-Object { Write-Output ($f + ':' + $_.Extent.StartLineNumber + ': ' + $_.Message) } } }; "
         "exit $bad")


def pwsh(script, *args, env, stdin="", timeout=180):
    return subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script, *args],
                          input=stdin, capture_output=True, text=True, encoding="utf-8", env=env, timeout=timeout)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


@unittest.skipUnless(PWSH, "pwsh not on PATH")
class ParseTests(unittest.TestCase):
    def test_every_powershell_file_parses(self):
        res = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", PARSE], capture_output=True,
                             text=True, timeout=60, env={**os.environ, "MR_PS_FILES": os.pathsep.join(SCRIPTS)})
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


@unittest.skipUnless(PWSH, "pwsh not on PATH")
class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="router-pwsh-cp-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.env = {**os.environ, "COPILOT_HOME": self.home, "TYPESAFE_API_KEY": "test-key"}
        self.env.pop("MODEL_ROUTER_HOME", None)

    def install(self, *args):
        res = pwsh(INSTALL, *args, env=self.env)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        return res

    def path(self, *parts):
        return os.path.join(self.home, *parts)

    def test_round_trip_leaves_only_what_was_there(self):
        with open(self.path("settings.json"), "w") as f:
            f.write('{"keep": true}\n')
        out = self.install().stdout
        self.assertIn("Self-test passed", out)
        self.assertIn("Done. Model router: OFF", out)
        self.assertNotIn("TYPESAFE_API_KEY in this shell", out)  # the key was in the environment
        for rel in ("model-router/router.py", "model-router/router_copilot.py", "model-router/router_compat.py",
                    "model-router/router_statusline.py", "model-router/bin/routercp", "model-router/bin/routercp.ps1",
                    "model-router/state.json", "model-router/agents/router-tiny.agent.md.tmpl", "hooks/model-router.json",
                    "skills/model-router/SKILL.md", *(f"agents/router-{s}.agent.md" for s in ("tiny", "everyday", "large", "hardest"))):
            self.assertTrue(os.path.exists(self.path(*rel.split("/"))), rel)
        self.assertFalse(os.path.exists(self.path("hooks", "model-router-session.json")))
        self.assertFalse(os.path.exists(self.path("model-router", "router_mcp.py")))
        with open(self.path("model-router", "state.json")) as f:
            self.assertFalse(json.load(f)["enabled"])
        # the hook has a command for both shells and no placeholder left
        hook = json.loads(read(self.path("hooks", "model-router.json")))
        entry = hook["hooks"]["userPromptTransformed"][0]
        self.assertEqual(entry["timeoutSec"], 3)
        self.assertTrue(entry["bash"].startswith("python3 -I "))
        self.assertTrue(entry["powershell"].endswith(" transform"))
        self.assertIn("router_copilot.py", entry["powershell"])
        if os.name == "nt":
            self.assertTrue(entry["powershell"].startswith('& "'), entry["powershell"])
            self.assertIn(self.home.lower(), entry["powershell"].lower())
        else:
            self.assertTrue(entry["powershell"].startswith("python3 -I "))
        for rel in ("hooks/model-router.json", "skills/model-router/SKILL.md"):
            text = read(self.path(*rel.split("/")))
            self.assertNotIn("@JR@", text, rel)
            self.assertNotIn("@PY@", text, rel)
        self.assertIn("router_copilot.py", read(self.path("skills", "model-router", "SKILL.md")))
        # the statusLine snippet is valid JSON that points at the installed status line
        snippet = out.split("settings.json (top level):", 1)[1].split("\n\n", 1)[0]
        self.assertIn("router_statusline.py", json.loads(snippet)["statusLine"]["command"])
        # Tier 2, twice: idempotent, and it only adds the session hook and the MCP server
        for _ in range(2):
            out2 = self.install("-Tier2").stdout
        self.assertIn("Tier 2 installed", out2)
        self.assertNotIn("kept previous", out2)
        self.assertTrue(os.path.exists(self.path("hooks", "model-router-session.json")))
        self.assertTrue(os.path.exists(self.path("model-router", "router_mcp.py")))
        mcp = json.loads(out2.split("(keep your other servers):", 1)[1].split("\nUse Tier 2", 1)[0])
        self.assertEqual(mcp["mcpServers"]["model-router"]["args"][0], "-I")
        self.assertTrue(mcp["mcpServers"]["model-router"]["args"][1].endswith("router_mcp.py"))
        session = json.loads(read(self.path("hooks", "model-router-session.json")))["hooks"]["sessionStart"][0]
        self.assertTrue(session["powershell"].endswith(" session"))
        res = pwsh(UNINSTALL, env=self.env)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        left = sorted(os.path.relpath(os.path.join(d, n), self.home) for d, _, ns in os.walk(self.home) for n in ns)
        self.assertEqual(left, ["settings.json"])
        self.assertEqual(read(self.path("settings.json")), '{"keep": true}\n')

    def test_reinstall_keeps_a_changed_model_and_backs_up_a_changed_file(self):
        self.install()
        agent = self.path("agents", "router-hardest.agent.md")
        self.assertIn("\nmodel: claude-opus-5.5\nreasoningEffort: high\n", read(agent))
        installed = self.path("model-router", "router_copilot.py")
        res = subprocess.run([sys.executable, "-I", installed, "model", "hardest", "claude-sonnet-5.5", "--effort", "none"],
                             capture_output=True, text=True, encoding="utf-8",
                             env={**os.environ, "TYPESAFE_API_KEY": "test-key"}, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("\nmodel: claude-sonnet-5.5\nmodel-policy: required\n", read(agent))
        # an edited installed file is kept as a .bak, the choice survives, no agent backup is made
        with open(installed, "a", encoding="utf-8") as f:
            f.write("\n# local edit\n")
        out = self.install().stdout
        self.assertIn("kept previous router_copilot.py as router_copilot.py.bak-", out)
        self.assertIn("\nmodel: claude-sonnet-5.5\n", read(agent))
        names = os.listdir(self.path("model-router"))
        self.assertEqual(len([n for n in names if n.startswith("router_copilot.py.bak-")]), 1)
        self.assertEqual([n for n in os.listdir(self.path("agents")) if ".bak-" in n], [])
        self.assertEqual(read(installed), read(os.path.join(FILES, "router_copilot.py")))

    def test_missing_key_is_reported_without_a_value(self):
        if sys.platform == "darwin":
            self.skipTest("the macOS Keychain may hold a real key")
        env = {k: v for k, v in self.env.items() if k != "TYPESAFE_API_KEY"}
        res = pwsh(INSTALL, env=env)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("NOTE: the active backend lacks a credential", res.stdout)
        self.assertIn("TYPESAFE_API_KEY: missing", res.stdout)
        self.assertIn("Credential Manager" if os.name == "nt" else "Keychain", res.stdout)


@unittest.skipUnless(PWSH, "pwsh not on PATH")
class RoutercpTests(unittest.TestCase):
    """routercp.ps1 against a stub copilot.ps1 that records its arguments and the PRESIZED flag."""
    server = None

    @classmethod
    def setUpClass(cls):
        cls.server = fake_jev.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="router-pwsh-routercp-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.layout = os.path.join(self.home, "model-router")  # same shape as an install
        os.makedirs(os.path.join(self.layout, "bin"))
        for name in ("router_copilot.py", "router.py", "router_compat.py", "router_statusline.py"):
            shutil.copy(os.path.join(FILES, name), os.path.join(self.layout, name))
        shutil.copy(ROUTERCP, os.path.join(self.layout, "bin", "routercp.ps1"))
        self.stub_dir = os.path.join(self.home, "stub")
        os.makedirs(self.stub_dir)
        self.stub_out = os.path.join(self.home, "stub-argv.txt")
        with open(os.path.join(self.stub_dir, "copilot.ps1"), "w") as f:
            f.write("$args | Set-Content -LiteralPath $env:ROUTERCP_STUB_OUT\n"
                    "\"presized=$env:MODEL_ROUTER_PRESIZED\" | Add-Content -LiteralPath $env:ROUTERCP_STUB_OUT\n")

    def env(self, url_query=""):
        env = dict(os.environ)
        env.pop("MODEL_ROUTER_PRESIZED", None)
        env.pop("MODEL_ROUTER_HOME", None)  # routercp runs with the adapter's own folder as its state dir, as installed
        env["TYPESAFE_API_KEY"] = "test-key"
        env["MODEL_ROUTER_URL"] = self.server.url + (("?" + url_query) if url_query else "")
        env["PATH"] = self.stub_dir + os.pathsep + os.environ.get("PATH", "")
        env["ROUTERCP_STUB_OUT"] = self.stub_out
        return env

    def set_router(self, on):
        res = subprocess.run([sys.executable, "-I", os.path.join(self.layout, "router_copilot.py"), "on" if on else "off"],
                             capture_output=True, text=True, env=self.env(), timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)

    def routercp(self, *args, url_query="size=tiny"):
        return pwsh(os.path.join(self.layout, "bin", "routercp.ps1"), *args, env=self.env(url_query), timeout=60)

    def argv(self):
        return read(self.stub_out).splitlines()

    def test_sized_prompt_runs_copilot_on_the_chosen_model(self):
        self.set_router(True)
        res = self.routercp(SIZE_PROMPT, url_query="size=large&p=0.9")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("routercp: large -> claude-opus-5.5", res.stderr)
        self.assertNotIn("TYPESAFE", res.stderr + res.stdout)
        self.assertEqual(self.argv(), ["--model", "claude-opus-5.5", "-p", SIZE_PROMPT, "presized=1"])

    def test_hardest_uses_high_effort_and_interactive_flag(self):
        self.set_router(True)
        res = self.routercp("-i", SIZE_PROMPT, url_query="size=hardest&p=0.9")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.argv(), ["--model", "claude-opus-5.5", "--reasoning-effort", "high",
                                       "-i", SIZE_PROMPT, "presized=1"])

    def test_off_runs_the_default_model(self):
        self.set_router(False)
        before = self.server.hits
        res = self.routercp(SIZE_PROMPT, url_query="size=large")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("routercp: off -> default model", res.stderr)
        self.assertEqual(self.argv(), ["-p", SIZE_PROMPT, "presized=1"])
        self.assertEqual(self.server.hits, before)

    def test_no_prompt_is_a_usage_error(self):
        res = self.routercp()
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertFalse(os.path.exists(self.stub_out))

    def test_presized_flag_does_not_leak_into_the_calling_session(self):
        """Run as a script inside one PowerShell session, as a user would: the flag must be gone afterwards."""
        self.set_router(False)
        script = os.path.join(self.layout, "bin", "routercp.ps1")
        command = (f"& '{script}' '{SIZE_PROMPT}'; Write-Output \"after=[$env:MODEL_ROUTER_PRESIZED]\"; "
                   "Write-Output \"rc=$LASTEXITCODE\"")
        res = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
                             capture_output=True, text=True, encoding="utf-8", env=self.env(), timeout=60)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(self.argv(), ["-p", SIZE_PROMPT, "presized=1"])  # copilot itself saw the flag
        self.assertIn("after=[]", res.stdout)  # the session did not keep it


if __name__ == "__main__":
    unittest.main()
