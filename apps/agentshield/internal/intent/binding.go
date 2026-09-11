package intent

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/signing"
	"time"
)

type Binding struct {
	GrantRef          *GrantReference `json:"grant_ref,omitempty"`
	SelectedGrant     *grant.Grant    `json:"-"`
	BindingID         string          `json:"binding_id"`
	Platform          string          `json:"platform"`
	SessionID         string          `json:"session_id"`
	AgentID           string          `json:"agent_id"`
	TaskID            string          `json:"task_id"`
	IntentID          string          `json:"intent_id"`
	IntentDigest      string          `json:"intent_digest"`
	BoundAt           string          `json:"bound_at"`
	ExpiresAt         string          `json:"expires_at"`
	AuthorityRevision string          `json:"authority_revision"`
	Signature         string          `json:"signature"`
}

func bindingID(platform, session, agent string) string {
	raw, _ := json.Marshal([]string{platform, session, agent})
	d := sha256.Sum256(raw)
	return "bind-" + hex.EncodeToString(d[:])
}
func bindingMap(b Binding) map[string]any {
	raw, _ := json.Marshal(b)
	var m map[string]any
	_ = json.Unmarshal(raw, &m)
	delete(m, "signature")
	return m
}

// Bind resolves authority from the store. Derived fields cannot be supplied by a caller.
func (s *Store) Bind(b Binding) (Binding, error) {
	if b.GrantRef != nil {
		return b, violation("intent_invalid_grant_selection")
	}
	return s.bind(b)
}

func (s *Store) bind(b Binding) (Binding, error) {
	authorityWriteMu.Lock()
	defer authorityWriteMu.Unlock()
	if b.Platform == "" || b.SessionID == "" || b.AgentID == "" || b.IntentID == "" {
		return b, violation("intent_invalid_binding")
	}
	c, err := s.Get(b.IntentID)
	if err != nil {
		return b, err
	}
	if err = s.checkIntentRevocation(c); err != nil {
		return b, err
	}
	if err = c.Active(time.Now()); err != nil {
		return b, err
	}
	if b.AgentID != c.Agent.ID || b.Platform != c.Agent.Platform {
		return b, violation("intent_agent_mismatch")
	}
	if b.TaskID != "" && b.TaskID != c.TaskID {
		return b, violation("intent_task_mismatch")
	}
	if _, err := s.resolveGrantSelection(b); err != nil {
		return b, err
	}
	b.BindingID = bindingID(b.Platform, b.SessionID, b.AgentID)
	if _, err := s.GetBindingRevocation(b.BindingID); err == nil {
		return b, violation("intent_binding_revoked")
	} else if !errors.Is(err, os.ErrNotExist) {
		return b, err
	}
	b.TaskID = c.TaskID
	b.IntentDigest = c.Digest
	b.AuthorityRevision = c.Authority.Revision
	if b.ExpiresAt == "" {
		b.ExpiresAt = c.ExpiresAt
	}
	until, err := time.Parse(time.RFC3339, b.ExpiresAt)
	end, _ := time.Parse(time.RFC3339, c.ExpiresAt)
	if err != nil || !time.Now().Before(until) || until.After(end) {
		return b, violation("intent_invalid_time_window")
	}
	// Stable ID is a cross-process uniqueness constraint, including after expiry.
	p, _ := s.bindingPath(b.BindingID)
	if existing, err := s.GetBinding(b.BindingID); err == nil {
		if existing.IntentID == b.IntentID && existing.IntentDigest == b.IntentDigest && existing.ExpiresAt == b.ExpiresAt && reflect.DeepEqual(existing.GrantRef, b.GrantRef) {
			return existing, nil
		}
		return b, violation("intent_binding_conflict")
	} else if !errors.Is(err, os.ErrNotExist) {
		return b, err
	}
	if ids, err := recordIDs(s.bindingDir()); err != nil {
		return b, err
	} else if len(ids) >= maxRecords {
		return b, violation("intent_state_capacity")
	}
	b.BoundAt = time.Now().UTC().Format(time.RFC3339Nano)
	b.Signature, err = s.key.SignCanonical(bindingMap(b))
	if err != nil {
		return b, err
	}
	raw, _ := json.MarshalIndent(b, "", "  ")
	if len(raw) > maxRecordBytes {
		return b, violation("intent_invalid_record")
	}
	if err = publish(p, raw); errors.Is(err, os.ErrExist) {
		existing, e := s.GetBinding(b.BindingID)
		if e == nil && existing.IntentID == b.IntentID && existing.IntentDigest == b.IntentDigest && existing.ExpiresAt == b.ExpiresAt && reflect.DeepEqual(existing.GrantRef, b.GrantRef) {
			return existing, nil
		}
		return b, violation("intent_binding_conflict")
	}
	return b, err
}
func (s *Store) GetBinding(id string) (Binding, error) {
	var b Binding
	p, err := s.bindingPath(id)
	if err != nil {
		return b, err
	}
	if err = readRecord(p, &b); err != nil {
		return b, err
	}
	if b.BindingID != id || id != bindingID(b.Platform, b.SessionID, b.AgentID) || !signing.VerifyCanonical(s.key.Public(), bindingMap(b), b.Signature) {
		return b, violation("intent_signature_invalid")
	}
	return b, nil
}
func (s *Store) bindingPath(id string) (string, error) {
	if !validID(id) {
		return "", violation("intent_invalid_id")
	}
	return filepath.Join(s.bindingDir(), id+".json"), nil
}
func (s *Store) ListBindings() ([]Binding, error) {
	ids, err := recordIDs(s.bindingDir())
	if err != nil {
		return nil, err
	}
	out := []Binding{}
	for _, id := range ids {
		b, err := s.GetBinding(id)
		if err != nil {
			return nil, err
		}
		out = append(out, b)
	}
	return out, nil
}
