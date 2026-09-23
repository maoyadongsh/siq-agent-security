package runtimeidentity

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
)

func requestFixture(t *testing.T) (*Store, Record, string, RequestIssuerCreate, RequestIdentityCreate, *grant.Grant) {
	t.Helper()
	s, rootReq, g := fixture(t)
	root, token := create(t, s, rootReq)
	cap := RequestIssuerCreate{SchemaVersion: "local-runtime-request-issuer-create/v1", ParentIdentityID: root.IdentityID, ScopeID: strings.Repeat("a", 24), MaxIdentitySeconds: 300, ExpiresAt: time.Now().UTC().Add(time.Hour).Format(time.RFC3339), ActorID: "fixture-operator"}
	req := RequestIdentityCreate{SchemaVersion: "local-runtime-request-identity-create/v1", RequestID: "qwen-request-0123456789abcdef", ExecutionSHA256: strings.Repeat("d", 64), ExpiresAt: time.Now().UTC().Add(240 * time.Second).Format(time.RFC3339)}
	return s, root, token, cap, req, g
}
func issueRequest(t *testing.T, s *Store, token string, cap RequestIssuerCreate, req RequestIdentityCreate) (Record, string) {
	t.Helper()
	if _, err := s.EnableRequestIssuer(cap); err != nil {
		t.Fatal(err)
	}
	r, err := s.IssueRequest(token, req)
	if err != nil {
		t.Fatal(err)
	}
	path, _ := s.CredentialPath(r.IdentityID)
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return r, string(raw)
}
func cancelBody(req RequestIdentityCreate) RequestIdentityCancel {
	return RequestIdentityCancel{SchemaVersion: "local-runtime-request-identity-cancel/v1", RequestID: req.RequestID, ExecutionSHA256: req.ExecutionSHA256}
}
func TestRequestIssuerExplicitImmutableAndBounded(t *testing.T) {
	s, root, token, cap, req, _ := requestFixture(t)
	if _, err := s.IssueRequest(token, req); err == nil {
		t.Fatal("implicit delegation")
	}
	issuer, err := s.EnableRequestIssuer(cap)
	if err != nil {
		t.Fatal(err)
	}
	retry, err := s.EnableRequestIssuer(cap)
	if err != nil || retry != issuer {
		t.Fatal("issuer retry changed authority")
	}
	for _, change := range []func(*RequestIssuerCreate){
		func(v *RequestIssuerCreate) { v.ScopeID = strings.Repeat("b", 24) },
		func(v *RequestIssuerCreate) { v.MaxIdentitySeconds++ },
		func(v *RequestIssuerCreate) { v.ExpiresAt = time.Now().UTC().Add(2 * time.Hour).Format(time.RFC3339) },
		func(v *RequestIssuerCreate) { v.ActorID = "different" },
		func(v *RequestIssuerCreate) { v.MaxIdentitySeconds = 59 },
		func(v *RequestIssuerCreate) { v.MaxIdentitySeconds = 3601 },
		func(v *RequestIssuerCreate) { v.ExpiresAt = time.Now().UTC().Add(25 * time.Hour).Format(time.RFC3339) },
		func(v *RequestIssuerCreate) { v.ExpiresAt = time.Now().UTC().Add(-time.Second).Format(time.RFC3339) },
	} {
		bad := cap
		change(&bad)
		if _, err := s.EnableRequestIssuer(bad); err == nil {
			t.Fatal("issuer mutation allowed")
		}
	}
	child, childToken := issueRequest(t, s, token, cap, req)
	if child.GrantRef != root.GrantRef || child.AgentID != root.AgentID || child.InstanceID != root.InstanceID || child.IdentityID == root.IdentityID {
		t.Fatal("authority changed")
	}
	badCap := cap
	badCap.ParentIdentityID = child.IdentityID
	if _, err := s.EnableRequestIssuer(badCap); err == nil {
		t.Fatal("child became issuer")
	}
	req.RequestID = "qwen-request-1111111111111111"
	if _, err := s.IssueRequest(childToken, req); err == nil {
		t.Fatal("child delegated")
	}
	selected, err := s.InspectByInstance(root.InstanceID)
	if err != nil || selected.IdentityID != root.IdentityID {
		t.Fatal("child selected as root")
	}
}
func TestRequestRetryIndependentSessionsAndEnvelopeDeadline(t *testing.T) {
	s, root, token, cap, req, _ := requestFixture(t)
	child, childToken := issueRequest(t, s, token, cap, req)
	reopened, err := Open(s.dir, s.key, s.intents, s.resolve)
	if err != nil {
		t.Fatal(err)
	}
	retry, err := reopened.IssueRequest(token, req)
	if err != nil || !reflect.DeepEqual(retry, child) {
		t.Fatal("retry changed identity")
	}
	req2 := req
	req2.RequestID = "qwen-request-2222222222222222"
	other, err := s.IssueRequest(token, req2)
	if err != nil || other.IdentityID == child.IdentityID {
		t.Fatal("requests share identity", err)
	}
	bad := req
	bad.ExecutionSHA256 = strings.Repeat("e", 64)
	if _, err := s.IssueRequest(token, bad); err == nil {
		t.Fatal("execution rebound")
	}
	bad = req
	bad.ExpiresAt = time.Now().UTC().Add(250 * time.Second).Format(time.RFC3339)
	if _, err := s.IssueRequest(token, bad); err == nil {
		t.Fatal("retry extended deadline")
	}
	session := child.RequestScope.SessionNamespace + ":" + strings.Repeat("b", 64)
	binding, err := s.Enroll(childToken, session)
	if err != nil {
		t.Fatal(err)
	}
	c, err := s.intents.Get(binding.IntentID)
	if err != nil {
		t.Fatal(err)
	}
	if c.ExpiresAt != req.ExpiresAt {
		t.Fatal("session exceeds request deadline")
	}
	if _, err := s.AuthorizeSession(childToken, root.Platform, root.AgentID, session); err != nil {
		t.Fatal(err)
	}
	if err := s.VerifySessionAuthority(c, session); err != nil {
		t.Fatal(err)
	}
	for _, otherSession := range []string{"native-root", other.RequestScope.SessionNamespace + ":" + strings.Repeat("b", 64), child.RequestScope.SessionNamespace, session + "a", strings.ToUpper(session)} {
		if _, err := s.Enroll(childToken, otherSession); err == nil {
			t.Fatal("session boundary bypass")
		}
	}
	if _, err := s.Revoke(root.IdentityID, "fixture-operator"); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Authenticate(childToken); err == nil {
		t.Fatal("revoked parent authenticated child")
	}
	if _, err := s.AuthorizeSession(childToken, root.Platform, root.AgentID, session); err == nil {
		t.Fatal("revoked parent authorized session")
	}
	if err := s.VerifySessionAuthority(c, session); err == nil {
		t.Fatal("observer accepted revoked parent")
	}
	if _, err := s.Enroll(childToken, session); err == nil {
		t.Fatal("revoked parent re-enrolled session")
	}
	summary, err := s.Summary(child.IdentityID)
	if err != nil || summary.Status != "grant_unavailable" {
		t.Fatal("stale summary")
	}
	if _, err := s.RevokeSelf(childToken); err != nil {
		t.Fatal("cleanup blocked", err)
	}
}
func TestRequestCancellationBeforeAndAfterIssuance(t *testing.T) {
	for _, issued := range []bool{false, true} {
		t.Run(map[bool]string{false: "before", true: "after"}[issued], func(t *testing.T) {
			s, root, token, cap, req, g := requestFixture(t)
			if _, err := s.EnableRequestIssuer(cap); err != nil {
				t.Fatal(err)
			}
			var childToken string
			if issued {
				_, childToken = issueRequest(t, s, token, cap, req)
			}
			id, didIssue, err := s.CancelRequest(token, cancelBody(req))
			if err != nil || didIssue != issued || id != requestIdentityID(root.IdentityID, req.RequestID) {
				t.Fatal("cancel", err)
			}
			before, err := os.ReadFile(s.requestPath("runtime-request-cancellations", id))
			if err != nil {
				t.Fatal(err)
			}
			if _, err := s.IssueRequest(token, req); err == nil {
				t.Fatal("cancelled request resurrected")
			}
			if issued {
				if _, err := s.Authenticate(childToken); err == nil {
					t.Fatal("cancelled child active")
				}
			}
			if _, err := s.Revoke(root.IdentityID, "fixture-operator"); err != nil {
				t.Fatal(err)
			}
			g.Status = "revoked"
			g.Signature, _ = s.sign(*g)
			s.resolve = func(string) (string, error) { return "", ErrUnavailable }
			if _, _, err := s.CancelRequest(token, cancelBody(req)); err != nil {
				t.Fatal("cleanup requires execution authority", err)
			}
			after, _ := os.ReadFile(s.requestPath("runtime-request-cancellations", id))
			if string(after) != string(before) {
				t.Fatal("cancellation audit overwritten")
			}
			bad := cancelBody(req)
			bad.ExecutionSHA256 = strings.Repeat("e", 64)
			if _, _, err := s.CancelRequest(token, bad); err == nil {
				t.Fatal("wrong execution cancelled")
			}
		})
	}
}
func TestRequestRevocationAndCancellationRace(t *testing.T) {
	s, _, token, cap, req, _ := requestFixture(t)
	if _, err := s.EnableRequestIssuer(cap); err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	for i := 0; i < 12; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			if i%3 == 0 {
				_, _, _ = s.CancelRequest(token, cancelBody(req))
			} else {
				_, _ = s.IssueRequest(token, req)
			}
		}(i)
	}
	wg.Wait()
	if _, err := s.IssueRequest(token, req); err == nil {
		t.Fatal("race restored authority")
	}
	if _, _, err := s.CancelRequest(token, cancelBody(req)); err != nil {
		t.Fatal(err)
	}
	ids, err := recordIDs(filepath.Join(s.dir, "runtime-identities"), maxIdentities)
	if err != nil || len(ids) > 2 {
		t.Fatal("duplicate issuance")
	}
}
func TestRequestAttemptResumesOnlyExactOriginal(t *testing.T) {
	s, root, token, cap, req, _ := requestFixture(t)
	child, childToken := issueRequest(t, s, token, cap, req)
	// Simulate death after durable attempt/secret but before final authority publication.
	if err := os.Remove(s.recordPath(child.IdentityID)); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Authenticate(childToken); err == nil {
		t.Fatal("orphan secret authenticated")
	}
	bad := req
	bad.ExecutionSHA256 = strings.Repeat("e", 64)
	if _, err := s.IssueRequest(token, bad); err == nil {
		t.Fatal("attempt rebound")
	}
	resumed, err := s.IssueRequest(token, req)
	if err != nil || !reflect.DeepEqual(child, resumed) {
		t.Fatal("resume changed signed authority", err)
	}
	if _, err := s.Authenticate(childToken); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Revoke(root.IdentityID, "fixture-operator"); err != nil {
		t.Fatal(err)
	}
	_, rootReq, _ := fixture(t)
	rootReq.InstanceID = root.InstanceID
	rootReq.GrantID = root.GrantRef.GrantID
	if _, err := s.Create(rootReq); err != nil {
		t.Fatal("child blocked replacement root", err)
	}
}
func TestRequestCorruptStateNeverRecreatedOrReportedCancelled(t *testing.T) {
	for _, kind := range []string{"runtime-request-issuers", "runtime-request-attempts", "runtime-identities", "runtime-request-cancellations"} {
		t.Run(kind, func(t *testing.T) {
			s, root, token, cap, req, _ := requestFixture(t)
			child, _ := issueRequest(t, s, token, cap, req)
			id := child.IdentityID
			if kind == "runtime-request-issuers" {
				id = root.IdentityID
			}
			if err := os.WriteFile(s.requestPath(kind, id), []byte("{}"), 0600); err != nil {
				t.Fatal(err)
			}
			// Attempt corruption is checked before completing an interrupted issuance.
			if kind == "runtime-request-attempts" {
				if err := os.Remove(s.recordPath(child.IdentityID)); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := s.IssueRequest(token, req); err == nil {
				t.Fatal("corrupt state issued")
			}
			if _, _, err := s.CancelRequest(token, cancelBody(req)); err == nil {
				t.Fatal("corrupt state reported cancelled")
			}
		})
	}
}
func TestRequestExpiryAndGrantLossRejectButAllowCleanup(t *testing.T) {
	for _, which := range []string{"request", "issuer", "grant", "instance"} {
		t.Run(which, func(t *testing.T) {
			s, _, token, cap, req, g := requestFixture(t)
			child, childToken := issueRequest(t, s, token, cap, req)
			switch which {
			case "request":
				child.RequestScope.ExpiresAt = time.Now().UTC().Add(-time.Second).Format(time.RFC3339)
				child.Signature, _ = s.sign(child)
				raw, _ := json.Marshal(child)
				if err := os.WriteFile(s.recordPath(child.IdentityID), raw, 0600); err != nil {
					t.Fatal(err)
				}
			case "issuer":
				root, _ := s.credentialRecord(token)
				v, _ := s.issuer(root)
				v.ExpiresAt = time.Now().UTC().Add(-time.Second).Format(time.RFC3339)
				v.CreatedAt = time.Now().UTC().Add(-time.Hour).Format(time.RFC3339)
				v.Signature, _ = s.sign(v)
				raw, _ := json.Marshal(v)
				if err := os.WriteFile(s.requestPath("runtime-request-issuers", root.IdentityID), raw, 0600); err != nil {
					t.Fatal(err)
				}
			case "grant":
				g.Status = "revoked"
				g.Signature, _ = s.sign(*g)
			case "instance":
				s.resolve = func(string) (string, error) { return "", ErrUnavailable }
			}
			if _, err := s.Authenticate(childToken); err == nil {
				t.Fatal("lost authority accepted")
			}
			if _, err := s.RevokeSelf(childToken); err != nil {
				t.Fatal("self cleanup blocked", err)
			}
		})
	}
}

func TestRequestPrivateCredentialRetryRejectsUnsafeOrLostFile(t *testing.T) {
	for _, which := range []string{"missing", "symlink", "directory", "public", "wrong-token"} {
		t.Run(which, func(t *testing.T) {
			s, _, token, cap, req, _ := requestFixture(t)
			child, secret := issueRequest(t, s, token, cap, req)
			path, _ := s.CredentialPath(child.IdentityID)
			switch which {
			case "missing":
				if err := os.Remove(path); err != nil {
					t.Fatal(err)
				}
			case "symlink":
				target := filepath.Join(t.TempDir(), "fixture-token")
				if err := os.WriteFile(target, []byte(secret), 0600); err != nil {
					t.Fatal(err)
				}
				if err := os.Remove(path); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(target, path); err != nil {
					t.Fatal(err)
				}
			case "directory":
				if err := os.Remove(path); err != nil {
					t.Fatal(err)
				}
				if err := os.Mkdir(path, 0700); err != nil {
					t.Fatal(err)
				}
			case "public":
				if err := os.Chmod(path, 0644); err != nil {
					t.Fatal(err)
				}
			case "wrong-token":
				if err := os.WriteFile(path, []byte(child.IdentityID+"."+strings.Repeat("e", 64)), 0600); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := s.IssueRequest(token, req); err == nil {
				t.Fatal("unsafe credential retry accepted")
			}
			if which == "missing" {
				if _, err := os.Lstat(path); !os.IsNotExist(err) {
					t.Fatal("lost credential silently recreated")
				}
			}
		})
	}
}
func TestRequestGrantDeadlineAndCanonicalTimeBounds(t *testing.T) {
	s, _, token, cap, req, _ := requestFixture(t)
	if _, err := s.EnableRequestIssuer(cap); err != nil {
		t.Fatal(err)
	}
	for _, expiry := range []string{time.Now().UTC().Add(-time.Second).Format(time.RFC3339), time.Now().UTC().Add(301 * time.Second).Format(time.RFC3339), time.Now().UTC().Add(120 * time.Second).Format("2006-01-02T15:04:05.000Z"), time.Now().UTC().Add(120 * time.Second).Format("2006-01-02T15:04:05+00:00")} {
		bad := req
		bad.ExpiresAt = expiry
		if _, err := s.IssueRequest(token, bad); err == nil {
			t.Fatal("deadline accepted", expiry)
		}
	}
	// Exact maximum is valid; a changed expiration is not an idempotent retry.
	req.ExpiresAt = time.Now().UTC().Add(300 * time.Second).Format(time.RFC3339)
	if _, err := s.IssueRequest(token, req); err != nil {
		t.Fatal(err)
	}
	for _, seconds := range []int{60, 3600} {
		t.Run(time.Duration(seconds).String(), func(t *testing.T) {
			s, _, token, cap, req, _ := requestFixture(t)
			cap.MaxIdentitySeconds = seconds
			req.ExpiresAt = time.Now().UTC().Add(time.Duration(seconds) * time.Second).Format(time.RFC3339)
			if _, err := s.EnableRequestIssuer(cap); err != nil {
				t.Fatal(err)
			}
			if _, err := s.IssueRequest(token, req); err != nil {
				t.Fatal(err)
			}
		})
	}
	// Configure a short original signed Grant before root creation.
	short, rootReq, g := fixture(t)
	end := time.Now().UTC().Add(120 * time.Second).Format(time.RFC3339)
	g.ExpiresAt = &end
	g.Signature, _ = short.sign(*g)
	root, rootToken := create(t, short, rootReq)
	cap.ParentIdentityID = root.IdentityID
	if _, err := short.EnableRequestIssuer(cap); err == nil {
		t.Fatal("issuer exceeded Grant")
	}
	cap.ExpiresAt = end
	if _, err := short.EnableRequestIssuer(cap); err != nil {
		t.Fatal(err)
	}
	req.ExpiresAt = time.Now().UTC().Add(180 * time.Second).Format(time.RFC3339)
	if _, err := short.IssueRequest(rootToken, req); err == nil {
		t.Fatal("child exceeded Grant")
	}
	req.ExpiresAt = end
	if _, err := short.IssueRequest(rootToken, req); err != nil {
		t.Fatal(err)
	}
}
func TestRequestCancelTombstonePrecedesOrdinaryRevocation(t *testing.T) {
	s, _, token, cap, req, _ := requestFixture(t)
	child, secret := issueRequest(t, s, token, cap, req)
	// A failed second write must not roll back the first cancellation record.
	if err := os.WriteFile(s.revokedPath(child.IdentityID), []byte("{}"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, _, err := s.CancelRequest(token, cancelBody(req)); err == nil {
		t.Fatal("partial cancellation reported complete")
	}
	parent, _ := s.credentialRecord(token)
	cancelled, err := s.requestCancelled(parent.IdentityID, req.RequestID, req.ExecutionSHA256)
	if err != nil || !cancelled {
		t.Fatal("missing primary cancellation audit")
	}
	if _, err := s.Authenticate(secret); err == nil {
		t.Fatal("partial cleanup restored authority")
	}
	if _, err := s.IssueRequest(token, req); err == nil {
		t.Fatal("cancelled issuance resumed")
	}
}
func TestRequestRootSessionCannotBeTakenOver(t *testing.T) {
	s, _, token, cap, req, _ := requestFixture(t)
	child, secret := issueRequest(t, s, token, cap, req)
	session := child.RequestScope.SessionNamespace + ":" + strings.Repeat("b", 64)
	if _, err := s.Enroll(token, session); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Enroll(secret, session); err == nil {
		t.Fatal("child took root session")
	}
	if _, err := s.AuthorizeSession(secret, child.Platform, child.AgentID, session); err == nil {
		t.Fatal("child authorized root session")
	}
}

func TestRequestCapacityBoundsAndRetryAtCapacity(t *testing.T) {
	for _, kind := range []string{"runtime-request-attempts", "runtime-request-cancellations", "runtime-identities"} {
		t.Run(kind, func(t *testing.T) {
			s, _, token, cap, req, _ := requestFixture(t)
			if _, err := s.EnableRequestIssuer(cap); err != nil {
				t.Fatal(err)
			}
			count := maxIdentities - 1
			if kind == "runtime-identities" {
				count--
			} // existing root
			for i := 0; i < count; i++ {
				path := s.requestPath(kind, fmt.Sprintf("ri-%032x", i))
				if err := os.WriteFile(path, []byte("{}"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			if kind == "runtime-request-cancellations" {
				if _, _, err := s.CancelRequest(token, cancelBody(req)); err != nil {
					t.Fatal("exact capacity rejected", err)
				}
				if _, _, err := s.CancelRequest(token, cancelBody(req)); err != nil {
					t.Fatal("retry at capacity rejected", err)
				}
				req.RequestID = "qwen-request-2222222222222222"
				if _, _, err := s.CancelRequest(token, cancelBody(req)); err == nil {
					t.Fatal("capacity exceeded")
				}
			} else {
				child, err := s.IssueRequest(token, req)
				if err != nil {
					t.Fatal("exact capacity rejected", err)
				}
				retry, err := s.IssueRequest(token, req)
				if err != nil || !reflect.DeepEqual(child, retry) {
					t.Fatal("retry at capacity changed authority", err)
				}
				req.RequestID = "qwen-request-2222222222222222"
				if _, err := s.IssueRequest(token, req); err == nil {
					t.Fatal("capacity exceeded")
				}
			}
		})
	}
}
func TestRequestConcurrentIdenticalIssuanceReturnsOneRecord(t *testing.T) {
	s, _, token, cap, req, _ := requestFixture(t)
	if _, err := s.EnableRequestIssuer(cap); err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	out := make(chan Record, 8)
	errs := make(chan error, 8)
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); r, err := s.IssueRequest(token, req); out <- r; errs <- err }()
	}
	wg.Wait()
	close(out)
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	var first Record
	for r := range out {
		if first.IdentityID == "" {
			first = r
		} else if !reflect.DeepEqual(first, r) {
			t.Fatal("concurrent retry diverged")
		}
	}
	ids, err := recordIDs(filepath.Join(s.dir, "runtime-identities"), maxIdentities)
	if err != nil || len(ids) != 2 {
		t.Fatal("duplicate signed issuance")
	}
}
func TestRequestSignedRecordRejectsMalformedScope(t *testing.T) {
	for _, which := range []string{"null", "alias", "unknown", "root-version", "wrong-platform", "namespace", "parent", "digest", "execution", "duplicate"} {
		t.Run(which, func(t *testing.T) {
			s, _, token, cap, req, _ := requestFixture(t)
			child, secret := issueRequest(t, s, token, cap, req)
			raw, _ := json.Marshal(child)
			var doc map[string]any
			_ = json.Unmarshal(raw, &doc)
			scope := doc["request_scope"].(map[string]any)
			switch which {
			case "null":
				doc["request_scope"] = nil
			case "alias":
				doc["Request_Scope"] = doc["request_scope"]
				delete(doc, "request_scope")
			case "unknown":
				scope["allow"] = "*"
			case "root-version":
				doc["schema_version"] = "local-runtime-identity/v1"
			case "wrong-platform":
				doc["platform"] = "openclaw"
			case "namespace":
				scope["session_namespace"] = "native"
			case "parent":
				scope["parent_identity_id"] = child.IdentityID
			case "digest":
				scope["parent_sha256"] = strings.Repeat("e", 64)
			case "execution":
				scope["execution_sha256"] = nil
			}
			// Re-sign the negative fixture to exercise shape/binding checks, not merely
			// the signature mismatch path. This key exists only in the test directory.
			doc["signature"], _ = s.sign(doc)
			raw, _ = json.Marshal(doc)
			if which == "duplicate" {
				raw = []byte(strings.Replace(string(raw), `"request_id":`, `"request_id":"qwen-request-1111111111111111","request_id":`, 1))
			}
			if err := os.WriteFile(s.recordPath(child.IdentityID), raw, 0600); err != nil {
				t.Fatal(err)
			}
			if _, err := s.Authenticate(secret); err == nil {
				t.Fatal("malformed scope authenticated")
			}
		})
	}
}

func TestRequestPrivateV3SharedContractAndSignature(t *testing.T) {
	s, _, token, cap, req, _ := requestFixture(t)
	child, _ := issueRequest(t, s, token, cap, req)
	raw, err := os.ReadFile("../../testdata/contracts/local-runtime-identity-v3.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture Record
	if err = json.Unmarshal(raw, &fixture); err != nil {
		t.Fatal(err)
	}
	if !s.verify(fixture, fixture.Signature) {
		t.Fatal("Python canonical signature differs")
	}
	child.IdentityID = requestIdentityID(fixture.RequestScope.ParentIdentityID, fixture.RequestScope.RequestID)
	child.CreatedAt = fixture.CreatedAt
	child.CredentialHash = fixture.CredentialHash
	child.SessionTTLSeconds = 600
	child.RequestScope = fixture.RequestScope
	child.Signature, err = s.sign(child)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(child, fixture) {
		t.Fatal("private v3 shared sample differs")
	}
}
