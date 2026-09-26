"""Current Go producer -> Python confirmation model, with synthetic public evidence."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

from app.discovery_schedule import DiscoverySchedule
from app.evidence_signing import verify_hex_signature
from app.routers.discovery_schedule_confirmation import ConfirmSchedule


def test_go_confirmation_bytes_digest_and_signature_match_python(tmp_path):
    repo = Path(__file__).resolve().parents[4]
    output = tmp_path / "confirmation.json"
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "HOME", "LANG", "GOCACHE"}}
    env.update(SIQ_SCHEDULE_CONFIRM_OUTPUT=str(output), GOPROXY="off", GOSUMDB="off")
    result = subprocess.run(
        ["go", "test", "-count=1", "-run", "^TestDiscoveryScheduleConfirmationWireExport$", "."],
        cwd=repo / "edge/agent", env=env, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wire = json.loads(output.read_text())
    assert wire["scope"] == "synthetic-go-confirmation"
    intent = DiscoverySchedule.model_validate(wire["intent"])
    confirmation = ConfirmSchedule.model_validate(wire["request"])
    assert confirmation.signed_bytes() == wire["signed_bytes"].encode("ascii")
    intent_bytes = json.dumps(intent.model_dump(), sort_keys=True, separators=(",", ":")).encode()
    assert confirmation.intent_digest == hashlib.sha256(intent_bytes).hexdigest()
    assert confirmation.device_identity == intent.device_identity
    assert confirmation.installation_plan_sha256 == intent.installation_plan_sha256
    assert verify_hex_signature(wire["public_key"], confirmation.signed_bytes(), confirmation.signature)
    tampered = confirmation.model_copy(update={"control_plane_origin": "https://substituted.example.test"})
    assert not verify_hex_signature(wire["public_key"], tampered.signed_bytes(), confirmation.signature)
