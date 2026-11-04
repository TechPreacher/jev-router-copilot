#!/usr/bin/env python3
"""Platform shims so the unchanged router core and the adapter also run on Windows.

jev_copilot.py calls prepare() before `import router`. Three jobs, each a no-op where it is not needed:

- fcntl: router.py locks state.json with fcntl.flock, which Windows lacks. On Windows a stand-in module is
  registered under that name, backed by msvcrt.locking on the same lock file.
- Secrets: router.py reads the environment, then the macOS Keychain, for TYPESAFE_API_KEY and the Azure
  backend values (JEV_AZURE_ENDPOINT, JEV_AZURE_DEPLOYMENT, JEV_AZURE_API_KEY). On Windows each can be a
  generic credential of that name in the Credential Manager (stored with cmdkey). They are read with
  CredReadW and put into the environment of this process only, where router.py finds them.
- UTF-8 stdio: Copilot sends and expects UTF-8 JSON. Python on Windows would otherwise use the console code
  page, so a prompt with an accent or an arrow would crash the hook or come out mangled.

Standard library only. Nothing here prints or logs the key.
"""
import os
import sys

KEY_NAME = "TYPESAFE_API_KEY"
NAMES = (KEY_NAME, "JEV_AZURE_ENDPOINT", "JEV_AZURE_DEPLOYMENT", "JEV_AZURE_API_KEY")
CRED_TYPE_GENERIC = 1
sources = {}  # name -> "environment" or "credential-manager", for the names load_secrets() found
key_source = None  # TYPESAFE_API_KEY's source, kept for older callers


def utf8_stdio():
    """UTF-8 on stdin/stdout/stderr regardless of the console code page. Must run before any read."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def ensure_fcntl():
    """Register a minimal fcntl module on Windows. Returns True when the shim was installed."""
    if sys.platform != "win32":
        return False
    try:
        import fcntl  # noqa: F401
        return False
    except ImportError:
        pass
    import msvcrt
    import types

    shim = types.ModuleType("fcntl")
    shim.LOCK_SH, shim.LOCK_EX, shim.LOCK_NB, shim.LOCK_UN = 1, 2, 4, 8

    def flock(fd, operation):
        """Lock or unlock the first byte of the file; router.py only ever locks a dedicated lock file."""
        fileno = fd.fileno() if hasattr(fd, "fileno") else fd
        if operation & shim.LOCK_UN:
            mode = msvcrt.LK_UNLCK
        elif operation & shim.LOCK_NB:
            mode = msvcrt.LK_NBLCK
        else:
            mode = msvcrt.LK_LOCK  # waits up to about ten seconds, then raises OSError
        os.lseek(fileno, 0, os.SEEK_SET)
        msvcrt.locking(fileno, mode, 1)

    shim.flock = flock
    sys.modules["fcntl"] = shim
    return True


def windows_credential(target):
    """The secret of the generic credential `target` from the Windows Credential Manager, or None."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                    ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
                    ("UserName", wintypes.LPWSTR)]

    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        cred_read = advapi32.CredReadW
        cred_read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
        cred_read.restype = wintypes.BOOL
        cred_free = advapi32.CredFree
        cred_free.argtypes = [ctypes.c_void_p]
        cred_free.restype = None
        pcred = ctypes.POINTER(CREDENTIAL)()
        if not cred_read(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
            return None
        try:
            size = pcred.contents.CredentialBlobSize
            blob = ctypes.string_at(pcred.contents.CredentialBlob, size) if size else b""
        finally:
            cred_free(pcred)
    except (OSError, AttributeError, ValueError):
        return None
    return _decode_blob(blob)


def _decode_blob(blob):
    """cmdkey and the Credential Manager UI store UTF-16LE; some tools store UTF-8.

    A UTF-16LE key made of Latin characters (every API key is) has a zero high byte in each pair; that is the
    tell. Anything else is tried as UTF-8 first, then as UTF-16LE.
    """
    if not blob:
        return None
    if len(blob) % 2 == 0 and not any(blob[1::2]):
        return blob.decode("utf-16-le").strip("\x00") or None
    for encoding in ("utf-8", "utf-16-le"):
        try:
            return blob.decode(encoding).strip("\x00") or None
        except UnicodeDecodeError:
            continue
    return None


def load_secrets():
    """Put Credential Manager values into os.environ for the names the environment lacks (Windows only)."""
    global key_source
    for name in NAMES:
        if os.environ.get(name):
            sources[name] = "environment"
            continue
        value = windows_credential(name)
        if value:
            os.environ[name] = value
            sources[name] = "credential-manager"
    key_source = sources.get(KEY_NAME)


load_api_key = load_secrets


def prepare():
    for step in (utf8_stdio, ensure_fcntl, load_secrets):
        try:
            step()
        except Exception:  # a shim must never take the hook down; the core fails open on its own
            pass
