"""Synthetic session for loopback browser fixtures, never bundled into the UI.

Only attach this to isolated component/business fixture pages. This is not
production IAM coverage. API authorization remains the fixture's own route or
its explicit least-privilege development headers.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

_REFRESH = re.compile(r"^http://127\.0\.0\.1:[0-9]+/api/iam/api/v1/auth/refresh$")


def install_fixture_session(page):
    def refresh(route):
        request = route.request
        url = urlsplit(request.url)
        if (url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port
                or request.method != "POST" or url.path != "/api/iam/api/v1/auth/refresh"):
            route.abort()
            return
        route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"access_token": "synthetic-browser-fixture-not-a-real-token"}),
        )

    page.route(_REFRESH, refresh)
