package provenance

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"time"
)

const MaxNodes = 1024
const MaxEdges = 4096
const MaxDepth = 64

func (s *Store) graphDir(scope Scope) string {
	digest, _ := ContentDigest(unsignedRecord(scope))
	return filepath.Join(s.dir, "provenance-assertions", digest)
}
func (s *Store) loadAssertion(id string, scope Scope) (Assertion, error) {
	var a Assertion
	if !identifier.MatchString(id) || !scope.valid() {
		return a, failure("provenance_authority_invalid")
	}
	fi, dirErr := os.Lstat(s.graphDir(scope))
	if errors.Is(dirErr, os.ErrNotExist) {
		return a, failure("provenance_not_found")
	}
	if dirErr != nil || !fi.IsDir() || fi.Mode()&os.ModeSymlink != 0 {
		return a, failure("provenance_signature_invalid")
	}
	err := readRecord(filepath.Join(s.graphDir(scope), id+".json"), &a)
	if errors.Is(err, os.ErrNotExist) {
		return a, failure("provenance_not_found")
	}
	if err != nil {
		return a, failure("provenance_signature_invalid")
	}
	if a.ProvenanceID != id {
		return a, failure("provenance_signature_invalid")
	}
	return a, nil
}

type graphNode struct {
	assertion Assertion
	height    int
}
type graphWalk struct {
	active map[string]bool
	done   map[string]graphNode
	edges  int
}

