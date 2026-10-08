"""Explicit host-only entry point for reverse verification and session control."""

import argparse
import importlib.util
import json
import os
import signal
import sys
import threading
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection", required=True, type=Path)
    parser.add_argument("--control", required=True, type=Path)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        return 2
    directory = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("siq_native_host_service", directory / "host_control.py",
                                                 submodule_search_locations=[str(directory)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    online = sys.modules[spec.name + ".host_online"]
    stopped = threading.Event()
    previous = {sig: signal.signal(sig, lambda *_: stopped.set()) for sig in (signal.SIGINT, signal.SIGTERM)}
    verifier = control = None
    try:
        verifier = online.Verifier(args.connection).start()
        control = module.HostControl(verifier, f"http://127.0.0.1:{args.port}", args.control).start()
        print(json.dumps({"schema_version": "native-host-service-ready/v1", "runtime_state": "unverified",
                          "pid": os.getpid()}), flush=True)
        while not stopped.wait(.5):
            control.assert_running()
        return 0
    except Exception:  # noqa: BLE001 - never expose config, tokens or system details.
        print("native_host_service_unavailable", file=sys.stderr)
        return 1
    finally:
        try:
            if control is not None:
                control.close()  # A failure must not close a Verifier still used by workers.
            if verifier is not None:
                verifier.close()
        except Exception:  # noqa: BLE001 - exit failure is distinct from confirmed cleanup.
            print("native_host_service_cleanup_unconfirmed", file=sys.stderr)
            # The OS closes descriptors on exit. This is not an assertion that
            # the business sandbox was recovered by its separate Supervisor.
            raise SystemExit(1) from None
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
