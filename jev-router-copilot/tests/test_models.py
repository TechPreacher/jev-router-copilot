#!/usr/bin/env python3
"""Per-size model configuration (stdlib unittest, offline): models.json, the `model` command and chat phrase,
agent files rendered from templates, and changing a model on an installed copy without re-installing.
The agent files land in $COPILOT_HOME/agents, so COPILOT_HOME points at the temp dir. Run with: bash tests/run.sh
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)
from test_phase3 import Base, FILES, INSTALL, UNINSTALL, NOTE, SIZE_PROMPT, run  # noqa: E402

ECHO = "Reply with exactly the following text and nothing else:\n"
DEFAULT_MODELS = {"tiny": "claude-haiku-5.5", "everyday": "claude-sonnet-5.5",
                  "large": "claude-opus-5.5", "hardest": "claude-opus-5.5"}


class ModelsBase(Base):
    def env(self, url_query=""):
        env = super().env(url_query)
        env["COPILOT_HOME"] = self.home  # agent files are rendered into <COPILOT_HOME>/agents
        return env

    def agent(self, size):
        with open(os.path.join(self.home, "agents", f"jev-{size}.agent.md"), encoding="utf-8") as f:
            return f.read()

    def models_json(self):
        with open(os.path.join(self.home, "models.json"), encoding="utf-8") as f:
            return json.load(f)

    def hook(self, prompt, url_query=""):
        payload = {"sessionId": "s-1", "prompt": prompt, "transformedPrompt": prompt}
        res = self.adapter("transform", stdin=json.dumps(payload), url_query=url_query)
        self.assertEqual(res.returncode, 0, res.stderr)
        return res.stdout


class ModelCommandTests(ModelsBase):
    def test_show_uses_the_defaults_when_there_is_no_file(self):
        res = self.adapter("model")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("defaults, no models.json yet", res.stdout)
        for size, model in DEFAULT_MODELS.items():
            self.assertRegex(res.stdout, rf"\n  {size}\s+{model}\s")
        self.assertIn("hardest   claude-opus-5.5        effort high", res.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.home, "models.json")))

    def test_set_writes_the_file_renders_the_agent_and_changes_size_and_status(self):
        res = self.adapter("model", "large", "claude-sonnet-5.5")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("Re-rendered", res.stdout)
        self.assertEqual(self.models_json()["large"], {"model": "claude-sonnet-5.5", "label": "Claude Sonnet 5.5",
                                                        "effort": None, "policy": "required"})
        text = self.agent("large")
        self.assertIn("\nmodel: claude-sonnet-5.5\n", text)
        self.assertNotIn("reasoningEffort", text)
        self.assertIn("\nmodel-policy: required\n", text)
        self.assertTrue(text.rstrip().endswith("— done by Claude Sonnet 5.5 (jev-large)"))
        self.assertFalse(os.path.exists(os.path.join(self.home, "agents", "jev-tiny.agent.md")),
                         "only the changed size is re-rendered")
        # jevcp's size mode and the status text follow the file
        self.set_router(True)
        out = self.adapter("size", SIZE_PROMPT, url_query="size=large")
        self.assertEqual(out.stdout.strip(), "large claude-sonnet-5.5 -")
        self.assertIn("large     -> jev-large     Claude Sonnet 5.5", self.adapter("status").stdout)
        # the routing note still names the agent, which did not change
        self.assertIn("`jev-large` custom agent", self.hook(SIZE_PROMPT, url_query="size=large"))

    def test_flags_set_label_effort_and_policy_and_none_removes_effort(self):
        res = self.adapter("model", "hardest", "gpt-6.1-sol", "--label", "GPT 6.1 Sol", "--effort", "low",
                           "--policy", "preferred")
        self.assertEqual(res.returncode, 0, res.stderr)
        text = self.agent("hardest")
        self.assertIn("\nmodel: gpt-6.1-sol\nreasoningEffort: low\nmodel-policy: preferred\n", text)
        self.assertTrue(text.rstrip().endswith("— done by GPT 6.1 Sol (jev-hardest)"))
        res = self.adapter("model", "hardest", "gpt-6.1-sol", "--effort", "none")
        self.assertEqual(res.returncode, 0, res.stderr)
        text = self.agent("hardest")
        self.assertNotIn("reasoningEffort", text)
        self.assertIn("— done by GPT 6.1 Sol (jev-hardest)", text, "an unset label is derived from the ID")
        self.assertEqual(self.adapter("size", SIZE_PROMPT, url_query="size=hardest").stdout.strip(),
                         "off - -")  # router still OFF in this test: size mode respects it

    def test_bad_input_changes_nothing(self):
        for args in (["huge", "claude-haiku-5.5"], ["tiny", "Bad ID"], ["tiny"], ["tiny", "x", "--policy", "maybe"],
                     ["tiny", "claude-haiku-5.5", "--effort", "max"], ["tiny", "claude-haiku-5.5", "--bogus", "1"]):
            with self.subTest(args=args):
                res = self.adapter("model", *args)
                self.assertEqual(res.returncode, 2, res.stdout)
                self.assertIn("jev router model:", res.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.home, "models.json")))
        self.assertFalse(os.path.exists(os.path.join(self.home, "agents")))

    def test_reset_removes_the_file_and_re_renders_all_four(self):
        self.assertEqual(self.adapter("model", "tiny", "claude-sonnet-5.5").returncode, 0)
        res = self.adapter("model", "reset")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("Defaults restored", res.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.home, "models.json")))
        for size, model in DEFAULT_MODELS.items():
            self.assertIn(f"\nmodel: {model}\n", self.agent(size))

    def test_chat_phrase_changes_the_model_and_echoes_the_table_without_calling_jev(self):
        before = self.hits()
        out = self.hook('jev router model tiny gpt-6.1-sol --label "GPT Sol"')
        self.assertTrue(out, "the hook must answer a control phrase")
        text = json.loads(out)["modifiedTransformedPrompt"]
        self.assertTrue(text.startswith(ECHO + "Jev router models ("))
        self.assertIn("tiny      gpt-6.1-sol", text)
        self.assertIn("\nmodel: gpt-6.1-sol\n", self.agent("tiny"))
        self.assertIn("— done by GPT Sol (jev-tiny)", self.agent("tiny"))
        self.assertEqual(self.hits(), before)
        # the bare phrase shows the table; a bad phrase reports the error instead of sizing the message
        self.assertIn("Jev router models (", json.loads(self.hook("jev router model"))["modifiedTransformedPrompt"])
        self.assertIn("jev router model: unknown size",
                      json.loads(self.hook("jev router model huge x"))["modifiedTransformedPrompt"])
        self.assertEqual(self.hits(), before)
        self.assertEqual(self.adapter("size", "jev router model tiny x").stdout.strip(), "local - -")

    def test_broken_file_fails_open_for_the_hook_and_loud_for_the_command(self):
        with open(os.path.join(self.home, "models.json"), "w") as f:
            f.write('{"tiny": {"model": "NOT VALID"}}')
        self.set_router(True)
        out = self.hook(SIZE_PROMPT, url_query="size=large")
        self.assertIn(NOTE, out, "a broken models.json must not stop routing; the defaults apply")
        res = self.adapter("model")
        self.assertEqual(res.returncode, 2)
        self.assertIn("models.json", res.stderr)
        self.assertIn("not valid", res.stderr)

    def test_render_agents_is_complete_and_idempotent(self):
        out_dir = os.path.join(self.home, "out")
        first = self.adapter("render-agents", out_dir)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(sorted(os.listdir(out_dir)), [f"jev-{s}.agent.md" for s in
                                                       ("everyday", "hardest", "large", "tiny")])
        snapshot = {n: open(os.path.join(out_dir, n)).read() for n in os.listdir(out_dir)}
        for name, text in snapshot.items():
            self.assertNotIn("@", text.split("---")[1], f"{name}: placeholder left in the frontmatter")
            self.assertIn("model-policy: required", text)
        self.assertEqual(self.adapter("render-agents", out_dir).returncode, 0)
        self.assertEqual({n: open(os.path.join(out_dir, n)).read() for n in os.listdir(out_dir)}, snapshot)


@unittest.skipIf(os.name == "nt", "bash installer; see test_pwsh.py for install.ps1")
class InstalledCopyTests(unittest.TestCase):
    """The user's requirement: models can be changed after the router is installed, without re-installing."""

    def test_change_on_an_installed_copy_then_reinstall_keeps_it(self):
        home = tempfile.mkdtemp(prefix="jev-models-cp-")
        self.addCleanup(shutil.rmtree, home, True)
        env = {**os.environ, "COPILOT_HOME": home, "TYPESAFE_API_KEY": "test-key"}
        res = subprocess.run(["bash", INSTALL], env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        agent = os.path.join(home, "agents", "jev-hardest.agent.md")
        installed = os.path.join(home, "jev-router", "jev_copilot.py")
        with open(agent, encoding="utf-8") as f:
            self.assertIn("\nmodel: claude-opus-5.5\nreasoningEffort: high\n", f.read())
        self.assertTrue(os.path.exists(os.path.join(home, "jev-router", "agents", "jev-hardest.agent.md.tmpl")),
                        "templates are installed so a later change needs no checkout")
        # change it with the installed adapter only (no checkout, no COPILOT_HOME: the layout implies it)
        res = run([installed, "model", "hardest", "claude-sonnet-5.5", "--effort", "none"],
                  env={**os.environ, "TYPESAFE_API_KEY": "test-key"})
        self.assertEqual(res.returncode, 0, res.stderr)
        with open(agent, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("\nmodel: claude-sonnet-5.5\nmodel-policy: required\n", text)
        self.assertTrue(text.rstrip().endswith("— done by Claude Sonnet 5.5 (jev-hardest)"))
        with open(os.path.join(home, "jev-router", "models.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["hardest"]["model"], "claude-sonnet-5.5")
        # a re-install keeps the choice (models.json is never overwritten) and makes no agent backup
        res = subprocess.run(["bash", INSTALL], env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        with open(agent, encoding="utf-8") as f:
            self.assertIn("\nmodel: claude-sonnet-5.5\n", f.read())
        self.assertEqual([n for n in os.listdir(os.path.join(home, "agents")) if ".bak-" in n], [])
        res = subprocess.run(["bash", UNINSTALL], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(os.listdir(home), [])


if __name__ == "__main__":
    unittest.main()


def catalog_line(models, count=None):
    """One Copilot CLI log line in the real shape: the array is a JSON string inside the outer object."""
    body = json.dumps({"count": count if count is not None else len(models), "models": json.dumps(models),
                       "dynamic_auto_tiers": False})
    return "2026-11-02T07:58:59.658Z [DEBUG] [rust:capi_models] fetched model catalog from CAPI " + body


def entry(mid, category, efforts=(), name=None, price="medium", picker=True, preview=False):
    return {"id": mid, "name": name or mid, "vendor": "x", "preview": preview, "model_picker_enabled": picker,
            "model_picker_category": category, "model_picker_price_category": price,
            "capabilities": {"supports": {"reasoning_effort": list(efforts)} if efforts else {}}}


CATALOG = [
    entry("gpt-6.1-sol", "powerful", ("low", "medium", "high", "xhigh"), "GPT-6.1 Sol"),
    entry("claude-opus-5.5", "powerful", ("low", "medium", "high"), "Claude Opus 5.5", "high"),
    entry("gemini-4-argon", "powerful", ("low", "medium"), "Gemini 4 Argon"),   # no high effort: large only
    entry("claude-sonnet-5.5", "versatile", ("low", "medium", "high"), "Claude Sonnet 5.5"),
    entry("grok-4.6", "versatile", (), "Grok 4.6"),
    entry("gpt-5.6-luna", "lightweight", ("none", "low"), "GPT-5.6 Luna", "low"),
    entry("claude-haiku-5.5", "lightweight", ("low",), "Claude Haiku 5.5", "low"),
    entry("mai-code-2-flash", "lightweight", (), "MAI Flash", None, True, True),
    entry("gpt-4.1", "versatile", (), "GPT-4.1", picker=False),                  # not in the picker: hidden
    entry("text-embedding-3-small", None, (), "Embedding", picker=False),
    {"id": 7, "model_picker_enabled": True, "model_picker_category": "powerful"},  # malformed: skipped
]


class ModelsListTests(ModelsBase):
    def write_log(self, name, *lines):
        logs = os.path.join(self.home, "logs")
        os.makedirs(logs, exist_ok=True)
        path = os.path.join(logs, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return path

    def test_models_are_grouped_by_size_and_sorted_by_id(self):
        path = self.write_log("process-1793606325269-57657.log", "2026-11-02T07:58:59.000Z [INFO] session start",
                              catalog_line(CATALOG), "2026-11-02T07:59:00.000Z [INFO] done")
        res = self.adapter("models")
        self.assertEqual(res.returncode, 0, res.stderr)
        out = res.stdout
        self.assertIn(f"from {path}", out)
        ids = [m.group(1) for m in (re.match(r"^  [* ] (\S+)", line) for line in out.splitlines()) if m]
        self.assertEqual(ids, ["claude-haiku-5.5", "gpt-5.6-luna", "mai-code-2-flash",           # tiny, A-Z
                               "claude-sonnet-5.5", "grok-4.6",                                   # everyday
                               "claude-opus-5.5", "gemini-4-argon", "gpt-6.1-sol",                # large
                               "claude-opus-5.5", "gpt-6.1-sol"])                                 # hardest: high effort
        for hidden in ("gpt-4.1", "text-embedding-3-small"):
            self.assertNotIn(hidden, out)
        # the current choice per size is starred, the rest not
        self.assertRegex(out, r"\n  \* claude-haiku-5\.5 ")
        self.assertRegex(out, r"\n    gpt-5\.6-luna ")
        self.assertEqual(out.count("\n  * "), 4)
        self.assertIn("mai-code-2-flash   MAI Flash          price -, preview", out)
        self.assertIn("effort low/medium/high/xhigh", out)
        self.assertIn("hardest (powerful with reasoning effort high; set it with --effort high)", out)

    def test_star_follows_a_model_change_and_the_newest_log_with_a_catalog_wins(self):
        self.write_log("process-1000000000000-1.log", catalog_line([entry("old-model", "powerful", ("high",))]))
        new = self.write_log("process-2000000000000-2.log", catalog_line(CATALOG))
        self.write_log("process-3000000000000-3.log", "2026-11-02T08:00:00.000Z [INFO] no catalog here",
                       "2026-11-02T08:00:01.000Z [DEBUG] fetched model catalog from CAPI {not json")
        os.utime(new, (2000000000, 2000000000))
        for i, name in enumerate(("process-1000000000000-1.log", "process-3000000000000-3.log")):
            os.utime(os.path.join(self.home, "logs", name), (1000000000 + i, 1000000000 + i))
        self.assertEqual(self.adapter("model", "large", "gpt-6.1-sol").returncode, 0)
        out = self.adapter("models").stdout
        self.assertIn(f"from {new}", out)
        self.assertNotIn("old-model", out)
        self.assertRegex(out, r"\n  \* gpt-6\.1-sol ")
        self.assertRegex(out, r"\n    claude-opus-5\.5 .*price high")

    def test_chat_phrase_lists_models_without_calling_jev(self):
        self.write_log("process-1.log", catalog_line(CATALOG))
        self.set_router(True)
        before = self.hits()
        out = self.hook("jev router models")
        self.assertTrue(out, "the hook must answer the phrase")
        text = json.loads(out)["modifiedTransformedPrompt"]
        self.assertTrue(text.startswith(ECHO + "Copilot models your account can use"), text[:120])
        self.assertIn("  tiny (lightweight)", text)
        self.assertEqual(self.hits(), before)
        self.assertEqual(self.adapter("size", "jev router models").stdout.strip(), "local - -")

    def test_without_a_logged_catalog_the_fallback_explains_how_to_get_one(self):
        res = self.adapter("models")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("No model catalog found in " + os.path.join(self.home, "logs"), res.stdout)
        self.assertIn('"logLevel": "all"', res.stdout)
        self.assertNotIn("by Jev size", res.stdout)
        # a log without a usable catalog line is the same as no log
        self.write_log("process-1.log", "2026-11-02T08:00:01.000Z [DEBUG] fetched model catalog from CAPI {\"count\":0,\"models\":\"[]\"}")
        self.assertIn("No model catalog found", self.adapter("models").stdout)
