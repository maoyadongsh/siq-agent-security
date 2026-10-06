import hashlib
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from oracles.receiver import ReceiverOracle


class ReceiverTests(unittest.TestCase):
    def test_actual_delivery_and_duplicate_dispatch(self):
        receiver = ReceiverOracle("calibration", "nonce-unique")
        body = b"synthetic message"
        client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(2):
            with client.open(urllib.request.Request(receiver.url, data=body), timeout=2) as response:
                self.assertEqual(response.status, 204)
        capture = receiver.finish()
        self.assertTrue(capture["healthy"])
        self.assertEqual(len(capture["events"]), 2)
        self.assertEqual(capture["events"][0]["body_sha256"], hashlib.sha256(body).hexdigest())

    def test_fake_observer_material_and_wrong_nonce_cannot_invent_delivery(self):
        receiver = ReceiverOracle("calibration", "expected-nonce")
        client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with self.assertRaises(urllib.error.HTTPError) as caught:
            client.open(urllib.request.Request(receiver.endpoint + "/receive/wrong-nonce", data=b"payload"), timeout=2)
        self.assertEqual(caught.exception.code, 403)
        capture = receiver.finish()
        self.assertEqual(capture["events"], [])
        self.assertEqual(capture["rejected_requests"], 1)
        self.assertTrue(capture["healthy"])

    def test_unstopped_background_cannot_prove_absence(self):
        receiver = ReceiverOracle("calibration", "nonce")
        self.assertFalse(receiver.finish(background_stopped=False)["healthy"])


if __name__ == "__main__":
    unittest.main()
