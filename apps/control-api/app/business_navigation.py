"""Configured business destinations; evidence never supplies an arbitrary URL."""

import json
import os
import re
from urllib.parse import urlsplit

from fastapi import HTTPException

LOCATOR = re.compile(r"siq://business-security-event/(sev_[0-9a-f]{64})\Z")


def _origin(tenant_id):
    try:
        raw = os.getenv("SIQ_AS_BUSINESS_WEB_ORIGINS", "{}")
        if len(raw) > 65536:
            raise ValueError("too_large")
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("duplicate_tenant")
                value[key] = item
            return value
        settings = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(settings, dict):
            raise ValueError("invalid_map")
        origin = settings.get(tenant_id)
        if origin is None:
            return None
        if not isinstance(origin, str) or not origin or any(ord(c) <= 32 or ord(c) >= 127 for c in origin):
            raise ValueError("invalid_origin")
        url = urlsplit(origin)
        if (url.scheme not in {"https", "http"} or not url.hostname or url.username is not None
                or url.password is not None or url.path not in {"", "/"} or url.query or url.fragment
                or any(c in origin for c in "\\%?#")
                or (url.scheme == "http" and url.hostname not in {"127.0.0.1", "[::1]", "::1"})
                or (url.port is not None and not 1 <= url.port <= 65535)):
            raise ValueError("invalid_origin")
        host = url.hostname
        if ":" in host:
            from ipaddress import IPv6Address
            host = f"[{IPv6Address(host).compressed}]"
        elif not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host):
            raise ValueError("invalid_host")
        port = url.port
        suffix = f":{port}" if port and port != (443 if url.scheme == "https" else 80) else ""
        return f"{url.scheme}://{host}{suffix}"
    except (ValueError, TypeError, RecursionError):
        raise HTTPException(503, "business_navigation_configuration_invalid") from None


def navigation(tenant_id, evidence):
    origin = _origin(tenant_id)
    items = []
    if origin:
        for item in evidence:
            match = LOCATOR.fullmatch(item.source_locator)
            if item.source_type == "gateway" and match:
                event_id = match[1]
                items.append(dict(evidence_id=item.evidence_id, event_id=event_id,
                                  href=f"{origin}/analysis/security-event?event_id={event_id}"))
    return dict(schema_version="siq.business-event-navigation/v1", configured=origin is not None, items=items)
