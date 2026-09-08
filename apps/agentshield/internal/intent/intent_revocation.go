package intent

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"time"

	"siq-agent-security/apps/agentshield/internal/signing"
)

// IntentRevocation is a terminal, immutable authority withdrawal and audit record.
// IntentDigest binds the verified immutable contract content.
type IntentRevocation struct {
	SchemaVersion string `json:"schema_version"`
	IntentID      string `json:"intent_id"`
	IntentDigest  string `json:"intent_digest"`
	RevokedAt     string `json:"revoked_at"`
	ReasonCode    string `json:"reason_code"`
	SigningSchema string `json:"signing_schema"`
	Signature     string `json:"signature"`
}

func (s *Store) intentRevocationDir() string {
	return filepath.Join(filepath.Dir(s.dir), "intent-revocations")
}
func (s *Store) intentRevocationPath(id string) (string, error) {
	if _, err := s.path(id); err != nil {
		return "", err
	}
	return filepath.Join(s.intentRevocationDir(), id+".json"), nil
}
func intentRevocationMap(r IntentRevocation) map[string]any {
	raw, _ := json.Marshal(r)
	var m map[string]any
	_ = json.Unmarshal(raw, &m)
	delete(m, "signature")
	return m
}
func (s *Store) GetIntentRevocation(id string) (IntentRevocation, error) {
	var r IntentRevocation
	path, err := s.intentRevocationPath(id)
	if err != nil {
		return r, err
	}
	if err = readRecord(path, &r); err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return r, err
		}
		return r, violation("intent_revocation_invalid")
	}
	if r.SchemaVersion != "intent-revocation/v1" || r.IntentID != id || !lowerHex(r.IntentDigest, 32) || r.ReasonCode != "intent_revoked" || r.SigningSchema != signing.SchemaLocalCanonicalV1 || !lowerHex(r.Signature, 64) {
		return r, violation("intent_revocation_invalid")
	}
	if _, err = time.Parse(time.RFC3339Nano, r.RevokedAt); err != nil {
		return r, violation("intent_revocation_invalid")
	}
	if !signing.VerifyCanonical(s.key.Public(), intentRevocationMap(r), r.Signature) {
		return r, violation("intent_revocation_invalid")
	}
	return r, nil
}

// RevokeIntent never removes or rewrites the original authority. A retry returns
// the first signed record; the expected digest is a precondition, not authority.
func (s *Store) RevokeIntent(id, expectedIntentDigest string) (IntentRevocation, error) {
	authorityWriteMu.Lock()
	defer authorityWriteMu.Unlock()
	var r IntentRevocation
	path, err := s.intentRevocationPath(id)
	if err != nil {
		return r, err
	}
	if !lowerHex(expectedIntentDigest, 32) {
		return r, violation("intent_invalid_revoke_request")
	}
	b, err := s.Get(id)
	if err != nil {
		return r, err
	}
	if expectedIntentDigest != b.Digest {
		return r, violation("intent_revoke_conflict")
	}
	wanted := b.Digest
	existing, err := s.GetIntentRevocation(id)
	if err == nil {
		if existing.IntentDigest != wanted {
			return r, violation("intent_revocation_invalid")
		}
		return existing, nil
	}
	if !errors.Is(err, os.ErrNotExist) {
		return r, err
	}
	if ids, err := recordIDs(s.intentRevocationDir()); err != nil {
		return r, err
	} else if len(ids) >= maxRecords {
		return r, violation("intent_state_capacity")
	}
	r = IntentRevocation{SchemaVersion: "intent-revocation/v1", IntentID: id, IntentDigest: wanted, RevokedAt: time.Now().UTC().Format(time.RFC3339Nano), ReasonCode: "intent_revoked", SigningSchema: signing.SchemaLocalCanonicalV1}
	r.Signature, err = s.key.SignCanonical(intentRevocationMap(r))
	if err != nil {
		return r, err
	}
	raw, _ := json.MarshalIndent(r, "", "  ")
	if err = publish(path, raw); errors.Is(err, os.ErrExist) {
		existing, err = s.GetIntentRevocation(id)
		if err == nil && existing.IntentDigest == wanted {
			return existing, nil
		}
		return r, violation("intent_revocation_invalid")
	}
	return r, err
}

func (s *Store) checkIntentRevocation(c Contract) error {
	r, err := s.GetIntentRevocation(c.IntentID)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	if r.IntentDigest != c.Digest {
		return violation("intent_revocation_invalid")
	}
	return violation("intent_revoked")
}
