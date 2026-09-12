"""Validate nonsecret SonarCloud parameters before a CI scan."""

from collections.abc import Mapping
import json
import os
import re
import sys


IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,255}")


def cloud_parameters(env: Mapping[str, str]) -> dict[str, str]:
    """Return validated public identifiers; never inspect authentication tokens."""
    if env.get("SONAR_HOST_URL", "") != "":
        raise ValueError("SONAR_HOST_URL")
    result = {}
    for field, output in (
        ("SONAR_ORGANIZATION", "organization"),
        ("SONAR_PROJECT_KEY", "project_key"),
    ):
        value = env.get(field, "")
        if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
            raise ValueError(field)
        result[output] = value
    region = env.get("SONAR_REGION", "")
    if region not in ("", "eu", "us"):
        raise ValueError("SONAR_REGION")
    result["region"] = "us" if region == "us" else ""
    return result


def main() -> int:
    try:
        parameters = cloud_parameters(os.environ)
    except ValueError as error:
        print(f"invalid configuration: {error}", file=sys.stderr)
        return 1
    output = os.environ.get("GITHUB_OUTPUT", "")
    if not output:
        print(json.dumps(parameters, sort_keys=True))
        return 0
    try:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write("".join(f"{key}={value}\n" for key, value in parameters.items()))
    except (OSError, ValueError):
        print("invalid configuration: GITHUB_OUTPUT", file=sys.stderr)
        return 1
    print("configuration validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
