import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calibrate_agentdojo_pilot import equivalent_differences
from verify_agentdojo import verify_pilot_allocation, verify_prompt_and_dispatch


class PilotTests(unittest.TestCase):
    def test_timestamp_exception_does_not_mask_email_changes(self):
        self.assertTrue(equivalent_differences({}))
        self.assertTrue(equivalent_differences({'values_changed': {"root['inbox']['emails']['34']['timestamp']": {}}}))
        self.assertFalse(equivalent_differences({'values_changed': {"root['inbox']['emails']['34']['body']": {}}}))
        self.assertFalse(equivalent_differences({'dictionary_item_added': ["root['inbox']['emails']['34']"]}))
        self.assertFalse(equivalent_differences({'values_changed': {"root['calendar']['timestamp']": {}}}))

    def test_legacy_smoke_not_reclassified_as_pilot(self):
        verify_pilot_allocation({'applicability': {'selected_tasks': ['one']}}, ['read'])

    def test_allocation_rejects_duplicate_and_missing_arm(self):
        tasks = [f'user_task_{n}' for n in range(20)]
        p = {'applicability': {'selected_tasks': tasks}, 'exposed_tools': ['read', 'send_email'], 'prompt_defense': 'defense',
             'allocation': [{'task_id': t, 'condition': c, 'group': g} for t in tasks for c in ('benign', 'adversarial') for g in ('B0', 'B1', 'B2')]}
        verify_pilot_allocation(p, ['send_email', 'read'])
        changed = copy.deepcopy(p)
        changed['allocation'][-1] = changed['allocation'][0]
        with self.assertRaises(ValueError):
            verify_pilot_allocation(changed, p['exposed_tools'])
        with self.assertRaises(ValueError):
            verify_pilot_allocation(p, ['read'])

    def test_prompt_and_arm_binding(self):
        p = {'system_prompt': 'system', 'prompt_defense': 'defense', 'exposed_tools': ['read']}
        messages = [{'role': 'system', 'content': [{'type': 'text', 'content': 'systemdefense'}]}, {'role': 'user', 'content': [{'type': 'text', 'content': 'task'}]}]
        row = {'decisions': [], 'dispatches': [{'tool': 'read'}]}
        verify_prompt_and_dispatch(p, {'group': 'B1'}, 'task', messages, row)
        for group, prompt in [('B0', 'task'), ('B1', 'attacker substituted task')]:
            with self.assertRaises(ValueError):
                verify_prompt_and_dispatch(p, {'group': group}, prompt, messages, row)
        for bad in [{'decisions': [{}], 'dispatches': []}, {'decisions': [], 'dispatches': [{'tool': 'hidden'}]}]:
            with self.assertRaises(ValueError):
                verify_prompt_and_dispatch(p, {'group': 'B1'}, 'task', messages, bad)


class PairedTests(unittest.TestCase):
    def test_unknown_and_lab_intervention_preserved(self):
        from analysis.agentdojo_pilot import paired
        rows = [{'task_id': 'task', 'group': arm, 'condition': 'adversarial', 'utility_completed': utility,
                 'harm_observed': harm, 'lab_boundary_intervened': lab} for arm, utility, harm, lab in [('B0', True, True, False), ('B2', None, None, True)]]
        result = paired(rows)
        self.assertEqual(result['cells']['harm_observed'], {'yes->unknown': 1})
        self.assertEqual(result['tasks'][0]['lab_boundary_intervened'], {'B0': False, 'B2': True})
        with self.assertRaises(ValueError):
            paired(rows[:1])
