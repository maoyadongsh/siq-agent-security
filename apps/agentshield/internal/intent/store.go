package intent

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/url"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/signing"
	"strings"
	"sync"
	"time"
)

var authorityWriteMu sync.Mutex

const maxRecords = 4096
const maxRecordBytes = 1 << 20

// Store uses immutable signed documents as authority and issuance audit records.
type Store struct {
	dir string
	key *signing.Key
}

func Open(dir string, key *signing.Key) (*Store, error) {
	if dir == "" || key == nil {
		return nil, errors.New("intent: directory and key required")
	}
	for _, name := range []string{"intents", "intent-bindings"} {
		if err := os.MkdirAll(filepath.Join(dir, name), 0700); err != nil {
			return nil, err
		}
	}
	return &Store{dir: filepath.Join(dir, "intents"), key: key}, nil
}
func (s *Store) path(id string) (string, error) {
	if !validID(id) {
		return "", violation("intent_invalid_id")
	}
	return filepath.Join(s.dir, id+".json"), nil
}
func (s *Store) bindingDir() string { return filepath.Join(filepath.Dir(s.dir), "intent-bindings") }
func unsignedMap(c Contract) map[string]any {
	b, _ := json.Marshal(c)
	var m map[string]any
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.UseNumber()
	_ = dec.Decode(&m)
	delete(m, "digest")
	delete(m, "signature")
	return m
}
func digest(m map[string]any) (string, error) {
	b, err := canon.Marshal(m)
	if err != nil {
		return "", err
	}
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:]), nil
}

