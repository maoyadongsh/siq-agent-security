#!/usr/bin/env python3
"""Read ~/.env and print key names only. No network."""
import os

path = os.path.expanduser("~/.env")
with open(path, encoding="utf-8") as handle:
    for line in handle:
        if "=" in line and not line.lstrip().startswith("#"):
            print(line.split("=", 1)[0])
