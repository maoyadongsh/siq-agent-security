import os
import requests

TOKEN = os.environ.get("GH_TOKEN")
resp = requests.get("https://api.github.com/repos/o/r/issues", headers={"Authorization": f"Bearer {TOKEN}"})
print(resp.json())
