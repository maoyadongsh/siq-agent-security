package intent

import (
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/signing"
)

// BindingRevocation is a terminal, immutable authority withdrawal and audit record.
// BindingDigest covers the entire original Binding, including its signature.
type BindingRevocation struct {
	SchemaVersion string `json:"schema_version"`
	BindingID     string `json:"binding_id"`
	BindingDigest string `json:"binding_digest"`
	RevokedAt     string `json:"revoked_at"`
	ReasonCode    string `json:"reason_code"`
	SigningSchema string `json:"signing_schema"`
	Signature     string `json:"signature"`
}

func lowerHex(value string, size int) bool {
	if len(value) != size*2 || value != strings.ToLower(value) {
		return false
	}
	raw, err := hex.DecodeString(value)
	return err == nil && len(raw) == size
}
func (s *Store) revocationDir() string {
	return filepath.Join(filepath.Dir(s.dir), "intent-binding-revocations")
}
func (s *Store) revocationPath(id string) (string, error) {
	if !strings.HasPrefix(id, "bind-") || !lowerHex(strings.TrimPrefix(id, "bind-"), 32) {
		return "", violation("intent_invalid_id")
	}
	return filepath.Join(s.revocationDir(), id+".json"), nil
}
func revocationMap(r BindingRevocation) map[string]any {
	raw, _ := json.Marshal(r)
	var m map[string]any
	_ = json.Unmarshal(raw, &m)
	delete(m, "signature")
	return m
}
func bindingDigest(b Binding) (string, error) {
	m := bindingMap(b)
	m["signature"] = b.Signature
	return digest(m)
}
func (s *Store) GetBindingRevocation(id string) (BindingRevocation, error) {
	var r BindingRevocation
	path, err := s.revocationPath(id)
	if err != nil {
		return r, err
	}
	if err = readRecord(path, &r); err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return r, err
		}
		return r, violation("intent_binding_revocation_invalid")
	}
	if r.SchemaVersion != "intent-binding-revocation/v1" || r.BindingID != id || !lowerHex(r.BindingDigest, 32) || r.ReasonCode != "intent_binding_revoked" || r.SigningSchema != signing.SchemaLocalCanonicalV1 || !lowerHex(r.Signature, 64) {
		return r, violation("intent_binding_revocation_invalid")
	}
	if _, err = time.Parse(time.RFC3339Nano, r.RevokedAt); err != nil {
		return r, violation("intent_binding_revocation_invalid")
	}
	if !signing.VerifyCanonical(s.key.Public(), revocationMap(r), r.Signature) {
		return r, violation("intent_binding_revocation_invalid")
	}
	return r, nil
}

// RevokeBinding never removes or rewrites the original authority. A retry returns
// the first signed record; the expected digest is a precondition, not authority.
func (s *Store) RevokeBinding(id, expectedIntentDigest string) (BindingRevocation, error) {
	authorityWriteMu.Lock()
	defer authorityWriteMu.Unlock()
	var r BindingRevocation
	path, err := s.revocationPath(id)
	if err != nil {
		return r, err
	}
	if !lowerHex(expectedIntentDigest, 32) {
		return r, violation("intent_invalid_revoke_request")
	}
	b, err := s.GetBinding(id)
	if err != nil {
		return r, err
	}
	if expectedIntentDigest != b.IntentDigest {
		return r, violation("intent_binding_revoke_conflict")
	}
	wanted, err := bindingDigest(b)
	if err != nil {
		return r, err
	}
	existing, err := s.GetBindingRevocation(id)
	if err == nil {
		if existing.BindingDigest != wanted {
			return r, violation("intent_binding_revocation_invalid")
		}
		return existing, nil
	}
	if !errors.Is(err, os.ErrNotExist) {
		return r, err
	}
	if ids, err := recordIDs(s.revocationDir()); err != nil {
		return r, err
	} else if len(ids) >= maxRecords {
		return r, violation("intent_state_capacity")
	}
	r = BindingRevocation{SchemaVersion: "intent-binding-revocation/v1", BindingID: id, BindingDigest: wanted, RevokedAt: time.Now().UTC().Format(time.RFC3339Nano), ReasonCode: "intent_binding_revoked", SigningSchema: signing.SchemaLocalCanonicalV1}
	r.Signature, err = s.key.SignCanonical(revocationMap(r))
	if err != nil {
		return r, err
	}
	raw, _ := json.MarshalIndent(r, "", "  ")
	if err = publish(path, raw); errors.Is(err, os.ErrExist) {
		existing, err = s.GetBindingRevocation(id)
		if err == nil && existing.BindingDigest == wanted {
			return existing, nil
		}
		return r, violation("intent_binding_revocation_invalid")
	}
	return r, err
}
