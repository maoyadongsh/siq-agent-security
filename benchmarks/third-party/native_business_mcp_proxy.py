"""Transparent JSON-line observer around a pre-created, owned MCP container."""
import argparse
import json
import subprocess
import sys
import threading
from pathlib import Path


def proxy(config):
    ledger = Path(config['ledger'])
    lock = threading.Lock()
    process = subprocess.Popen(['docker', 'start', '-a', '-i', config['container']], stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def record(direction, line):
        message = json.loads(line)
        with lock, ledger.open('a') as stream:
            stream.write(json.dumps({'direction': direction, 'message': message}) + '\n')

    def responses():
        for line in process.stdout:
            record('response', line)
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()

    thread = threading.Thread(target=responses, daemon=True)
    thread.start()
    try:
        for line in sys.stdin.buffer:
            if len(line) > 1_000_000:
                raise ValueError('MCP request exceeds observation budget')
            record('request', line)
            process.stdin.write(line)
            process.stdin.flush()
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
        thread.join(timeout=5)
        process.stdout.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    args = parser.parse_args()
    proxy(json.loads(args.config.read_text()))
