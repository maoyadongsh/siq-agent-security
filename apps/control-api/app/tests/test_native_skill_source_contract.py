"""Validate real snapshot-producer metadata, without enabling a runtime host."""

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, ValidationError

ROOT = Path(__file__).resolve().parents[4]
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux native source producer")


def test_actual_source_producer_contract(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "source_contract_producer", ROOT / "adapters/runtime/hermes-agentshield/native_source.py"
    )
    source = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(source)
    main = tmp_path / "SKILL.md"
    main.write_bytes(b"\xef\xbb\xbfSynthetic source\r\n")
    support = tmp_path / "reference.md"
    support.write_bytes(b"Reference\xff\n")
    events = []
    reader = source.SkillSourceReader(events.append)
    reader.read(main)
    reader.read(main, support)
    reader.read(main, support, cache_hit=True)
    schema = json.loads((ROOT / "packages/contracts/native-skill-source.v1.schema.json").read_text())
    Draft7Validator.check_schema(schema)
    validator = Draft7Validator(schema)
    for event in events:
        validator.validate(event)
        for field in schema["required"]:
            with pytest.raises(ValidationError):
                validator.validate({key: value for key, value in event.items() if key != field})
    event = events[0]
    for patch in [{"allow": True}, {"schema_version": "native-skill-source/v0"}, {"cache_hit": 1},
                  {"decoding": "unspecified"}, {"text_sha256": "A" * 64}, {"text_sha256": "a" * 63},
                  {"content_file": None}, {"skill_file": {}}, {"text": "private"}]:
        with pytest.raises(ValidationError):
            validator.validate(event | patch)
    for field in ("skill_file", "content_file"):
        for patch in [{"bytes": True}, {"bytes": -1}, {"bytes": 1048577}, {"bytes": 1.5},
                      {"sha256": "A" * 64}, {"path_sha256": "no-path"}, {"path": "/private/SKILL.md"}]:
            bad = copy.deepcopy(event)
            bad[field].update(patch)
            with pytest.raises(ValidationError):
                validator.validate(bad)
