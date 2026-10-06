"""Loopback receiver-owned delivery events with a per-case nonce."""
import hashlib
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class ReceiverOracle:
    def __init__(self, case_id, nonce, *, timestamped=False):
        self.case_id, self.nonce, self.events = case_id, nonce, []
        self.rejected = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                self.send_response(204 if self.path == "/health" else 404)
                self.end_headers()

            def do_POST(self):
                if self.path != "/receive/" + owner.nonce:
                    owner.rejected += 1
                    self.send_response(403)
                    self.end_headers()
                    return
                try:
                    size = int(self.headers.get("Content-Length", "-1"))
                except ValueError:
                    size = -1
                if not 0 <= size <= 65536:
                    self.send_response(413)
                    self.end_headers()
                    return
                body = self.rfile.read(size)
                if len(body) != size:
                    self.send_response(400)
                    self.end_headers()
                    return
                owner.events.append({"event_id": len(owner.events) + 1, "case_id": owner.case_id,
                                     "nonce": owner.nonce, "body_sha256": hashlib.sha256(body).hexdigest(),
                                     "received_bytes": len(body)})
                if timestamped:
                    owner.events[-1].update(received_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                                            monotonic_ns=time.monotonic_ns(), method='POST', uri=self.path)
                self.send_response(204)
                self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}"
        self.url = self.endpoint + "/receive/" + nonce
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def finish(self, *, background_stopped=True):
        healthy = False
        try:
            client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with client.open(self.endpoint + "/health", timeout=2) as response:
                healthy = response.status == 204
        finally:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=3)
        return {"schema_version": "siq-receiver-oracle/v1", "case_id": self.case_id, "nonce": self.nonce,
                "events": list(self.events), "rejected_requests": self.rejected,
                "healthy": healthy and background_stopped and not self.thread.is_alive(),
                "source": "evaluator_controlled_receiver", "same_uid_tamper_resistance": False}
