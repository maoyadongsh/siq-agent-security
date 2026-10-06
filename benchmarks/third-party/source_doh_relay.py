"""Temporary evaluation DNS relay: forward original wire queries over verified TLS."""
import hashlib
import ipaddress
import json
import socketserver
import struct
import time
import urllib.request


def skip_name(data, offset):
    for _ in range(128):
        size = data[offset]
        offset += 1
        if size & 0xc0 == 0xc0:
            return offset + 1
        if size == 0:
            return offset
        if size > 63:
            raise ValueError('invalid DNS name')
        offset += size
    raise ValueError('DNS name budget')


def answer_addresses(data):
    _, _, questions, answers, _, _ = struct.unpack('!6H', data[:12])
    at = 12
    for _ in range(questions):
        at = skip_name(data, at) + 4
    result = []
    for _ in range(answers):
        at = skip_name(data, at)
        kind, _, _, size = struct.unpack('!HHIH', data[at:at + 10])
        at += 10
        if (kind, size) in ((1, 4), (28, 16)):
            result.append(str(ipaddress.ip_address(data[at:at + size])))
        at += size
    return result


class Relay(socketserver.BaseRequestHandler):
    def handle(self):
        query, transport = self.request
        row = {'time_ns': time.time_ns(), 'query_sha256': hashlib.sha256(query).hexdigest()}
        try:
            if not 12 <= len(query) <= 4096:
                raise ValueError('query budget')
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            request = urllib.request.Request('https://1.1.1.1/dns-query', data=query,
                                             headers={'Content-Type': 'application/dns-message', 'Accept': 'application/dns-message'})
            with opener.open(request, timeout=10) as response:
                data = response.read(65536)
                if response.status != 200 or not 12 <= len(data) < 65536 or data[:2] != query[:2]:
                    raise ValueError('invalid upstream DNS response')
            row.update(response_sha256=hashlib.sha256(data).hexdigest(), rcode=data[3] & 15, addresses=answer_addresses(data))
        except Exception as error:  # noqa: BLE001 -- bounded error reply, no upstream body in logs
            row['error_type'] = type(error).__name__
            data = query[:2] + b'\x81\x82' + b'\0' * 8
        transport.sendto(data, self.client_address)
        print(json.dumps(row), flush=True)


if __name__ == '__main__':
    with socketserver.ThreadingUDPServer(('0.0.0.0', 53), Relay) as server:
        server.daemon_threads = True
        print(json.dumps({'event': 'dns_ready', 'transport': 'original DNS wire over HTTPS; system certificate validation'}), flush=True)
        server.serve_forever(poll_interval=.2)
