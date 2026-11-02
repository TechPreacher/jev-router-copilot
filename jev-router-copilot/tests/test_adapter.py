#!/usr/bin/env python3
"""Adapter tests (stdlib unittest, offline).

Every hook test runs the real command in a subprocess, as Copilot does: `python3 -I jev_copilot.py transform`
with JEV_ROUTER_HOME set to a temp dir and JEV_ROUTER_URL pointing at tests/fake_jev.py. TYPESAFE_API_KEY is
always set, so the macOS Keychain is never read. Run with: bash tests/run.sh
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(os.path.dirname(TESTS), "files")
ADAPTER = os.path.join(FILES, "jev_copilot.py")
sys.path.insert(0, TESTS)
import fake_jev  # noqa: E402

ECHO = "Reply with exactly the following text and nothing else:\n"
NOTE = "[jev-router] Jev sized this message as"
SIZE_PROMPT = "Summarise the attached meeting notes into five bullet points for the whole team."
WORKSPACE = ("<current_datetime>2026-10-29T11:07:32+01:00</current_datetime>\n\n{p}\n\n"
             "<system_reminder>\n<workspace_info>\nREADME.md\n</workspace_info>\n</system_reminder>")


def transformed(prompt):
    return WORKSPACE.format(p=prompt)


class AdapterCase(unittest.TestCase):
    server = None

    @classmethod
    def setUpClass(cls):
        cls.server = fake_jev.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="jev-copilot-test-")
        self.addCleanup(shutil.rmtree, self.home, True)

    def env(self, url_query=""):
        env = dict(os.environ)
        env["JEV_ROUTER_HOME"] = self.home
        env["TYPESAFE_API_KEY"] = "test-key"
        env["JEV_ROUTER_URL"] = self.server.url + (("?" + url_query) if url_query else "")
        return env

    def adapter(self, *args, stdin="", url_query=""):
        return subprocess.run([sys.executable, "-I", ADAPTER, *args], input=stdin, capture_output=True,
                              text=True, env=self.env(url_query), timeout=20)

    def hook(self, prompt, *, sid="s-1", raw=None, url_query="", transformed_text=None):
        """Run the transform hook. Returns stdout (empty string when the adapter stays silent)."""
        payload = {"sessionId": sid, "timestamp": 1793268452456, "cwd": "/tmp/project", "prompt": prompt,
                   "transformedPrompt": transformed(prompt) if transformed_text is None else transformed_text}
        stdin = raw if raw is not None else json.dumps(payload)
        res = self.adapter("transform", stdin=stdin, url_query=url_query)
        self.assertEqual(res.returncode, 0, res.stderr)  # fail-open: always exit 0
        return res.stdout

    def set_router(self, on):
        res = self.adapter("on" if on else "off")
        self.assertEqual(res.returncode, 0, res.stderr)

    def state(self):
        with open(os.path.join(self.home, "state.json")) as f:
            return json.load(f)

    def hits(self):
        return self.server.hits


class HookTests(AdapterCase):
    def test_off_gives_no_output_and_no_call(self):
        before = self.hits()
        self.assertEqual(self.hook(SIZE_PROMPT, url_query="size=tiny"), "")
        self.assertEqual(self.hits(), before)

    def test_control_phrases_act_and_echo_status(self):
        on = json.loads(self.hook("Jev Router On."))["modifiedTransformedPrompt"]
        self.assertTrue(on.startswith(ECHO))
        self.assertIn("Jev router: ON", on)
        self.assertTrue(self.state()["enabled"])

        off = json.loads(self.hook("jev router off"))["modifiedTransformedPrompt"]
        self.assertIn("Jev router: OFF", off)
        self.assertFalse(self.state()["enabled"])

        status = json.loads(self.hook("jev router status"))["modifiedTransformedPrompt"]
        self.assertTrue(status.startswith(ECHO))
        self.assertIn("Jev router: OFF", status)

    def test_reset_clears_counters_and_keeps_the_switch(self):
        self.set_router(True)
        self.hook(SIZE_PROMPT, sid="s-reset", url_query="size=tiny")
        self.assertEqual(self.state()["counts"].get("tiny"), 1)
        reset = json.loads(self.hook("jev router reset"))["modifiedTransformedPrompt"]
        self.assertTrue(reset.startswith(ECHO))
        self.assertTrue(self.state()["enabled"])
        self.assertEqual(self.state()["counts"], {})

    def test_slash_and_bang_prompts_are_not_sized(self):
        self.set_router(True)
        before = self.hits()
        for prompt in ("/help", "!ls -la"):
            self.assertEqual(self.hook(prompt, url_query="size=tiny"), "")
        self.assertEqual(self.hits(), before)

    def test_subagent_prompts_are_never_sized(self):
        """Copilot fires the hook for a helper's own prompt (agentId/parentAgentId present); skip it."""
        self.set_router(True)
        before = self.hits()
        payload = {"sessionId": "s-1", "timestamp": 1793268452456, "cwd": "/tmp/project",
                   "agentId": "jev-large", "agentType": "custom", "parentAgentId": "main",
                   "prompt": "User asks: write a migration plan for a large Rails app.",
                   "transformedPrompt": transformed("User asks: write a migration plan for a large Rails app.")}
        self.assertEqual(self.hook("ignored", raw=json.dumps(payload), url_query="size=large"), "")
        self.assertEqual(self.hits(), before)

    def test_secret_looking_prompt_never_leaves_the_machine(self):
        self.set_router(True)
        before = self.hits()
        out = self.hook("my key is sk-abcdefghijklmnopqrstuvwx1234 please check it", url_query="size=tiny")
        self.assertEqual(out, "")
        self.assertEqual(self.hits(), before)
        self.assertEqual(self.state()["counts"].get("skipped_private"), 1)

    def test_first_prompt_is_never_a_followup_but_a_later_yes_is(self):
        self.set_router(True)
        first = json.loads(self.hook("yes", sid="s-follow", url_query="size=tiny"))["modifiedTransformedPrompt"]
        self.assertIn(NOTE, first)
        before = self.hits()
        self.assertEqual(self.hook("yes", sid="s-follow", url_query="size=tiny"), "")
        self.assertEqual(self.hits(), before)
        self.assertEqual(self.state()["counts"].get("self_followup"), 1)

    def test_low_confidence_gives_no_output(self):
        self.set_router(True)
        self.assertEqual(self.hook(SIZE_PROMPT, sid="s-unsure", url_query="size=large&p=0.5"), "")
        self.assertEqual(self.state()["counts"].get("self_unsure"), 1)

    def test_each_size_names_its_agent_and_appends_the_note_last(self):
        self.set_router(True)
        for size in ("tiny", "everyday", "large", "hardest"):
            with self.subTest(size=size):
                text = transformed(SIZE_PROMPT)
                out = self.hook(SIZE_PROMPT, sid=f"s-{size}", url_query=f"size={size}&p=0.9")
                mt = json.loads(out)["modifiedTransformedPrompt"]
                self.assertTrue(mt.startswith(text + "\n\n"))
                note = mt[len(text) + 2:]
                self.assertTrue(note.startswith(f"{NOTE} {size.upper()} (p=0.90)."), note[:80])
                self.assertIn(f"`jev-{size}` custom agent", note)
                self.assertTrue(note.endswith("say the router fell back."))

    def test_sizing_uses_the_original_prompt_not_the_transformed_one(self):
        self.set_router(True)
        self.hook(SIZE_PROMPT, sid="s-body", url_query="size=tiny")
        self.assertEqual(self.server.last_body["state"]["message"], SIZE_PROMPT)

    def test_jev_timeout_fails_open(self):
        self.set_router(True)
        self.assertEqual(self.hook(SIZE_PROMPT, sid="s-slow", url_query="size=tiny&delay=3"), "")
        self.assertEqual(self.state()["counts"].get("self_error"), 1)
        self.assertIn("Error", self.state()["last_error"])

    def test_http_500_fails_open(self):
        self.set_router(True)
        self.assertEqual(self.hook(SIZE_PROMPT, sid="s-500", url_query="size=tiny&status=500"), "")
        self.assertEqual(self.state()["counts"].get("self_error"), 1)
        self.assertIn("HTTPError", self.state()["last_error"])

    def test_payload_already_carrying_the_note_is_left_alone(self):
        self.set_router(True)
        before = self.hits()
        text = transformed(SIZE_PROMPT) + "\n\n" + NOTE + " Jev sized this message as TINY (p=0.90)."
        self.assertEqual(self.hook(SIZE_PROMPT, sid="s-marker", url_query="size=tiny", transformed_text=text), "")
        self.assertEqual(self.hits(), before)

    def test_invalid_stdin_fails_open_and_is_reported_in_status(self):
        res = self.adapter("transform", stdin="this is not json {")
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "")
        status = self.adapter("status")
        self.assertIn("last error", status.stdout)
        self.assertIn("JSONDecodeError", status.stdout)

    def test_status_shows_hardest_pinned_to_opus(self):
        out = self.adapter("status").stdout
        self.assertIn("jev-hardest", out)
        self.assertIn("Claude Opus 5.5", out)
        self.assertNotIn("Fable", out)