func (s *Store) resolveNode(a Assertion, scope Scope, now time.Time, depth int, w *graphWalk) (graphNode, error) {
	if depth > MaxDepth {
		return graphNode{}, failure("provenance_capacity")
	}
	if w.active[a.ProvenanceID] {
		return graphNode{}, failure("provenance_derivation_unknown")
	}
	if old, ok := w.done[a.ProvenanceID]; ok {
		if depth+old.height-1 > MaxDepth {
			return graphNode{}, failure("provenance_capacity")
		}
		return old, nil
	}
	issuer, err := s.getIssuer(a.Issuer)
	if err != nil {
		return graphNode{}, err
	}
	if err := a.VerifyAuthority(issuer, s.key.Public(), scope, now); err != nil {
		return graphNode{}, err
	}
	w.active[a.ProvenanceID] = true
	defer delete(w.active, a.ProvenanceID)
	height := 1
	if a.Derivation == "unknown" && a.Source.Trust != "unknown" {
		return graphNode{}, failure("provenance_derivation_unknown")
	}
	for _, id := range a.Parents {
		w.edges++
		if w.edges > MaxEdges {
			return graphNode{}, failure("provenance_capacity")
		}
		parent, err := s.loadAssertion(id, scope)
		if err != nil {
			return graphNode{}, err
		}
		p, err := s.resolveNode(parent, scope, now, depth+1, w)
		if err != nil {
			return graphNode{}, err
		}
		if trustRanks[a.Source.Trust] > trustRanks[p.assertion.Source.Trust] {
			return graphNode{}, failure("provenance_trust_insufficient")
		}
		if p.assertion.Derivation == "unknown" && a.Derivation != "unknown" {
			return graphNode{}, failure("provenance_derivation_unknown")
		}
		if a.Source.Type != p.assertion.Source.Type && a.Source.Type != "AGENT" && a.Source.Type != "UNKNOWN" {
			return graphNode{}, failure("provenance_source_not_allowed")
		}
		expires, _ := time.Parse(time.RFC3339, a.ExpiresAt)
		parentExpires, _ := time.Parse(time.RFC3339, p.assertion.ExpiresAt)
		if expires.After(parentExpires) {
			return graphNode{}, failure("provenance_expired")
		}
		if p.height+1 > height {
			height = p.height + 1
		}
	}
	node := graphNode{a, height}
	if len(w.done) >= MaxNodes {
		return graphNode{}, failure("provenance_capacity")
	}
	w.done[a.ProvenanceID] = node
	return node, nil
}
func newWalk() *graphWalk { return &graphWalk{active: map[string]bool{}, done: map[string]graphNode{}} }
func (s *Store) Resolve(id string, scope Scope, now time.Time) (Assertion, error) {
	storeMu.RLock()
	defer storeMu.RUnlock()
	a, err := s.loadAssertion(id, scope)
	if err != nil {
		return Assertion{}, err
	}
	n, err := s.resolveNode(a, scope, now, 1, newWalk())
	return n.assertion, err
}
func (s *Store) IssueAssertion(a Assertion, now time.Time) (Assertion, error) {
	storeMu.Lock()
	defer storeMu.Unlock()
	if a.Signature != "" || a.SigningSchema != "" && a.SigningSchema != signing.SchemaLocalCanonicalV1 {
		return Assertion{}, failure("provenance_authority_invalid")
	}
	issuer, err := s.getIssuer(a.Issuer)
	if err != nil {
		return Assertion{}, err
	}
	if issuer.LocalKeyRef != "local-state" {
		return Assertion{}, failure("provenance_issuer_untrusted")
	}
	a.SigningSchema = signing.SchemaLocalCanonicalV1
	a.Signature, err = s.key.SignCanonical(a.Unsigned())
	if err != nil {
		return Assertion{}, err
	}
	return s.importAssertion(a, now)
}
func (s *Store) ImportAssertion(a Assertion, now time.Time) (Assertion, error) {
	storeMu.Lock()
	defer storeMu.Unlock()
	return s.importAssertion(a, now)
}
func (s *Store) importAssertion(a Assertion, now time.Time) (Assertion, error) {
	if _, err := s.resolveNode(a, a.Scope, now, 1, newWalk()); err != nil {
		return Assertion{}, err
	}
	dir := s.graphDir(a.Scope)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return Assertion{}, err
	}
	fi, err := os.Lstat(dir)
	if err != nil || !fi.IsDir() || fi.Mode()&os.ModeSymlink != 0 {
		return Assertion{}, failure("provenance_state_unavailable")
	}
	path := filepath.Join(dir, a.ProvenanceID+".json")
	if _, err := os.Lstat(path); err == nil {
		old, err := s.loadAssertion(a.ProvenanceID, a.Scope)
		if err != nil {
			return Assertion{}, err
		}
		x, _ := json.Marshal(a)
		y, _ := json.Marshal(old)
		if bytes.Equal(x, y) {
			return old, nil
		}
		return Assertion{}, failure("provenance_immutable_conflict")
	} else if !errors.Is(err, os.ErrNotExist) {
		return Assertion{}, err
	}
	f, err := os.Open(dir)
	if err != nil {
		return Assertion{}, err
	}
	entries, err := f.ReadDir(MaxNodes + 1)
	_ = f.Close()
	if err != nil && err != io.EOF {
		return Assertion{}, err
	}
	if len(entries) >= MaxNodes {
		return Assertion{}, failure("provenance_capacity")
	}
	edges := len(a.Parents)
	for _, entry := range entries {
		var old Assertion
		if err := readRecord(filepath.Join(dir, entry.Name()), &old); err != nil {
			return Assertion{}, failure("provenance_signature_invalid")
		}
		issuer, err := s.getIssuer(old.Issuer)
		if err != nil {
			return Assertion{}, err
		}
		public := s.key.Public()
		if issuer.PublicKey != "" {
			raw, _ := base64.StdEncoding.Strict().DecodeString(issuer.PublicKey)
			public = ed25519.PublicKey(raw)
		}
		if old.Scope != a.Scope || entry.Name() != old.ProvenanceID+".json" || old.Validate() != nil || signing.VerifyWithSchema(old.SigningSchema, public, old.Unsigned(), old.Signature) != nil {
			return Assertion{}, failure("provenance_signature_invalid")
		}
		edges += len(old.Parents)
	}
	if edges > MaxEdges {
		return Assertion{}, failure("provenance_capacity")
	}
	if err := publishRecord(path, a); err != nil {
		return Assertion{}, err
	}
	return a, nil
}
