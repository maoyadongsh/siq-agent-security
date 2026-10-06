"""Bounded stdio MCP source used only by owned native Hermes profiles."""
import argparse
import json
import os
import sys
from pathlib import Path


def serve(config):
    ledger = Path(config['ledger'])
    initialized = False
    with ledger.open('a') as stream:
        stream.write(json.dumps({'event': 'start', 'pid': os.getpid()}) + '\n')
    for line in sys.stdin:
        if len(line) > 65536:
            raise ValueError('request too large')
        message = json.loads(line)
        method, ident = message.get('method'), message.get('id')
        if method == 'initialize':
            result = {'protocolVersion': message['params']['protocolVersion'], 'capabilities': {'tools': {}},
                      'serverInfo': {'name': 'evaluation-reports', 'version': '1'}}
        elif method == 'notifications/initialized':
            initialized = True
            result = None
        elif method == 'tools/list':
            result = {'tools': [{'name': 'lookup', 'description': 'Return the authorized synthetic report path.',
                                'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}}]}
        elif method == 'tools/call' and initialized:
            if message['params'].get('name') != 'lookup' or message['params'].get('arguments', {}) != {}:
                raise ValueError('unexpected MCP tool arguments')
            result = {'content': [{'type': 'text', 'text': config['target']}],
                      'structuredContent': {'path': config['target']}, 'isError': False}
        elif method == 'ping':
            result = {}
        elif ident is None:
            result = None
        else:
            raise ValueError('unexpected MCP method')
        row = {'event': 'rpc', 'method': method, 'id': ident, 'params': message.get('params'), 'result': result}
        with ledger.open('a') as stream:
            stream.write(json.dumps(row) + '\n')
        if ident is not None:
            print(json.dumps({'jsonrpc': '2.0', 'id': ident, 'result': result}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    args = parser.parse_args()
    serve(json.loads(args.config.read_text()))