class SessionTests(AdapterCase):
    def test_seen_sessions_are_bounded_to_200(self):
        code = ("import sys\n"
                "sys.path.insert(0, sys.argv[1])\n"
                "import jev_copilot as a\n"
                "for i in range(230):\n"
                "    a.seen_before('s%d' % i)\n"
                "print(len(a.core.read_state()['sessions']))\n")
        res = subprocess.run([sys.executable, "-I", "-c", code, FILES], capture_output=True, text=True,
                             env=self.env(), timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.strip(), "200")


class PackagingTests(unittest.TestCase):
    MODELS = {"tiny": ("claude-haiku-5.5", "Claude Haiku 5.5"),
              "everyday": ("claude-sonnet-5.5", "Claude Sonnet 5.5"),
              "large": ("claude-opus-5.5", "Claude Opus 5.5"),
              "hardest": ("claude-opus-5.5", "Claude Opus 5.5")}

    def test_agent_files_match_the_router_sizes(self):
        """The agent files rendered with the default config (what a fresh install writes)."""
        out_dir = tempfile.mkdtemp(prefix="jev-copilot-agents-")
        self.addCleanup(shutil.rmtree, out_dir, True)
        home = tempfile.mkdtemp(prefix="jev-copilot-home-")
        self.addCleanup(shutil.rmtree, home, True)
        res = subprocess.run([sys.executable, "-I", ADAPTER, "render-agents", out_dir], capture_output=True,
                             text=True, env={**os.environ, "JEV_ROUTER_HOME": home}, timeout=20)
        self.assertEqual(res.returncode, 0, res.stderr)
        for size, (model, footer_model) in self.MODELS.items():
            with self.subTest(size=size):
                with open(os.path.join(out_dir, f"jev-{size}.agent.md"), encoding="utf-8") as f:
                    text = f.read()
                parts = text.split("---\n", 2)
                self.assertEqual(parts[0], "")
                meta = {}
                for line in parts[1].splitlines():
                    if line and not line.startswith("#") and ":" in line:
                        key, value = line.split(":", 1)
                        meta[key.strip()] = value.strip()
                self.assertEqual(meta["name"], f"jev-{size}")
                self.assertEqual(meta["model"], model)
                self.assertEqual(meta["model-policy"], "required")
                self.assertEqual(meta["user-invocable"], "false")
                self.assertIn("[jev-router]", meta["description"])
                self.assertEqual(meta.get("reasoningEffort") == "high", size == "hardest")
                last = parts[2].rstrip().splitlines()[-1]
                self.assertEqual(last, f"— done by {footer_model} (jev-{size})")

    def test_hook_template_renders_to_valid_json(self):
        with open(os.path.join(FILES, "hooks", "jev-router.json.tmpl"), encoding="utf-8") as f:
            rendered = f.read().replace("@JR@", "/Users/me/My Copilot")
        entry = json.loads(rendered)["hooks"]["userPromptTransformed"][0]
        self.assertEqual(entry["timeoutSec"], 3)
        self.assertTrue(entry["bash"].startswith("python3 -I "))
        self.assertTrue(entry["bash"].endswith(" transform"))


if __name__ == "__main__":
    unittest.main()
