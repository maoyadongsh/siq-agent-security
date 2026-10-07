"""Fixed, same-process entry to the pinned Hermes gateway after initialization."""

import json
import os
import sys

from .native_bootstrap import ImageBootstrap

MARKER = "SIQ_NATIVE_GATEWAY_READY="


def main():
    bootstrap = None
    try:
        if len(sys.argv) != 4 or any(key.startswith("SIQ_AGENT_SECURITY_") for key in os.environ):
            raise ValueError("native_gateway_input_invalid")
        bootstrap = ImageBootstrap(*sys.argv[1:])
        print(MARKER + json.dumps(bootstrap.ready(), separators=(",", ":"), allow_nan=False), flush=True)
        bootstrap.configure(timeout=60)
        # Keep /proc argv intact and use the existing dedicated gateway entry.
        # Import only after configuration; never accept a caller-selected module.
        sys.argv = ["gateway/run.py"]
        from gateway.run import main as gateway_main

        result = gateway_main()
        return 0 if result is None else result if type(result) is int and 0 <= result <= 255 else 1
    except SystemExit as error:
        return 0 if error.code is None else error.code if type(error.code) is int and 0 <= error.code <= 255 else 1
    except BaseException:  # noqa: BLE001 - cancellation also closes the boundary.
        print("native_gateway_unavailable", file=sys.stderr, flush=True)
        return 1
    finally:
        if bootstrap is not None:
            bootstrap.close()
