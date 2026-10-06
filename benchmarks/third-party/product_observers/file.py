"""Request product-side observation without deriving the evaluator's gold label."""


class ProductFileObservation:
    def __init__(self, harness, scope, decision, path, expected_digest, observation_id):
        self.harness, self.path, self.observation_id = harness, path, observation_id
        self.token = harness.api("/v1/effect-observers", {
            "source": {"type": "host_observer", "source_id": "evaluation-product-observer", "independence": "host_independent"},
            "scope": scope, "expires_in": 120}, expected=201)["token"]
        harness.api("/v1/file-observations", {"observation_id": observation_id,
                    "action_id": decision["action_id"], "decision_receipt_id": decision["receipt_id"],
                    "path": str(path), "expected_digest": expected_digest, "max_bytes": 65536}, token=self.token, expected=201)

    def finish(self):
        result = self.harness.api("/v1/file-observations/" + self.observation_id + "/finish",
                                  {"path": str(self.path)}, token=self.token, expected=201)
        persisted = self.harness.api("/v1/effect-evidence/" + self.observation_id)
        if result != persisted:
            raise ValueError("product observation readback mismatch")
        return result
