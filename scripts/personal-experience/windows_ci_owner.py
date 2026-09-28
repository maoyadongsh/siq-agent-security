"""CI only: create synthetic test objects as the runner user, never change files.

Elevated hosted runners default TokenOwner to Administrators. A normal user's
private state must belong to that user. Adjust only this process token's default
owner for child tests and restore it afterward; no privileges, groups, existing
ACLs, registry or product checks change.
https://learn.microsoft.com/windows/win32/secauthz/owner-of-a-new-object
"""

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes


def main():
    if os.name != "nt" or os.environ.get("GITHUB_ACTIONS") != "true" or len(sys.argv) < 2:
        raise SystemExit("requires a Windows Actions runner and a test command")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.SetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    advapi.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0080 | 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())

    def info(kind):
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, kind, None, 0, ctypes.byref(size))
        if not size.value or size.value > 65536:
            raise RuntimeError("invalid token information size")
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, kind, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer

    try:
        user, original = info(1), info(4)  # TOKEN_USER and TOKEN_OWNER start with PSID.
        owner = ctypes.c_void_p.from_buffer(user)
        prior = ctypes.c_void_p.from_buffer(original)
        print("ci_default_owner_was_current_user=" + str(bool(advapi.EqualSid(owner, prior))), flush=True)
        if not advapi.SetTokenInformation(token, 4, ctypes.byref(owner), ctypes.sizeof(owner)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            actual = info(4)
            if not advapi.EqualSid(owner, ctypes.c_void_p.from_buffer(actual)):
                raise RuntimeError("CI process default owner readback failed")
            return subprocess.run(sys.argv[1:], check=False).returncode
        finally:
            if not advapi.SetTokenInformation(token, 4, ctypes.byref(prior), ctypes.sizeof(prior)):
                raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(token)


if __name__ == "__main__":
    raise SystemExit(main())
