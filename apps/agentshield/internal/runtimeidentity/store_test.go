package runtimeidentity

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func fixture(t *testing.T) (*Store, CreateRequest, *grant.Grant) {
	t.Helper()
	key, _ := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	instance := "hi-" + strings.Repeat("1", 32)
	agent, _ := AgentID(instance)
	adm := admission.Admission{AdmissionID: "adm-runtime-identity", ContentHash: strings.Repeat("a", 64), Verdict: "admit", DeclaredFacts: []admission.DeclaredFact{{Domain: "tool", Action: "tool.invoke", Resource: admission.Resource{Type: "tool", Value: "read_file"}, Effect: "allow", State: "declared", Authority: "skill_manifest"}}}
	result, err := grant.Build(adm, grant.Options{Platform: "hermes", Subject: grant.Subject{Type: "agent_instance", ID: agent}, Now: time.Date(2026, 9, 10, 0, 0, 0, 0, time.UTC), Key: key})
	if err != nil {
		t.Fatal(err)
	}
	g, err := grant.Approve(result.Grant, grant.Approval{ActorType: "human", ActorID: "fixture-operator", ApprovedAt: "2026-09-10T00:00:00Z", Channel: "console"}, key)
	if err != nil {
		t.Fatal(err)
	}
	g, err = grant.MarkDeployed(g, key)
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	intents, err := intent.Open(dir, key, func(id string) (*grant.Grant, int, error) {
		if id != g.GrantID {
			return nil, 0, os.ErrNotExist
		}
		return &g, 3, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	s, err := Open(dir, key, intents, func(id string) error {
		if id != instance {
			return ErrUnavailable
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return s, CreateRequest{SchemaVersion: "local-runtime-identity-create/v1", InstanceID: instance, GrantID: g.GrantID, ExpectedGrantRevision: 3, ActorID: "fixture-operator", SessionTTLSeconds: 28800}, &g
}
func create(t *testing.T, s *Store, req CreateRequest) (Record, string) {
	t.Helper()
	r, err := s.Create(req)
	if err != nil {
		t.Fatal(err)
	}
	path, _ := s.CredentialPath(r.IdentityID)
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return r, string(b)
}
func TestIdentityIssuanceRestartRevocationAndReplacement(t *testing.T) {
	s, req, _ := fixture(t)
	r, token := create(t, s, req)
	if _, err := s.Authenticate(token); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{s.recordPath(r.IdentityID), filepath.Join(s.dir, "runtime-identity-secrets", r.IdentityID+".token")} {
		info, err := os.Stat(path)
		if err != nil || info.Mode().Perm() != 0600 {
			t.Fatal("private file", err)
		}
	}
	public, _ := json.Marshal(r)
	if bytes.Contains(public, []byte(token)) || bytes.Contains(public, []byte(token[36:])) {
		t.Fatal("plaintext token in record")
	}
	reopened, err := Open(s.dir, s.key, s.intents, s.resolve)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = reopened.Authenticate(token); err != nil {
		t.Fatal("restart", err)
	}
	if _, err = reopened.Create(req); !errors.Is(err, ErrConflict) {
		t.Fatal("duplicate", err)
	}
	rev, err := reopened.Revoke(r.IdentityID, "human-revoker")
	if err != nil {
		t.Fatal(err)
	}
	if !s.verify(rev, rev.Signature) {
		t.Fatal("unsigned revocation")
	}
	retry, err := s.Revoke(r.IdentityID, "different-retry-actor")
	if err != nil || retry != rev {
		t.Fatal("revoke replay", err)
	}
	if _, err = s.Authenticate(token); err == nil {
		t.Fatal("revoked credential accepted")
	}
	newer, newToken := create(t, s, req)
	if newer.IdentityID == r.IdentityID || newToken == token {
		t.Fatal("identity reused")
	}
	if _, err = s.Authenticate(newToken); err != nil {
		t.Fatal(err)
	}
	if _, err = s.Authenticate(token); err == nil {
		t.Fatal("old identity resurrected")
	}
}
func TestIdentityInvalidCreationAndNoSecretPublication(t *testing.T) {
	for _, kind := range []string{"revision", "instance", "actor", "ttl_short", "ttl_long", "schema", "grant", "unknown_instance"} {
		t.Run(kind, func(t *testing.T) {
			s, req, _ := fixture(t)
			switch kind {
			case "revision":
				req.ExpectedGrantRevision--
			case "instance":
				req.InstanceID = "../escape"
			case "actor":
				req.ActorID = "\n"
			case "ttl_short":
				req.SessionTTLSeconds = 59
			case "ttl_long":
				req.SessionTTLSeconds = 86401
			case "schema":
				req.SchemaVersion = "future"
			case "grant":
				req.GrantID = "missing"
			case "unknown_instance":
				req.InstanceID = "hi-" + strings.Repeat("2", 32)
			}
			if _, err := s.Create(req); err == nil {
				t.Fatal("invalid issuance")
			}
			for _, name := range []string{"runtime-identities", "runtime-identity-secrets"} {
				files, _ := os.ReadDir(filepath.Join(s.dir, name))
				if len(files) != 0 {
					t.Fatal("invalid issuance wrote files")
				}
			}
		})
	}
	for _, ttl := range []int{60, 86400} {
		s, req, _ := fixture(t)
		req.SessionTTLSeconds = ttl
		if _, err := s.Create(req); err != nil {
			t.Fatal("valid boundary", err)
		}
	}
}
func TestIdentityGrantChangesAndForgery(t *testing.T) {
	for _, kind := range []string{"revoked", "unsigned_change", "signed_change", "subject", "expired", "malformed", "token", "wrong_key"} {
		t.Run(kind, func(t *testing.T) {
			s, req, g := fixture(t)
			r, token := create(t, s, req)
			switch kind {
			case "revoked":
				next, err := grant.Revoke(*g, s.key)
				if err != nil {
					t.Fatal(err)
				}
				*g = next
			case "unsigned_change":
				g.Facts[0].Resource.Value = "write_file"
			case "signed_change":
				g.Status = "approved"
				g.Facts[0].Resource.Value = "write_file"
				next, err := grant.MarkDeployed(*g, s.key)
				if err != nil {
					t.Fatal(err)
				}
				*g = next
			case "subject":
				g.Status = "approved"
				g.Subject.ID = "different"
				next, err := grant.MarkDeployed(*g, s.key)
				if err != nil {
					t.Fatal(err)
				}
				*g = next
			case "expired":
				at := time.Now().Add(-time.Hour).UTC().Format(time.RFC3339)
				g.ExpiresAt = &at
				g.Signature, _ = s.sign(*g)
			case "malformed":
				token = "bad"
			case "token":
				token = token[:36] + strings.Repeat("0", 64)
			case "wrong_key":
				key, _ := signing.FromSeed(bytes.Repeat([]byte{8}, 32))
				s.key = key
			}
			if _, err := s.Authenticate(token); err == nil {
				t.Fatal("accepted changed authority")
			}
			if kind == "revoked" {
				if _, err := s.Revoke(r.IdentityID, "operator"); err != nil {
					t.Fatal("cannot revoke inactive Grant", err)
				}
			}
		})
	}
}
func TestIdentityCorruptAndAliasedRecordsFailClosed(t *testing.T) {
	for _, kind := range []string{"signature", "alias", "duplicate", "null", "oversize", "revocation", "revocation_retarget", "missing_record", "ancestor_link", "record_link", "permissions"} {
		t.Run(kind, func(t *testing.T) {
			s, req, _ := fixture(t)
			r, token := create(t, s, req)
			path := s.recordPath(r.IdentityID)
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			switch kind {
			case "signature":
				raw = bytes.Replace(raw, []byte(`"actor_id":"fixture-operator"`), []byte(`"actor_id":"attacker"`), 1)
			case "alias":
				raw = bytes.Replace(raw, []byte(`"agent_id"`), []byte(`"Agent_ID"`), 1)
			case "duplicate":
				raw = append([]byte(`{"agent_id":"attacker",`), raw[1:]...)
			case "null":
				raw = bytes.Replace(raw, []byte(`"session_ttl_seconds":28800`), []byte(`"session_ttl_seconds":null`), 1)
			case "oversize":
				raw = bytes.Repeat([]byte(" "), maxRecordBytes+1)
			case "revocation":
				path = s.revokedPath(r.IdentityID)
				raw = []byte("broken")
			case "revocation_retarget":
				rev := Revocation{SchemaVersion: "local-runtime-identity-revocation/v1", IdentityID: r.IdentityID, IdentityDigest: strings.Repeat("0", 64), ActorID: "operator", RevokedAt: time.Now().UTC().Format(time.RFC3339Nano)}
				rev.Signature, _ = s.sign(rev)
				raw, _ = json.Marshal(rev)
				path = s.revokedPath(r.IdentityID)
			case "missing_record":
				if err = os.Remove(path); err != nil {
					t.Fatal(err)
				}
			case "ancestor_link":
				dir := filepath.Dir(path)
				if err = os.Rename(dir, dir+"-original"); err != nil {
					t.Fatal(err)
				}
				if err = os.Symlink(dir+"-original", dir); err != nil {
					t.Fatal(err)
				}
			case "record_link":
				if err = os.Rename(path, path+".original"); err != nil {
					t.Fatal(err)
				}
				if err = os.Symlink(path+".original", path); err != nil {
					t.Fatal(err)
				}
			case "permissions":
				if err = os.Chmod(path, 0644); err != nil {
					t.Fatal(err)
				}
			}
			switch kind {
			case "missing_record", "ancestor_link", "record_link", "permissions":
			default:
				if err = os.WriteFile(path, raw, 0600); err != nil {
					t.Fatal(err)
				}
			}
			if _, err = s.Authenticate(token); err == nil {
				t.Fatal("corrupt authority accepted")
			}
		})
	}
}
func TestIdentityInterruptedPublicationCannotAuthenticate(t *testing.T) {
	s, req, _ := fixture(t)
	calls := 0
	s.resolve = func(string) error {
		calls++
		if calls > 1 {
			return ErrUnavailable
		}
		return nil
	}
	if _, err := s.Create(req); err == nil {
		t.Fatal("interrupted create accepted")
	}
	secrets, err := os.ReadDir(filepath.Join(s.dir, "runtime-identity-secrets"))
	if err != nil || len(secrets) != 1 {
		t.Fatal("expected orphan secret", err)
	}
	raw, err := os.ReadFile(filepath.Join(s.dir, "runtime-identity-secrets", secrets[0].Name()))
	if err != nil {
		t.Fatal(err)
	}
	if _, err = s.Authenticate(string(raw)); err == nil {
		t.Fatal("orphan credential accepted")
	}
	records, _ := os.ReadDir(filepath.Join(s.dir, "runtime-identities"))
	if len(records) != 0 {
		t.Fatal("partial issuance is authority")
	}
}
func TestIdentityConcurrentHandlesOneIssuance(t *testing.T) {
	s, req, _ := fixture(t)
	other, err := Open(s.dir, s.key, s.intents, s.resolve)
	if err != nil {
		t.Fatal(err)
	}
	var passed atomic.Int32
	var wg sync.WaitGroup
	for i := 0; i < 12; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			current := s
			if i%2 == 0 {
				current = other
			}
			_, e := current.Create(req)
			if e == nil {
				passed.Add(1)
			} else if !errors.Is(e, ErrConflict) {
				t.Error(e)
			}
		}(i)
	}
	wg.Wait()
	if passed.Load() != 1 {
		t.Fatal("duplicate identity publication", passed.Load())
	}
}
func TestIdentityBoundedFilesAndExclusivePublication(t *testing.T) {
	dir := t.TempDir()
	if err := os.Chmod(dir, 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "immutable")
	if err := publish(path, []byte("first")); err != nil {
		t.Fatal(err)
	}
	if err := publish(path, []byte("second")); !errors.Is(err, os.ErrExist) {
		t.Fatal("overwrote record", err)
	}
	raw, _ := os.ReadFile(path)
	if string(raw) != "first" {
		t.Fatal("changed original")
	}
	scan := filepath.Join(dir, "scan")
	if err := os.Mkdir(scan, 0700); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 3; i++ {
		if err := os.WriteFile(filepath.Join(scan, fmt.Sprintf("ri-%032x.json", i)), []byte("{}"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	if ids, err := recordIDs(scan, 3); err != nil || len(ids) != 3 {
		t.Fatal("exact scan budget", err)
	}
	if _, err := recordIDs(scan, 2); err == nil {
		t.Fatal("unbounded scan")
	}
}
func TestIdentitySharedContractFixtures(t *testing.T) {
	s, req, _ := fixture(t)
	r, token := create(t, s, req)
	if _, err := s.Authenticate(token); err != nil {
		t.Fatal(err)
	}
	// Normalize only exported synthetic fixture nondeterminism; the actual signed
	// storage above was independently authenticated before normalization.
	r.IdentityID = "ri-" + strings.Repeat("3", 32)
	r.CreatedAt = "2026-09-10T00:00:00Z"
	r.CredentialHash = strings.Repeat("b", 64)
	r.Signature, _ = s.sign(r)
	rev := Revocation{SchemaVersion: "local-runtime-identity-revocation/v1", IdentityID: r.IdentityID, IdentityDigest: recordDigest(r), ActorID: "fixture-revoker", RevokedAt: "2026-09-10T01:00:00Z"}
	rev.Signature, _ = s.sign(rev)
	for name, value := range map[string]any{"local-runtime-identity-create": req, "local-runtime-identity": r, "local-runtime-identity-revocation": rev} {
		b, err := json.MarshalIndent(value, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		b = append(b, '\n')
		path := filepath.Join("..", "..", "testdata", "contracts", name+".json")
		if os.Getenv("SIQ_UPDATE_RUNTIME_IDENTITY_FIXTURES") == "1" {
			if err = os.WriteFile(path, b, 0600); err != nil {
				t.Fatal(err)
			}
		}
		want, err := os.ReadFile(path)
		if err != nil || !bytes.Equal(want, b) {
			t.Fatalf("shared fixture %s differs: %v", name, err)
		}
	}
}

func TestEmptyToolGrantDoesNotPublishIdentityOrSecret(t *testing.T) {
	s, req, g := fixture(t)
	g.Facts = nil
	empty := []string{}
	g.HermesToolsetAllowlist = &empty
	var err error
	g.Signature, err = s.sign(*g)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.Create(req); !errors.Is(err, ErrNoTools) {
		t.Fatal("empty grant issuance", err)
	}
	for _, dir := range []string{"runtime-identities", "runtime-identity-secrets"} {
		entries, err := os.ReadDir(filepath.Join(s.dir, dir))
		if err != nil && !os.IsNotExist(err) {
			t.Fatal(err)
		}
		if len(entries) != 0 {
			t.Fatal("published unusable authority", dir)
		}
	}
}
