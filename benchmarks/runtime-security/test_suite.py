"""The verifier's requested suite, not a report's claim, selects coverage."""
import unittest

from evidence import verify


class SuiteBoundaryTest(unittest.TestCase):
    def test_report_cannot_downgrade_full_verification_to_smoke(self):
        with self.assertRaisesRegex(ValueError, "requested coverage"):
            verify({"suite": "smoke"})

    def test_unknown_suite_and_mismatched_report_fail_before_evidence(self):
        for report, expected in [({"suite": "custom"}, "custom"),
                                 ({"suite": "full"}, "smoke"), ({}, "smoke")]:
            with self.assertRaisesRegex(ValueError, "requested coverage"):
                verify(report, expected_suite=expected)


if __name__ == "__main__":
    unittest.main()
