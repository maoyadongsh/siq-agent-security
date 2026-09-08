package intent

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"

	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/trustedcontext"
)

func contextInvalid() error         { return &trustedcontext.Violation{Code: "trusted_context_invalid"} }
func (s *Store) contextDir() string { return filepath.Join(filepath.Dir(s.dir), "context-assertions") }

// IssueContext shares the immutable authority publisher and signing suite with
// Intent. Only the management HTTP capability exposes this operation.
func (s *Store) IssueContext(a trustedcontext.Assertion) (*trustedcontext.Assertion, error) {
	authorityWriteMu.Lock()
	defer authorityWriteMu.Unlock()
	if a.Signature != "" || a.SigningSchema != "" && a.SigningSchema != signing.SchemaLocalCanonicalV1 {
		return nil, contextInvalid()
	}
	a.SigningSchema = signing.SchemaLocalCanonicalV1
	if err := a.Validate(); err != nil {
		return nil, err
	}
	ids, err := recordIDs(s.contextDir())
	if err != nil || len(ids) >= maxRecords {
		return nil, contextInvalid()
	}
	a.Signature, err = s.key.SignCanonical(a.Unsigned())
	if err != nil {
		return nil, contextInvalid()
	}
	raw, err := json.MarshalIndent(a, "", "  ")
	if err != nil || len(raw) > 64<<10 {
		return nil, contextInvalid()
	}
	if err = publish(filepath.Join(s.contextDir(), a.AssertionID+".json"), raw); err != nil {
		if errors.Is(err, os.ErrExist) {
			return nil, &trustedcontext.Violation{Code: "trusted_context_conflict"}
		}
		return nil, contextInvalid()
	}
	return &a, nil
}
func (s *Store) GetContext(id string) (*trustedcontext.Assertion, error) {
	authorityWriteMu.RLock()
	defer authorityWriteMu.RUnlock()
	if !validID(id) {
		return nil, contextInvalid()
	}
	path := filepath.Join(s.contextDir(), id+".json")
	fi, err := os.Lstat(path)
	if err != nil || fi.Size() > 64<<10 {
		return nil, contextInvalid()
	}
	var a trustedcontext.Assertion
	if err := readRecord(path, &a); err != nil {
		return nil, contextInvalid()
	}
	if a.AssertionID != id || a.Validate() != nil || signing.VerifyWithSchema(a.SigningSchema, s.key.Public(), a.Unsigned(), a.Signature) != nil {
		return nil, contextInvalid()
	}
	return &a, nil
}