// Publish a complete fsynced file exclusively; never expose a partially written authority.
func publish(path string, b []byte) error {
	f, err := os.CreateTemp(filepath.Dir(path), ".intent-*")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if _, err = f.Write(b); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	return os.Link(f.Name(), path)
}
func readRecord(path string, out any) error {
	fi, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if !fi.Mode().IsRegular() || fi.Size() > maxRecordBytes {
		return violation("intent_invalid_record")
	}
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	dec := json.NewDecoder(io.LimitReader(f, maxRecordBytes+1))
	dec.DisallowUnknownFields()
	dec.UseNumber()
	if err := dec.Decode(out); err != nil {
		return violation("intent_invalid_record")
	}
	var extra any
	if dec.Decode(&extra) != io.EOF {
		return violation("intent_invalid_record")
	}
	return nil
}
func recordIDs(dir string) ([]string, error) {
	f, err := os.Open(dir)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	entries, err := f.ReadDir(maxRecords + 1)
	if err != nil && err != io.EOF {
		return nil, err
	}
	if len(entries) > maxRecords {
		return nil, violation("intent_state_capacity")
	}
	ids := []string{}
	for _, e := range entries {
		if strings.HasPrefix(e.Name(), ".") {
			continue
		}
		if !strings.HasSuffix(e.Name(), ".json") || !validID(strings.TrimSuffix(e.Name(), ".json")) {
			return nil, violation("intent_invalid_record")
		}
		ids = append(ids, strings.TrimSuffix(e.Name(), ".json"))
	}
	return ids, nil
}
func (s *Store) checkEvidence(c Contract) error {
	for _, id := range c.Authority.EvidenceIDs {
		if strings.HasPrefix(id, "external:") {
			u, err := url.Parse(strings.TrimPrefix(id, "external:"))
			if err != nil || u.Scheme != "https" || u.Hostname() == "" || u.User != nil {
				return violation("intent_invalid_evidence")
			}
			continue
		}
		if !validID(id) {
			return violation("intent_invalid_evidence")
		}
		var evidence struct {
			EvidenceID string `json:"evidence_id"`
		}
		// Evidence has its own schema; inspect identity without rejecting its other fields.
		p := filepath.Join(filepath.Dir(s.dir), "evidence", id+".json")
		fi, err := os.Lstat(p)
		if err != nil || !fi.Mode().IsRegular() || fi.Size() > maxRecordBytes {
			return violation("intent_evidence_missing")
		}
		raw, err := os.ReadFile(p)
		if err != nil || json.Unmarshal(raw, &evidence) != nil || evidence.EvidenceID != id {
			return violation("intent_evidence_missing")
		}
	}
	return nil
}
func (s *Store) Issue(c Contract) (*Contract, error) {
	authorityWriteMu.Lock()
	defer authorityWriteMu.Unlock()
	if err := c.Validate(); err != nil {
		return nil, err
	}
	if err := s.checkEvidence(c); err != nil {
		return nil, err
	}
	c.SigningSchema = signing.SchemaLocalCanonicalV1
	m := unsignedMap(c)
	d, err := digest(m)
	if err != nil {
		return nil, err
	}
	c.Digest = d
	m["digest"] = d
	c.Signature, err = s.key.SignCanonical(m)
	if err != nil {
		return nil, err
	}
	p, err := s.path(c.IntentID)
	if err != nil {
		return nil, err
	}
	b, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return nil, err
	}
	if len(b) > maxRecordBytes {
		return nil, violation("intent_invalid_record")
	}
	if ids, err := recordIDs(s.dir); err != nil {
		return nil, err
	} else if len(ids) >= maxRecords {
		return nil, violation("intent_state_capacity")
	}
	if err = publish(p, b); errors.Is(err, os.ErrExist) {
		existing, e := s.Get(c.IntentID)
		if e != nil {
			return nil, e
		}
		if existing.Digest == c.Digest && existing.Signature == c.Signature {
			return &existing, nil
		}
		return nil, violation("intent_immutable_conflict")
	}
	if err != nil {
		return nil, err
	}
	return &c, nil
}
func (s *Store) Get(id string) (Contract, error) {
	var c Contract
	p, err := s.path(id)
	if err != nil {
		return c, err
	}
	if err = readRecord(p, &c); err != nil {
		return c, err
	}
	if c.IntentID != id {
		return c, violation("intent_digest_mismatch")
	}
	m := unsignedMap(c)
	d, err := digest(m)
	if err != nil || d != c.Digest {
		return c, violation("intent_digest_mismatch")
	}
	m["digest"] = d
	if c.SigningSchema != signing.SchemaLocalCanonicalV1 || !signing.VerifyCanonical(s.key.Public(), m, c.Signature) {
		return c, violation("intent_signature_invalid")
	}
	return c, c.Validate()
}
func (s *Store) List() ([]Contract, error) {
	ids, err := recordIDs(s.dir)
	if err != nil {
		return nil, err
	}
	out := []Contract{}
	for _, id := range ids {
		c, err := s.Get(id)
		if err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, nil
}
func (s *Store) ResolveBinding(platform, sessionID, agentID string) (*Contract, *Binding, error) {
	bindings, err := s.ListBindings()
	if err != nil {
		return nil, nil, err
	}
	var found *Binding
	for _, b := range bindings {
		if b.Platform != platform || b.SessionID != sessionID || b.AgentID != agentID {
			continue
		}
		if found != nil {
			return nil, nil, violation("intent_binding_conflict")
		}
		copy := b
		found = &copy
	}
	if found == nil {
		return nil, nil, nil
	}
	until, err := time.Parse(time.RFC3339, found.ExpiresAt)
	if err != nil || !time.Now().Before(until) {
		return nil, found, violation("intent_expired")
	}
	c, err := s.Get(found.IntentID)
	if errors.Is(err, os.ErrNotExist) {
		return nil, found, violation("intent_not_found")
	}
	if err != nil {
		return nil, found, err
	}
	if c.Digest != found.IntentDigest || c.Authority.Revision != found.AuthorityRevision {
		return nil, found, violation("intent_digest_mismatch")
	}
	if c.TaskID != found.TaskID || c.Agent.ID != agentID || c.Agent.Platform != platform {
		return nil, found, violation("intent_agent_mismatch")
	}
	if err := c.Active(time.Now()); err != nil {
		return nil, found, err
	}
	return &c, found, nil
}
