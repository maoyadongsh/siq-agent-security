"""Evidence utilities for author-side evaluation; no product decision imports."""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def write_json(path: Path, value, *, exclusive=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def safe_path(root: Path, relative: str):
    name = Path(relative)
    if name.is_absolute() or ".." in name.parts or not name.parts:
        raise ValueError("invalid relative artifact path")
    current = root.resolve()
    for part in name.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symlink artifact forbidden")
    current.resolve().relative_to(root.resolve())
    return current


class Events:
    def __init__(self, path: Path, run_id: str):
        self.path, self.run_id = path, run_id
        if path.exists():
            raise ValueError("new event log required; interrupted actions must not replay")
        self.sequence = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(mode=0o600, exist_ok=False)

    def add(self, event: str, **fields):
        self.sequence += 1
        row = dict(run_id=self.run_id, sequence=self.sequence, event=event,
                   utc=utc_now(), monotonic_ns=time.monotonic_ns(), pid=os.getpid(), **fields)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(canonical(row).decode() + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return row


def clean_environment(temporary: Path | None = None):
    result = {key: os.environ[key] for key in
              ("PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT", "SSL_CERT_FILE") if key in os.environ}
    result.update(GOMAXPROCS="4", GOFLAGS="-p=4", PYTHONUNBUFFERED="1",
                  PYTHONDONTWRITEBYTECODE="1", UV_NO_PROGRESS="1")
    if temporary:
        temporary.mkdir(parents=True, exist_ok=True)
        result["TMPDIR"] = str(temporary)
    return result


def process_group_rss(pgid: int):
    total = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) == pgid:
                total += int(fields[21]) * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            continue
    return total


def run_command(events: Events, command_id: str, argv: list[str], cwd: Path,
                output: Path, *, timeout=1800, memory_mib=16384, env=None):
    """Capture every attempt and reap only our own process group, including errors."""
    output.mkdir(parents=True, exist_ok=True)
    stdout = output / f"{command_id}.stdout.log"
    stderr = output / f"{command_id}.stderr.log"
    events.add("command_started", command_id=command_id, argv=argv, cwd=str(cwd), timeout_seconds=timeout)
    started = time.monotonic()
    timed_out, failure, peak = False, None, 0
    process = None
    try:
        with stdout.open("xb") as out, stderr.open("xb") as err:
            process = subprocess.Popen(argv, cwd=cwd, env=env or clean_environment(),
                                       stdout=out, stderr=err, start_new_session=True)
            while process.poll() is None:
                elapsed = time.monotonic() - started
                peak = max(peak, process_group_rss(process.pid))
                if elapsed > timeout:
                    timed_out, failure = True, "timeout"
                    break
                if peak > memory_mib * 1024 * 1024:
                    failure = "memory_limit"
                    break
                if stdout.stat().st_size + stderr.stat().st_size > 128 * 1024 * 1024:
                    failure = "output_limit"
                    break
                time.sleep(0.25)
    except OSError as exc:
        failure = f"spawn_error:{type(exc).__name__}"
    finally:
        if process:
            # Daemons inherited the group. Never select processes by name or port.
            try:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    row = {"command_id": command_id, "argv": argv, "exit_code": process.returncode if process else None,
           "timed_out": timed_out, "error": failure, "duration_seconds": time.monotonic() - started,
           "peak_group_rss_bytes": peak, "stdout_sha256": sha256(stdout), "stderr_sha256": sha256(stderr)}
    events.add("command_finished", **row)
    return row
