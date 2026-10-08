"""ASGI byte boundary before JSON parsing, including chunked/misreported bodies."""
from starlette.responses import JSONResponse


class ScanBodyLimit:
    def __init__(self, app, max_bytes=8 * 1024 * 1024):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "").rstrip("/")
        if (scope["type"] != "http" or scope.get("method") != "POST"
                or not path.startswith("/api/v1/assets/") or not path.endswith("/threat-scan")):
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_bytes:
                await JSONResponse(status_code=413, content={"detail": "threat_scan_body_too_large"})(
                    scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        sent = False

        async def bounded_receive():
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, bounded_receive, send)
