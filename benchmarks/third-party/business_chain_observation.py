"""Observe the original receiver without replacing its business handler."""
import hashlib
import io
import json
import threading
import time
from urllib.request import ProxyHandler, Request, build_opener

from common import canonical


def observe_fixture(base, events, wire, health):
    class ObservedFixture(base):
        def __init__(self, *args, **kwargs):
            self.collector_condition = threading.Condition()
            self.collector_active = 0
            super().__init__(*args, **kwargs)

        def _handler(self):
            parent = super()._handler()
            service = self

            class Handler(parent):
                def send_response(self, code, message=None):
                    self.observed_status = code
                    return super().send_response(code, message)

                def do_POST(self):
                    if not self.path.startswith('/messages/'):
                        return super().do_POST()
                    with service.collector_condition:
                        service.collector_active += 1
                    try:
                        return self.observed_post()
                    finally:
                        with service.collector_condition:
                            service.collector_active -= 1
                            service.collector_condition.notify_all()

                def observed_post(self):
                    started = time.monotonic_ns()
                    raw = self.rfile.read(int(self.headers['Content-Length']))
                    original = self.rfile
                    self.rfile = io.BytesIO(raw)
                    try:
                        return super().do_POST()
                    finally:
                        self.rfile = original
                        row = {'path': self.path, 'action_id': self.headers.get('X-SIQ-Action-ID'),
                               'status': getattr(self, 'observed_status', None),
                               'request_sha256': hashlib.sha256(raw).hexdigest(),
                               'received_ns': started, 'finished_ns': time.monotonic_ns(),
                               'payload_sha256': None, 'parse_error': None}
                        try:
                            body = json.loads(raw)['body']
                            row['payload_sha256'] = hashlib.sha256(body.encode()).hexdigest()
                        except (ValueError, KeyError, TypeError, AttributeError) as exc:
                            row['parse_error'] = type(exc).__name__
                        wire.append(row)
                        events.add('receiver_request', **row)
            return Handler

        def health_check(self, stage):
            try:
                client = build_opener(ProxyHandler({}))
                with client.open(Request(self.endpoint + '/messages', headers=self.headers()), timeout=2) as response:
                    okay = response.status == 200 and isinstance(json.loads(response.read())['messages'], list)
            except Exception:  # noqa: BLE001 -- errors are an unhealthy observation
                okay = False
            health[stage] = okay
            events.add('receiver_health', stage=stage, healthy=okay)
            return okay

        def __enter__(self):
            result = super().__enter__()
            health['window_start_ns'] = time.monotonic_ns()
            self.health_check('before')
            return result

        def __exit__(self, *args):
            self.health_check('after')
            try:
                return super().__exit__(*args)
            finally:
                with self.collector_condition:
                    drained = self.collector_condition.wait_for(lambda: self.collector_active == 0, timeout=2)
                health['closed'] = not self.thread.is_alive() and drained
                health['window_end_ns'] = time.monotonic_ns()
                events.add('receiver_closed', confirmed=health['closed'])
    return ObservedFixture


def serialize_events(events):
    lock = threading.Lock()
    original = events.add

    def add(*args, **kwargs):
        with lock:
            return original(*args, **kwargs)
    events.add = add
    return events


def calibrate(benchmark, events):
    wire, health = [], {}
    observed = observe_fixture(benchmark.FixtureServices, events, wire, health)
    counts = [0]
    with observed(benchmark.ROOT / 'demo/fixtures') as fixture:
        route = '/messages/' + hashlib.sha256(canonical(fixture.contacts['Alice'])).hexdigest()
        client = build_opener(ProxyHandler({}))
        for i in range(2):
            data = canonical({'body': 'evaluation receiver calibration ' + str(i)})
            request = Request(fixture.endpoint + route, data=data, headers={**fixture.headers(),
                              'Content-Type': 'application/json', 'X-SIQ-Action-ID': 'calibration-' + str(i)})
            with client.open(request, timeout=2) as response:
                if response.status != 201:
                    raise ValueError('calibration delivery failed')
            # The handler records on exit; wait for the matching collector event.
            deadline = time.monotonic() + 2
            while len(wire) < i + 1 and time.monotonic() < deadline:
                time.sleep(0.005)
            counts.append(len(wire))
    return {'counts': counts, 'wire': wire, 'health': health,
            'passed': counts == [0, 1, 2] and all(health.get(k) is True for k in ('before', 'after', 'closed')),
            'scope': 'same receiver instrumentation, separate fixture; not business deliveries'}
