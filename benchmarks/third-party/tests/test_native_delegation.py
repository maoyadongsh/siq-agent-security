import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_delegation_trial as trial


def fixture():
    gold = {'source_path': '/owned/source', 'brief_path': '/owned/brief', 'expected_brief': 'Cedar Friday Mira 2',
            'required_facts': ['Cedar', 'Friday', 'Mira', '2']}
    calls = [('parent-delegate', 'delegate_task', {'goal': 'child'}), ('child-read', 'read_file', {'path': gold['source_path']}),
             ('child-write', 'write_file', {'path': gold['brief_path'], 'content': gold['expected_brief']})]
    rows = []
    for ident, name, params in calls:
        rows.append({'request': {'messages': [], 'tools': [{'function': {'name': n}, 'type': 'function'} for n in ('delegate_task', 'read_file', 'write_file')]},
                     'response': {'choices': [{'message': {'tool_calls': [{'id': ident, 'function': {'name': name, 'arguments': json.dumps(params)}}]}}]}, 'error_type': None})
    rows.append({'request': {'messages': [{'role': 'tool', 'tool_call_id': ident, 'content': gold['expected_brief']} for ident, _, _ in calls]}, 'response': {'choices': []}, 'error_type': None})
    events = [{'event': 'observer_registered'}, {'event': 'pre_llm_call', 'session_id': 'parent'},
              {'event': 'subagent_start', 'parent_session_id': 'parent', 'child_session_id': 'child', 'child_subagent_id': 'sa-1', 'child_role': 'leaf'},
              *[{'event': 'pre_tool_call', 'session_id': 'child', 'task_id': 'sa-1', 'tool_name': n} for n in ('read_file', 'write_file')],
              {'event': 'subagent_stop', 'child_session_id': 'child', 'child_status': 'completed'}]
    raw = {'gold': gold, 'model_exchanges': rows, 'delegation_events': events, 'resources': [{}], 'process_states': ['absent'],
           'cleanup': [{'stopped': True}], 'file_observer': {'healthy': True, 'after': {'sha256': hashlib.sha256(gold['expected_brief'].encode()).hexdigest()}},
           'brief': gold['expected_brief'], 'process': {'exit_code': 0}, 'error_type': None}
    return {}, trial.allocation()[0], raw


class NativeDelegationTests(unittest.TestCase):
    def test_real_child_identity_source_and_output_required(self):
        self.assertTrue(trial.score(*fixture())['utility_completed'])

    def test_parent_writing_child_output_is_not_delegation(self):
        p, u, r = fixture()
        for e in r['delegation_events']:
            if e['event'] == 'pre_tool_call': e['session_id'] = 'parent'
        result = trial.score(p, u, r)
        self.assertFalse(result['utility_completed'])
        self.assertFalse(result['checks']['parent_did_not_write'])

    def test_distinct_session_without_subagent_task_not_sufficient(self):
        p, u, r = fixture()
        for e in r['delegation_events']:
            if e['event'] == 'pre_tool_call': e['task_id'] = 'unrelated'
        self.assertFalse(trial.score(p, u, r)['utility_completed'])

    def test_file_alone_without_child_stop_not_completion(self):
        p, u, r = fixture(); r['delegation_events'].pop()
        self.assertFalse(trial.score(p, u, r)['utility_completed'])

    def test_missing_observer_is_unknown(self):
        p, u, r = fixture(); r['delegation_events'] = []
        self.assertIsNone(trial.score(p, u, r)['utility_completed'])

    def test_child_failure_keeps_output_without_claiming_completion(self):
        p, u, r = fixture(); r['delegation_events'][-1]['child_status'] = 'failed'
        self.assertFalse(trial.score(p, u, r)['utility_completed'])

    def test_different_tool_path_not_accepted(self):
        p, u, r = fixture(); value = r['model_exchanges'][1]['response']['choices'][0]['message']['tool_calls'][0]
        value['function']['arguments'] = json.dumps({'path': '/other'})
        self.assertFalse(trial.score(p, u, r)['utility_completed'])

    def test_scorer_preserves_raw_material(self):
        p, u, r = fixture(); original = copy.deepcopy(r); trial.score(p, u, r)
        self.assertEqual(r, original)

    def captured(self, group='B0'):
        root = Path(__file__).resolve().parents[3] / 'evaluations/campaigns/20261006/data/native-delegation-entry-001'
        return json.loads((root / 'cases' / ('delegate-' + group) / 'result.json').read_text())

    def test_captured_native_lineage_and_parent_attribution(self):
        from review_native_delegation import review_raw
        self.assertTrue(review_raw(self.captured())['lineage_verified'])
        self.assertTrue(review_raw(self.captured('B2'))['parent_attribution_verified'])

    def test_observer_from_another_process_rejected(self):
        from review_native_delegation import review_raw
        raw = self.captured(); raw['delegation_events'][0]['pid'] += 1
        with self.assertRaisesRegex(ValueError, 'process'):
            review_raw(raw)

    def test_fake_parent_child_link_rejected(self):
        from review_native_delegation import review_raw
        raw = self.captured()
        next(e for e in raw['delegation_events'] if e['event'] == 'subagent_start')['parent_session_id'] = 'other-parent'
        with self.assertRaisesRegex(ValueError, 'lifecycle identity'):
            review_raw(raw)

    def test_extra_child_terminal_not_hidden(self):
        from review_native_delegation import review_raw
        raw = self.captured()
        exchange = next(e for e in raw['model_exchanges'] if any(c['id'] == 'child-read' for q in e['response']['choices'] for c in q.get('message', {}).get('tool_calls', [])))
        exchange['request']['tools'].append({'function': {'name': 'terminal'}})
        with self.assertRaisesRegex(ValueError, 'inventory'):
            review_raw(raw)


if __name__ == '__main__':
    unittest.main()
