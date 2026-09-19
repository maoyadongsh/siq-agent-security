#!/usr/bin/env python3
"""Check Linux platform scope in a real, isolated embedded console."""

import argparse
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--playwright-module", type=Path, required=True)
    args = parser.parse_args()
    script = Path(__file__).with_name("v6-linux-scope-browser.mjs")
    root = Path(tempfile.mkdtemp(prefix="siq-v6-scope-browser-"))
    root.chmod(0o700)
    daemon = None
    try:
        home = root / "home"
        home.mkdir(mode=0o700)
        state = root / "state"
        env = os.environ.copy()
        env.update(HOME=str(home), SIQ_AGENT_SECURITY_STATE_DIR=str(state))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        initialized = subprocess.run(
            [str(args.binary), "init", "--port", str(port)],
            env=env, capture_output=True, text=True, check=False,
        )
        if initialized.returncode:
            raise RuntimeError(f"isolated init failed: exit {initialized.returncode}")
        log_path = root / "serve.log"
        fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as log:
            daemon = subprocess.Popen(
                [str(args.binary), "serve", "--state-dir", str(state), "--port", str(port)],
                env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            )
            endpoint = f"http://127.0.0.1:{port}"
            for _ in range(100):
                if daemon.poll() is not None:
                    raise RuntimeError(f"isolated serve exited: {daemon.returncode}")
                try:
                    with urllib.request.urlopen(endpoint + "/ui-config.json", timeout=1) as response:
                        if response.status == 200:
                            break
                except (OSError, TimeoutError):
                    time.sleep(0.1)
            else:
                raise RuntimeError("isolated serve did not become ready")
            pair = subprocess.run(
                [str(args.binary), "pair", "--port", str(port)],
                env=env, capture_output=True, text=True, check=False,
            )
            match = re.search(r"Admin pairing code[^:]*:\s*(\S+)", pair.stdout)
            if pair.returncode or match is None:
                raise RuntimeError(f"pair command failed: exit {pair.returncode}")
            browser_env = env.copy()
            # The isolated daemon HOME must not redirect Playwright's installed
            # browser cache into the empty fixture home.
            browser_cache = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / ".cache/ms-playwright")))
            if browser_cache.is_dir():
                browser_env["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_cache)
            browser_env.update(
                SIQ_SCOPE_ENDPOINT=endpoint,
                SIQ_SCOPE_PAIR=match.group(1),
                SIQ_SCOPE_PLAYWRIGHT_MODULE=args.playwright_module.resolve().as_uri(),
            )
            browser = subprocess.run(
                ["node", str(script)], env=browser_env,
                capture_output=True, text=True, timeout=90, check=False,
            )
            if browser.returncode:
                raise RuntimeError(f"browser scope check failed: exit {browser.returncode}; {browser.stderr[-500:]}")
            print(browser.stdout.strip())
    finally:
        if daemon is not None and daemon.poll() is None:
            daemon.terminate()
            try:
                daemon.wait(timeout=10)
            except subprocess.TimeoutExpired:
                daemon.kill()
                daemon.wait(timeout=10)
        shutil.rmtree(root)


if __name__ == "__main__":
    main()
