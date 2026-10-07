"""Disposable process driver. Synthetic gateway state only; never a live CLI."""

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.adapters.openshell.contracts import AdapterError, DeploymentReceipt
from app.tests.test_durable_openshell_operations import apply, backend
from app.tests.test_openshell_policy_operations import StatefulRunner
from app.tests.test_sealed_snapshot import ORIGIN


def main():
    mode, database_url, directory = sys.argv[1:]
    assert database_url.startswith("sqlite:///")
    root = Path(directory)
    state_path, receipt_path = root / "gateway.json", root / "receipt.json"
    stored = json.loads(state_path.read_text()) if state_path.exists() else None
    runner = StatefulRunner(policy=stored["policy"] if stored else None,
                            revision=stored["revision"] if stored else 4)
    calls = stored["set_calls"] if stored else 0

    def execute(args):
        nonlocal calls
        result = runner(args)
        if args[:2] == ["policy", "set"]:
            calls += 1
            state_path.write_text(json.dumps({
                "policy": runner.policy, "revision": runner.revision, "set_calls": calls,
            }))
            if mode.startswith("crash-"):
                os._exit(73)  # Kernel closes locks; no Python cleanup/finally.
        return result

    engine = create_engine(database_url)
    try:
        adapter = backend(sessionmaker(bind=engine, expire_on_commit=False), execute)
        if mode.endswith("apply"):
            receipt_path.write_text(json.dumps(asdict(apply(adapter))))
        else:
            receipt = DeploymentReceipt(**json.loads(receipt_path.read_text()))
            adapter.rollback(ORIGIN.target, receipt, authorizer=lambda _: True)
    except AdapterError:
        sys.exit(74)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
