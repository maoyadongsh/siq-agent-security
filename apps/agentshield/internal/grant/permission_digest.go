package grant

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"

	"siq-agent-security/apps/agentshield/internal/canon"
)

// PermissionDigest identifies the approved execution limits independently of
// backend readback evidence. The complete Grant signature is verified separately.
func PermissionDigest(g Grant) (string, error) {
	raw, err := json.Marshal(g)
	if err != nil {
		return "", err
	}
	decoded, err := canon.Decode(raw)
	if err != nil {
		return "", err
	}
	document := decoded.(map[string]any)
	for _, field := range []string{"status", "effective_readback", "signature", "signing_schema"} {
		delete(document, field)
	}
	if facts, ok := document["facts"].([]any); ok {
		for _, value := range facts {
			f := value.(map[string]any)
			// Only tool allow facts consult state during runtime authorization.
			if f["domain"] == "tool" {
				if f["state"] == "declared" || f["state"] == "effective" {
					f["state"] = "runtime_eligible"
				}
			} else {
				delete(f, "state")
			}
			for _, field := range []string{"authority", "authority_revision", "readback_evidence_id"} {
				delete(f, field)
			}
		}
	}
	document["digest_schema"] = "grant-permissions/v1"
	normalized, err := canon.Marshal(document)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(normalized)
	return hex.EncodeToString(sum[:]), nil
}
