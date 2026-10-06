"""Owned sandbox syscall control, separate from model tools and SIQ decisions."""
import hashlib
import json
import sys
from pathlib import Path


def probe(allowed_input, allowed_output, forbidden):
    result = {'schema_version': 'siq.research-cross-company-os-probe.v1'}
    result['allowed_read_sha256'] = hashlib.sha256(allowed_input.read_bytes()).hexdigest()
    with allowed_output.open('xb') as stream:
        stream.write(b'OWNED_OS_POSITIVE_CONTROL\n')
    result['allowed_write_sha256'] = hashlib.sha256(allowed_output.read_bytes()).hexdigest()
    for operation in ('read', 'write'):
        try:
            if operation == 'read':
                raw = forbidden.read_bytes()
                result['forbidden_read_sha256'] = hashlib.sha256(raw).hexdigest()
            else:
                forbidden.write_bytes(b'UNAUTHORIZED_OS_CANARY_MUTATION\n')
        except OSError as exc:
            result[operation + '_denied'] = True
            result[operation + '_error'] = type(exc).__name__
            result[operation + '_errno'] = exc.errno
        else:
            result[operation + '_denied'] = False
    return result


if __name__ == '__main__':
    print(json.dumps(probe(*(Path(value) for value in sys.argv[1:4])), sort_keys=True))
