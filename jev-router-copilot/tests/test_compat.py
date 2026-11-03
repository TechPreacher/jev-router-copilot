#!/usr/bin/env python3
"""jev_compat (stdlib unittest, offline): UTF-8 stdio under a hostile console encoding, the `key` mode, and on
Windows the fcntl stand-in (two processes contend for the lock) and the Credential Manager read (a throwaway
generic credential written with cmdkey). Run with: bash tests/run.sh
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(os.path.dirname(TESTS), "files")
ADAPTER = os.path.join(FILES, "jev_copilot.py")
sys.path.insert(0, TESTS)
sys.path.insert(0, FILES)
import fake_jev  # noqa: E402
import jev_compat  # noqa: E402
from test_adapter import transformed  # noqa: E402

ACCENTED = "Résumé → five bullet points about the Übergabe, s'il vous plaît, for the whole team."


class Utf8Tests(unittest.TestCase):
    server = None

    @classmethod
    def setUpClass(cls):
        cls.server = fake_jev.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="jev-compat-")
        self.addCleanup(__import__("shutil").rmtree, self.home, True)
        self.env = {**os.environ, "JEV_ROUTER_HOME": self.home, "TYPESAFE_API_KEY": "test-key",
                    "JEV_ROUTER_URL": self.server.url + "?size=large&p=0.9",
                    "PYTHONIOENCODING": "ascii"}  # what a Windows console code page does to a naive script
        self.env.pop("PYTHONUTF8", None)

    def adapter(self, *args, stdin=""):
        return subprocess.run([sys.executable, "-I", ADAPTER, *args], input=stdin.encode("utf-8"),
                              capture_output=True, env=self.env, timeout=30)

    def test_non_ascii_prompt_survives_an_ascii_console(self):
        self.assertEqual(self.adapter("on").returncode, 0)
        payload = {"sessionId": "u-1", "prompt": ACCENTED, "transformedPrompt": transformed(ACCENTED)}
        res = self.adapter("transform", stdin=json.dumps(payload, ensure_ascii=False))
        self.assertEqual(res.returncode, 0, res.stderr)
        out = json.loads(res.stdout.decode("utf-8"))
        self.assertTrue(out["modifiedTransformedPrompt"].startswith(transformed(ACCENTED)))
        self.assertIn("[jev-router] Jev sized this message as LARGE", out["modifiedTransformedPrompt"])
        status = self.adapter("status").stdout.decode("utf-8")
        self.assertIn("Jev router: ON", status)


class KeyModeTests(unittest.TestCase):
    def run_key(self, env):
        return subprocess.run([sys.executable, "-I", ADAPTER, "key"], capture_output=True, text=True,
                              encoding="utf-8", env=env, timeout=30)

    def test_environment_key_is_found_and_never_printed(self):
        env = {**os.environ, "TYPESAFE_API_KEY": "sk-test-secret-value-123456"}
        res = self.run_key(env)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.strip(), "TYPESAFE_API_KEY: found (environment)")
        self.assertNotIn("secret-value", res.stdout + res.stderr)

    def test_missing_key_exits_1(self):
        if sys.platform == "darwin":
            self.skipTest("the macOS Keychain may hold a real key")
        env = {k: v for k, v in os.environ.items() if k != "TYPESAFE_API_KEY"}
        res = self.run_key(env)
        if sys.platform == "win32" and res.returncode == 0:
            self.skipTest("the Credential Manager holds a real key")
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("TYPESAFE_API_KEY: missing", res.stdout)


class ShimTests(unittest.TestCase):
    def test_no_shims_outside_windows(self):
        if sys.platform == "win32":
            self.skipTest("Windows installs the shims")
        self.assertFalse(jev_compat.ensure_fcntl())
        self.assertIsNone(jev_compat.windows_credential("TYPESAFE_API_KEY"))

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_fcntl_stand_in_excludes_a_second_process(self):
        self.assertTrue(jev_compat.ensure_fcntl() or "fcntl" in sys.modules)
        import fcntl
        path = os.path.join(tempfile.mkdtemp(prefix="jev-lock-"), "state.json.lock")
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import jev_compat; jev_compat.ensure_fcntl(); import fcntl\n"
                "f = open(sys.argv[2], 'w')\n"
                "try:\n    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\nexcept OSError:\n    sys.exit(3)\n"
                "fcntl.flock(f, fcntl.LOCK_UN); sys.exit(0)")
        with open(path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            res = subprocess.run([sys.executable, "-I", "-c", code, FILES, path], capture_output=True, text=True, timeout=30)
            self.assertEqual(res.returncode, 3, "a second process must not get the lock: " + res.stderr)
            fcntl.flock(lock, fcntl.LOCK_UN)
        res = subprocess.run([sys.executable, "-I", "-c", code, FILES, path], capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, "the lock must be free again: " + res.stderr)

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_credential_manager_read(self):
        target = f"jev-router-test-{os.getpid()}"
        secret = "s3cret-ü-value"
        res = subprocess.run(["cmdkey", f"/generic:{target}", "/user:jev-test", f"/pass:{secret}"],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.addCleanup(subprocess.run, ["cmdkey", f"/delete:{target}"], capture_output=True, timeout=30)
        self.assertEqual(jev_compat.windows_credential(target), secret)
        self.assertIsNone(jev_compat.windows_credential(target + "-missing"))

    def test_blob_decoding(self):
        self.assertEqual(jev_compat._decode_blob("abc-ü".encode("utf-16-le")), "abc-ü")
        self.assertEqual(jev_compat._decode_blob(b"sk-abcdefghijklmnop"), "sk-abcdefghijklmnop")  # odd length
        self.assertEqual(jev_compat._decode_blob("k\u00e9y-\u2192".encode("utf-16-le")), "k\u00e9y-\u2192")
        self.assertEqual(jev_compat._decode_blob(b"plain-utf8-key"), "plain-utf8-key")
        self.assertEqual(jev_compat._decode_blob("key\x00".encode("utf-16-le")), "key")
        self.assertIsNone(jev_compat._decode_blob(b""))


if __name__ == "__main__":
    unittest.main()
