"""Separate exact source support from an unnecessarily exact citation set."""
import json
import unittest

from native_semantic import expected_report, grade, tasks
from native_semantic_review import citation_review


class CitationReviewTests(unittest.TestCase):
    def setUp(self):
        self.task = next(t for t in tasks() if t['id'] == 'incident')
        self.report = expected_report(self.task)

    def evaluate(self):
        return citation_review(self.task, json.dumps(self.report))

    def test_additional_correct_context_does_not_erase_support(self):
        self.report['answers']['affected_customers']['citations'].append({
            'document': 'report.txt', 'line_id': 'E3', 'quote': self.task['documents']['report.txt'][2][1]})
        self.assertFalse(grade(self.task, json.dumps(self.report))['passed'])
        result = self.evaluate()
        self.assertTrue(result['supported_correct_report'])
        self.assertEqual(result['claims']['affected_customers']['extra_source_refs'], ['report.txt:E3'])

    def test_wrong_value_still_fails_with_real_quotes(self):
        self.report['answers']['affected_customers']['value'] = 9
        self.assertFalse(self.evaluate()['supported_correct_report'])

    def test_missing_necessary_source_still_fails(self):
        self.report['answers']['affected_customers']['citations'] = [{
            'document': 'report.txt', 'line_id': 'E3', 'quote': self.task['documents']['report.txt'][2][1]}]
        self.assertFalse(self.evaluate()['supported_correct_report'])

    def test_fabricated_additional_quote_still_fails(self):
        self.report['answers']['affected_customers']['citations'].append({
            'document': 'report.txt', 'line_id': 'E3', 'quote': 'Invented context'})
        self.assertFalse(self.evaluate()['supported_correct_report'])

    def test_duplicate_is_recorded_not_new_evidence(self):
        self.report['answers']['affected_customers']['citations'] *= 2
        self.assertEqual(self.evaluate()['claims']['affected_customers']['duplicate_references'], 1)

    def test_schema_invalid_cannot_be_rescued(self):
        self.report['answers']['unrequested'] = {'value': 3, 'citations': []}
        self.assertFalse(self.evaluate()['reviewable'])

    def test_prospective_policy_keeps_original_default(self):
        self.report['answers']['affected_customers']['citations'].append({
            'document': 'report.txt', 'line_id': 'E3', 'quote': self.task['documents']['report.txt'][2][1]})
        encoded = json.dumps(self.report)
        self.assertFalse(grade(self.task, encoded)['passed'])
        self.assertTrue(grade(self.task, encoded, citation_policy='minimum_required_traceable')['passed'])
        self.report['answers']['affected_customers']['citations'].pop(0)
        self.assertFalse(grade(self.task, json.dumps(self.report), citation_policy='minimum_required_traceable')['passed'])

    def test_unknown_policy_is_rejected(self):
        with self.assertRaises(ValueError):
            grade(self.task, json.dumps(self.report), citation_policy='ignore_all_citations')


if __name__ == '__main__':
    unittest.main()
