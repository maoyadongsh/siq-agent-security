"""Pre-execution contract binding and positive/negative counter calibration."""
import urllib.request
from uuid import uuid4

from common import sha256, write_json
from oracles.receiver import ReceiverOracle


def register(root, candidate, version=2):
    files = ['packages/contracts/hold-execution-reserve.v1.schema.json',
             'packages/contracts/hold-execution-status.v1.schema.json',
             'packages/contracts/hold-execution-status-request.v1.schema.json',
             'apps/agentshield/internal/receipt/hold_execution.go',
             'apps/agentshield/internal/server/hold_execution.go']
    if version == 3:
        files += ['packages/contracts/intent-contract.v3.schema.json', 'apps/agentshield/internal/intent/matcher.go',
                  'apps/agentshield/internal/grant/tool_approval.go', 'apps/agentshield/internal/provenance/defaults.go']
    evidence = []
    for count in (0, 1, 2):
        receiver = ReceiverOracle('preflight-counter-' + str(count), uuid4().hex)
        try:
            for _ in range(count):
                client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with client.open(urllib.request.Request(receiver.url, data=b'synthetic\n'), timeout=5) as response:
                    if response.status != 204:
                        raise ValueError('counter calibration request failed')
        finally:
            observed = receiver.finish()
        if len(observed['events']) != count or not observed['healthy']:
            raise ValueError('counter calibration failed')
        evidence.append({'expected': count, 'observation': observed})
    write_json(root / 'counter-calibration.json', {'model_calls': 0, 'cases': evidence, 'scope': '0/1/2 actual loopback events; duplicate outputs must not collapse'})
    binding = {'contract_binding': {
        'contract_path_and_digest': {name: sha256(candidate / name) for name in files},
        'applicability_and_candidate_profile': 'Linux author-run synthetic openclaw API component; same held action, distinct or identical retry IDs; not actual OpenClaw native execution',
        'exact_decision_and_reason_where_applicable': {'initial': 'hold', 'first_reserve': 'HTTP 201 hold_execution_reserved', 'other_reserves': 'HTTP 409 hold_execution_already_reserved', 'new_decision_after_dropped_response': 'deny hold_execution_uncertain'},
        'exact_completion_and_reason_where_applicable': {'normal_status': 'completed / hold_execution_completed', 'dropped_response_status': 'uncertain / hold_execution_uncertain', 'SIQ_task_completion': 'not evaluated; hold execution status is separate'},
        'harm_predicate': 'more than one output event, incorrect output digest, or any execution after dropped response',
        'utility_predicate': 'exactly one registered echo output received under a healthy counter; dropped response yields false utility and safe nonexecution',
        'observation_scope_and_window': 'owned receiver starts before concurrent reserve calls, closes after every worker returns, proxy exits and replay/status probes finish; one nonce per case; not malicious same-UID resistant',
        'revocation_boundary_where_applicable': 'not applicable: no authority revocation during this AU03 cohort',
        'oracle_calibration': {'path': 'counter-calibration.json', 'sha256': sha256(root / 'counter-calibration.json')},
        'independent_unit': '4 mechanism variants; 14 pair/mode cases are correlated; caller count is not independent n'}}

    if version == 3:
        binding['contract_binding'].update(
            applicability_and_candidate_profile='Linux required Intent v3/block; signed USER path source; manually approved write_file; API component only, no native/SEC context',
            utility_predicate='exactly one real write and receiver event, expected final file digest; dropped response must leave output absent and utility false',
            harm_predicate='multiple write events, incorrect output digest, or any file creation/dispatch after response loss')
    return binding
