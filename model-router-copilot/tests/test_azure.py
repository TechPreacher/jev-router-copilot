#!/usr/bin/env python3
"""Azure Decision-1 backend (stdlib unittest, offline): URL normalisation, backend selection, the token cache,
the hook's fail-open-then-refresh path with a stub `az` on PATH, the api-key header, status and `key` output.
The only server is tests/fake_jev.py on 127.0.0.1, standing in for a Foundry deployment. Run with: bash tests/run.sh
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(os.path.dirname(TESTS), "files")
ADAPTER = os.path.join(FILES, "router_copilot.py")
ROUTER = os.path.join(FILES, "router.py")
sys.path.insert(0, TESTS)
sys.path.insert(0, FILES)
import fake_jev  # noqa: E402
import router_compat  # noqa: E402

router_compat.ensure_fcntl()  # the core imports fcntl at the top; on Windows the adapter's shim stands in
# router reads MODEL_ROUTER_HOME at import; point it at a scratch dir for the unit tests without leaving the
# variable in this process (other test modules build subprocess environments from os.environ).
_prev_home = os.environ.get("MODEL_ROUTER_HOME")
os.environ["MODEL_ROUTER_HOME"] = tempfile.mkdtemp(prefix="router-azure-unit-")
try:
    import router  # noqa: E402
finally:
    if _prev_home is None:
        del os.environ["MODEL_ROUTER_HOME"]
    else:
        os.environ["MODEL_ROUTER_HOME"] = _prev_home
from test_adapter import transformed  # noqa: E402

PROMPT = "Research the main options for migrating our reporting from Postgres to ClickHouse and write a report."
STUB_TOKEN = "stub-azure-token"
FAR_FUTURE = 4102444800  # 2100-01-01
AZ_JSON = json.dumps({"accessToken": STUB_TOKEN, "expires_on": FAR_FUTURE, "tokenType": "Bearer"})


def make_az_stub(directory):
    """A fake `az` that prints a token JSON; `az.cmd` on Windows, a sh script elsewhere."""
    if os.name == "nt":
        path = os.path.join(directory, "az.cmd")
        with open(path, "w") as f:
            f.write("@echo off\r\necho " + AZ_JSON + "\r\n")
    else:
        path = os.path.join(directory, "az")
        with open(path, "w") as f:
            f.write("#!/bin/sh\nprintf '%s\\n' '" + AZ_JSON + "'\n")
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


class UnitTests(unittest.TestCase):
    def test_url_normalisation(self):
        want = "https://x.services.ai.azure.com/providers/microsoft/v1/systemone"
        for given in ("https://x.services.ai.azure.com", "https://x.services.ai.azure.com/",
                      "https://x.services.ai.azure.com/providers/microsoft",
                      "https://x.services.ai.azure.com/providers/microsoft/",
                      "https://x.services.ai.azure.com/providers/microsoft/v1/systemone"):
            self.assertEqual(router.azure_url(given), want, given)

    def test_backend_selection(self):
        base = {"MODEL_ROUTER_AZURE_ENDPOINT": "https://x.services.ai.azure.com", "MODEL_ROUTER_AZURE_DEPLOYMENT": "Decision-1"}
        with mock.patch.dict(os.environ, base, clear=False):
            os.environ.pop("MODEL_ROUTER_BACKEND", None)
            kind, azure = router.backend()
            self.assertEqual(kind, "azure")
            self.assertEqual(azure["deployment"], "Decision-1")
            self.assertTrue(azure["url"].endswith("/providers/microsoft/v1/systemone"))
        with mock.patch.dict(os.environ, {**base, "MODEL_ROUTER_BACKEND": "typesafe"}, clear=False):
            self.assertEqual(router.backend(), ("typesafe", None))
        with mock.patch.dict(os.environ, {"MODEL_ROUTER_AZURE_ENDPOINT": "https://x", "MODEL_ROUTER_AZURE_DEPLOYMENT": ""}, clear=False):
            if sys.platform != "darwin":  # the macOS Keychain could hold a real deployment name
                self.assertEqual(router.backend(), ("typesafe", None))

    def test_token_cache_is_owner_only_and_round_trips(self):
        home = tempfile.mkdtemp(prefix="router-azure-cache-")
        self.addCleanup(shutil.rmtree, home, True)
        with mock.patch.object(router, "HOME", home), \
                mock.patch.object(router, "AZURE_TOKEN_FILE", os.path.join(home, "azure-token.json")):
            router.write_token_cache("t0k", 1234567890.0)
            self.assertEqual(router.read_token_cache(), ("t0k", 1234567890.0))
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(os.stat(router.AZURE_TOKEN_FILE).st_mode), 0o600)
            with open(router.AZURE_TOKEN_FILE, "w") as f:
                f.write("not json")
            self.assertEqual(router.read_token_cache(), (None, 0.0))
            router.write_token_cache("t1", 1.0)
            self.assertEqual([n for n in os.listdir(home) if n != "azure-token.json"], [], "no temp files left behind")

    def test_state_lock_works_without_fcntl(self):
        """The core locks state.json with flock where it exists and msvcrt on Windows; both paths must round-trip."""
        home = tempfile.mkdtemp(prefix="router-azure-lock-")
        self.addCleanup(shutil.rmtree, home, True)
        with mock.patch.object(router, "HOME", home), mock.patch.object(router, "STATE", os.path.join(home, "state.json")):
            with router.locked_state() as s:
                s["enabled"] = True
            self.assertTrue(router.read_state()["enabled"])
            self.assertTrue(os.path.exists(os.path.join(home, "state.json.lock")))


class AzureHookTests(unittest.TestCase):
    """The adapter against a fake Decision-1 deployment, with a stub az on PATH and no TypeSafe key at all."""
    server = None

    @classmethod
    def setUpClass(cls):
        cls.server = fake_jev.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="router-azure-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.stub_dir = os.path.join(self.home, "stub")
        os.makedirs(self.stub_dir)
        make_az_stub(self.stub_dir)
        self.cache = os.path.join(self.home, "azure-token.json")
        self.server.size, self.server.p = "large", 0.9

    def env(self, az=True, **extra):
        env = {k: v for k, v in os.environ.items()
               if k not in ("TYPESAFE_API_KEY", "MODEL_ROUTER_AZURE_API_KEY", "MODEL_ROUTER_AZURE_TOKEN", "MODEL_ROUTER_BACKEND", "MODEL_ROUTER_URL")}
        env["MODEL_ROUTER_HOME"] = self.home
        env["MODEL_ROUTER_AZURE_ENDPOINT"] = self.server.url.replace("/v1/systemone", "/fake-foundry")
        env["MODEL_ROUTER_AZURE_DEPLOYMENT"] = "decision-test"
        if az:
            env["PATH"] = self.stub_dir + os.pathsep + os.environ.get("PATH", "")
        else:  # no az at all, not even a real one
            env["PATH"] = os.pathsep.join(d for d in os.environ.get("PATH", "").split(os.pathsep)
                                          if d and not shutil.which("az", path=d))
        env.update(extra)
        return env

    def adapter(self, *args, stdin="", **env_extra):
        return subprocess.run([sys.executable, "-I", ADAPTER, *args], input=stdin, capture_output=True, text=True,
                              encoding="utf-8", env=self.env(**env_extra), timeout=60)

    def hook(self, **env_extra):
        payload = {"sessionId": "az-1", "prompt": PROMPT, "transformedPrompt": transformed(PROMPT)}
        res = self.adapter("transform", stdin=json.dumps(payload), **env_extra)
        self.assertEqual(res.returncode, 0, res.stderr)
        return res.stdout

    def state(self):
        with open(os.path.join(self.home, "state.json")) as f:
            return json.load(f)

    def wait_for_cache(self, predicate, seconds=10):
        deadline = time.time() + seconds
        while time.time() < deadline:
            token, expires_on = self.read_cache()
            if predicate(token, expires_on):
                return True
            time.sleep(0.1)
        return False

    def read_cache(self):
        try:
            with open(self.cache) as f:
                data = json.load(f)
            return data.get("token"), float(data.get("expires_on", 0))
        except (OSError, ValueError):
            return None, 0.0

    def test_on_warms_the_token_and_the_hook_routes_through_the_deployment(self):
        res = self.adapter("on")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("backend: Microsoft Decision-1", res.stdout)
        self.assertNotIn("fake-foundry", res.stdout)  # the endpoint is a secret
        self.assertNotIn("decision-test", res.stdout)  # so is the deployment
        self.assertEqual(self.read_cache()[0], STUB_TOKEN, "`on` warmed the cache through az")
        before = self.server.hits
        out = self.hook()
        self.assertIn("[model-router] Sized as LARGE", json.loads(out)["modifiedTransformedPrompt"])
        self.assertEqual(self.server.hits, before + 1)
        self.assertTrue(self.server.last_path.endswith("/fake-foundry/providers/microsoft/v1/systemone"), self.server.last_path)
        self.assertEqual(self.server.last_body["model"], "decision-test")
        self.assertEqual(self.server.last_headers.get("authorization"), f"Bearer {STUB_TOKEN}")
        self.assertNotIn("api-key", self.server.last_headers)
        with open(os.path.join(self.home, "decisions.log")) as f:
            self.assertEqual(json.loads(f.readlines()[-1])["backend"], "azure")

    def test_hook_without_a_cached_token_fails_open_once_and_refreshes_in_the_background(self):
        self.adapter("on", az=False)  # no az on PATH: `on` reports it cannot warm, state is still ON
        self.assertFalse(os.path.exists(self.cache))
        before = self.server.hits
        self.assertEqual(self.hook(), "")  # fail open: nothing printed, message unchanged
        self.assertEqual(self.server.hits, before)
        self.assertIn("Azure token not cached", self.state()["last_error"])
        self.assertTrue(self.wait_for_cache(lambda t, e: t == STUB_TOKEN), "a detached refresh filled the cache")
        self.assertIn("LARGE", self.hook())
        self.assertEqual(self.server.hits, before + 1)

    def test_token_close_to_expiry_is_used_and_refreshed_in_the_background(self):
        self.adapter("on", az=False)
        soon = time.time() + 300  # under AZURE_REFRESH_S, above AZURE_MIN_LEFT_S
        with open(self.cache, "w") as f:
            json.dump({"token": "old-token", "expires_on": soon}, f)
        self.assertIn("LARGE", self.hook())
        self.assertEqual(self.server.last_headers.get("authorization"), "Bearer old-token")
        self.assertTrue(self.wait_for_cache(lambda t, e: t == STUB_TOKEN and e == FAR_FUTURE))

    def test_api_key_header_needs_no_token(self):
        self.adapter("on", az=False, MODEL_ROUTER_AZURE_API_KEY="k-1234")
        self.assertFalse(os.path.exists(self.cache))
        self.assertIn("LARGE", self.hook(az=False, MODEL_ROUTER_AZURE_API_KEY="k-1234"))
        self.assertEqual(self.server.last_headers.get("api-key"), "k-1234")
        self.assertNotIn("authorization", self.server.last_headers)
        self.assertFalse(os.path.exists(self.cache))

    def test_typesafe_override_wins_over_azure_settings(self):
        res = self.adapter("status", MODEL_ROUTER_BACKEND="typesafe")
        self.assertIn("backend: TypeSafe Jev", res.stdout)

    def test_key_mode_reports_the_azure_names_without_values(self):
        res = self.adapter("key")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("MODEL_ROUTER_AZURE_ENDPOINT: found (environment)", res.stdout)
        self.assertIn("MODEL_ROUTER_AZURE_DEPLOYMENT: found (environment)", res.stdout)
        self.assertIn("MODEL_ROUTER_AZURE_API_KEY: not set", res.stdout)
        self.assertIn("Azure token:", res.stdout)
        self.assertNotIn("fake-foundry", res.stdout)
        self.assertNotIn("decision-test", res.stdout)
        res = self.adapter("key", az=False)
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("az CLI not on PATH", res.stdout)
        res = self.adapter("key", az=False, MODEL_ROUTER_AZURE_TOKEN="env-token-value")
        self.assertEqual(res.returncode, 0, res.stdout)  # a static token in the environment is a valid setup
        self.assertIn("Azure token: MODEL_ROUTER_AZURE_TOKEN (environment)", res.stdout)
        self.assertNotIn("env-token-value", res.stdout)

    def test_size_mode_waits_for_the_token(self):
        """routercp's size mode is not the hook: it may call az and wait."""
        self.adapter("on", az=False)
        self.assertFalse(os.path.exists(self.cache))
        res = self.adapter("size", PROMPT)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(res.stdout.startswith("large "), res.stdout)
        self.assertEqual(self.read_cache()[0], STUB_TOKEN)


if __name__ == "__main__":
    unittest.main()
