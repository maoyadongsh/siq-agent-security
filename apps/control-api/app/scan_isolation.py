"""Minimal Linux namespace launcher; development process mode has resource limits only."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from app.scan_transport import ScanFailure


def command(mode, *, code=None):
    executable = os.path.abspath(sys.executable)
    root = str(Path(__file__).resolve().parent.parent)
    bootstrap = code or "from app.scan_worker import main; main()"
    if mode == "process":
        return [executable, "-I", "-B", "-c", f"import sys; sys.path.insert(0, {root!r}); {bootstrap}"]
    if mode != "bwrap" or sys.platform != "linux":
        raise ScanFailure("threat_scan_isolation_unavailable")
    bwrap = shutil.which("bwrap", path="/usr/bin:/bin")
    if not bwrap:
        raise ScanFailure("threat_scan_isolation_unavailable")
    argv = [bwrap, "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
            "--clearenv", "--setenv", "LANG", "C.UTF-8",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--chdir", "/tmp"]
    mounts = {
        "/usr/lib": "/usr/lib", "/lib": "/lib",
        str(Path(sys.base_prefix) / "lib"): str(Path(sys.base_prefix) / "lib"),
        str(Path(sys.prefix) / "lib"): str(Path(sys.prefix) / "lib"),
        str(Path(__file__).resolve().parent): "/scan/app",
    }
    for source, destination in mounts.items():
        if Path(source).is_dir():
            argv += ["--ro-bind", source, destination]
    cfg = Path(sys.prefix) / "pyvenv.cfg"
    if cfg.is_file():
        argv += ["--ro-bind", str(cfg), str(cfg)]
    argv += ["--ro-bind", str(Path(executable).resolve()), executable,
             "--remount-ro", "/tmp", "--remount-ro", "/", "--", executable, "-I", "-B", "-c",
             f"import sys; sys.path.insert(0, '/scan'); {bootstrap}"]
    return argv
