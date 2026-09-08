"""Small, redacted runtime probe for the existing competition dashboard."""

import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request

from .contracts import strict_json


def source_identity(repo):
    try:
        candidate = repo.parent / 'source-info.json'
        if candidate.is_file() and not candidate.is_symlink():
            value = strict_json(candidate.read_bytes())
            if value.get('schema_version') == 'hackathon-rc-source/v2':
                return {'source_sha': value['git_sha'], 'source_dirty': False}
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True, stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo, stderr=subprocess.DEVNULL))
        return {'source_sha': commit, 'source_dirty': dirty}
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return {'source_sha': 'UNVERIFIED', 'source_dirty': None}


class HardwareStatus:
    def __init__(self, router, daemon):
        self.router, self.daemon = router, daemon
        self._at, self._record = 0, {}

    def snapshot(self):
        # DemoService serializes snapshots under its existing lock. Probe at most
        # every 30 seconds, without adding another polling API or background daemon.
        if time.monotonic() - self._at < 30:
            return dict(self._record)
        record = {"product": "UNVERIFIED", "gpu": "UNVERIFIED", "model": "UNVERIFIED",
                  "local_model_status": "UNVERIFIED", "local_inference": "UNVERIFIED",
                  "runtime": "READY" if self.daemon._proc and self.daemon._proc.poll() is None else "UNAVAILABLE",
                  "checked_at": datetime.now(timezone.utc).isoformat(), "inference_duration_ms": None}
        try:
            product = Path("/sys/devices/virtual/dmi/id/product_name").read_text().strip()
            gpu = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                                 capture_output=True, text=True, timeout=2, check=False)
            verified = product in ("NVIDIA_DGX_Spark", "NVIDIA DGX Spark") and gpu.returncode == 0 and "GB10" in gpu.stdout
            if verified:
                record.update(product=product, gpu="NVIDIA GB10")
            local = self.router._local() if self.router else None
            if local and local.capabilities.locality == "local_dgx":
                record["model"] = local.model
                headers = {"Authorization": "Bearer " + local._key} if local._key else {}
                with local._http.open(Request(local.endpoint.removesuffix('/chat/completions') + '/models', headers=headers),
                                      timeout=2) as response:
                    value = strict_json(response.read(65537))
                listed = isinstance(value, dict) and any(isinstance(m, dict) and m.get('id') == local.model
                                                         for m in value.get('data', []) if isinstance(value.get('data'), list))
                record["local_model_status"] = "READY" if verified and listed else "UNAVAILABLE"
                calls = [c for c in self.router.calls if c.get('locality') == 'local_dgx']
                if calls and verified and listed:
                    record['local_inference'] = 'READY' if calls[-1]['status'] == 'accepted' else 'UNAVAILABLE'
                    record['inference_duration_ms'] = calls[-1]['elapsed_ms']
        except Exception:  # noqa: BLE001 -- hardware and HTTP response details are not diagnostics
            record['local_model_status'] = 'UNAVAILABLE'
        self._at, self._record = time.monotonic(), record
        return dict(record)
