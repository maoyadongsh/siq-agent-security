"""Operator-owned model egress policy. No model output configures this boundary."""

import subprocess
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from .contracts import DataSensitivity


@dataclass(frozen=True)
class ModelCapabilities:
    locality: str
    allowed_sensitivity: tuple[DataSensitivity, ...]
    can_receive_raw_source: bool


REMOTE = ModelCapabilities("remote", (DataSensitivity.PUBLIC,), True)
LOCAL = ModelCapabilities("local_dgx", tuple(DataSensitivity), True)
FIXTURE = ModelCapabilities("fixture", tuple(DataSensitivity), True)


@dataclass(frozen=True)
class ModelPolicy:
    public_research_local: bool = False
    internal_remote: bool = False
    secret_local: bool = False


@dataclass(frozen=True)
class CallContext:
    task_id: str = "standalone"
    sensitivity: DataSensitivity = DataSensitivity.PUBLIC
    internal_remote: bool = False
    secret_local: bool = False


CALL_CONTEXT = ContextVar("siq_model_call", default=None)


def dgx_local_ready():
    """Fresh host/GPU check; neither provider name nor model text attests locality."""
    try:
        product = Path("/sys/devices/virtual/dmi/id/product_name").read_text().strip()
        if product not in ("NVIDIA_DGX_Spark", "NVIDIA DGX Spark"):
            return False
        result = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                                capture_output=True, text=True, timeout=5, check=False)
        return result.returncode == 0 and any("GB10" in line for line in result.stdout.splitlines())
    except (OSError, subprocess.SubprocessError):
        return False
