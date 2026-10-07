package runtimeidentity

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
)

func nativeFixture(t *testing.T) (*Store, CreateRequest, *grant.Grant) {
	s, req, g := fixture(t)
	req.SchemaVersion = "local-runtime-identity-create/v3"
	req.NativeSkillPolicy = &NativeSkillPolicy{Mode: "required", RuntimeArtifactSHA256: strings.Repeat("c", 64)}
	return s, req, g
}

func TestNativePolicyIndependentOfCallPresenceAndSurvivesRestart(t *testing.T) {
	s, req, _ := nativeFixture(t)
	r, token := create(t, s, req)
	if r.SchemaVersion != "local-runtime-identity/v4" {
		t.Fatal("wrong identity version")
	}
	for _, name := range []string{"native-skill-sessions", "native-skill-calls", "skill-contexts-v2"} {
		if _, err := os.Lstat(filepath.Join(s.dir, name)); !os.IsNotExist(err) {
			t.Fatal("fixture already has native calls")
		}
	}
	p, err := s.NativePolicy(r.Platform, r.AgentID)
	if err != nil || !sameNativePolicy(p, req.NativeSkillPolicy) {
		t.Fatal("required policy absent", err)
	}
	p.Mode = "optional"
	req.NativeSkillPolicy.RuntimeArtifactSHA256 = strings.Repeat("d", 64)
	reopened, err := Open(s.dir, s.key, s.intents, s.resolve)
	if err != nil {
		t.Fatal(err)
	}
	p, err = reopened.NativePolicy(r.Platform, r.AgentID)
	if err != nil || p.Mode != "required" || p.RuntimeArtifactSHA256 != strings.Repeat("c", 64) {
		t.Fatal("policy changed", err)
	}
	if _, err := reopened.Enroll(token, "native-session"); err != nil {
		t.Fatal(err)
	}
	if _, err := reopened.AuthorizeSession(token, r.Platform, r.AgentID, "native-session"); err != nil {
		t.Fatal(err)
	}
	if _, err := reopened.AuthorizeSession(token, r.Platform, r.AgentID, "missing-session"); err == nil {
		t.Fatal("policy query authorized missing session")
	}
	if _, err := reopened.Revoke(r.IdentityID, "fixture-human"); err != nil {
		t.Fatal(err)
	}
	if _, err := reopened.NativePolicy(r.Platform, r.AgentID); err == nil {
		t.Fatal("revocation downgraded to legacy")
	}
}

func TestNativeRequestIdentityInheritsPolicyAndRejectsDowngrade(t *testing.T) {
	s, req, _ := nativeFixture(t)
	root, token := create(t, s, req)
	cap := RequestIssuerCreate{SchemaVersion: "local-runtime-request-issuer-create/v1", ParentIdentityID: root.IdentityID, ScopeID: strings.Repeat("a", 24), MaxIdentitySeconds: 300, ExpiresAt: time.Now().UTC().Add(time.Hour).Format(time.RFC3339), ActorID: "fixture-operator"}
	body := RequestIdentityCreate{SchemaVersion: "local-runtime-request-identity-create/v1", RequestID: "qwen-request-0123456789abcdef", ExecutionSHA256: strings.Repeat("d", 64), ExpiresAt: time.Now().UTC().Add(240 * time.Second).Format(time.RFC3339)}
	child, childToken := issueRequest(t, s, token, cap, body)
	if child.SchemaVersion != "local-runtime-identity/v5" || !sameNativePolicy(child.NativeSkillPolicy, root.NativeSkillPolicy) || child.NativeSkillPolicy == root.NativeSkillPolicy {
		t.Fatal("policy not independently inherited")
	}
	session := child.RequestScope.SessionNamespace + ":" + strings.Repeat("b", 64)
	if _, err := s.Enroll(childToken, session); err != nil {
		t.Fatal(err)
	}
	if _, err := s.AuthorizeSession(childToken, child.Platform, child.AgentID, session); err != nil {
		t.Fatal(err)
	}
	childCap := cap
	childCap.ParentIdentityID = child.IdentityID
	if _, err := s.EnableRequestIssuer(childCap); err == nil {
		t.Fatal("native request child became issuer")
	}
	for _, change := range []func(*Record){
		func(r *Record) { r.SchemaVersion, r.NativeSkillPolicy = "local-runtime-identity/v3", nil },
		func(r *Record) {
			r.NativeSkillPolicy = &NativeSkillPolicy{Mode: "required", RuntimeArtifactSHA256: strings.Repeat("e", 64)}
		},
	} {
		bad := child
		change(&bad)
		bad.Signature, _ = s.sign(bad)
		if s.checkRequestRecord(bad) == nil {
			t.Fatal("signed child policy downgrade or drift accepted")
		}
	}
	if _, _, err := s.CancelRequest(token, cancelBody(body)); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Authenticate(childToken); err == nil {
		t.Fatal("cancelled native request still authenticates")
	}
	if policy, err := s.NativePolicy(root.Platform, root.AgentID); err != nil || !sameNativePolicy(policy, root.NativeSkillPolicy) {
		t.Fatal("request cancellation downgraded root policy", err)
	}
	if _, err := s.Revoke(root.IdentityID, "fixture-human"); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Authenticate(childToken); err == nil {
		t.Fatal("revoked parent still authorizes native child")
	}
}

func TestNativePolicyInvalidAndLegacyEnrollment(t *testing.T) {
	for _, kind := range []string{"missing", "optional", "bad-digest", "legacy-version", "windows-profile", "skill-baseline", "openclaw"} {
		t.Run(kind, func(t *testing.T) {
			s, req, g := nativeFixture(t)
			switch kind {
			case "missing":
				req.NativeSkillPolicy = nil
			case "optional":
				req.NativeSkillPolicy.Mode = "optional"
			case "bad-digest":
				req.NativeSkillPolicy.RuntimeArtifactSHA256 = "unknown"
			case "legacy-version":
				req.SchemaVersion = "local-runtime-identity-create/v1"
			case "windows-profile":
				req.ConfirmFilesystemProfile = true
			case "skill-baseline":
				g.Skill = &grant.SkillRef{SkillID: "fixture", ContentHash: strings.Repeat("a", 64)}
				g.Signature, _ = s.sign(*g)
			case "openclaw":
				s, req = openClawFixture(t)
				req.SchemaVersion = "local-runtime-identity-create/v3"
				req.NativeSkillPolicy = &NativeSkillPolicy{Mode: "required", RuntimeArtifactSHA256: strings.Repeat("c", 64)}
			}
			if _, err := s.Create(req); err == nil {
				t.Fatal("invalid native enrollment accepted")
			}
			ids, err := recordIDs(filepath.Join(s.dir, "runtime-identities"), maxIdentities)
			if err != nil || len(ids) != 0 {
				t.Fatal("invalid enrollment published identity", err)
			}
		})
	}
	s, req, _ := fixture(t)
	r, _ := create(t, s, req)
	if p, err := s.NativePolicy(r.Platform, r.AgentID); err != nil || p != nil {
		t.Fatal("legacy policy changed", err)
	}
	if p, err := s.NativePolicy("hermes", "ordinary-agent"); err != nil || p != nil {
		t.Fatal("ordinary Agent changed", err)
	}
	if _, err := s.NativePolicy("hermes", "hri-"+strings.Repeat("f", 32)); err == nil {
		t.Fatal("missing managed identity downgraded")
	}
}

func TestNativePolicyMissingCorruptConflictingAndDriftingAuthority(t *testing.T) {
	for _, kind := range []string{"missing", "corrupt", "conflict", "grant", "resolver", "wrong-platform"} {
		t.Run(kind, func(t *testing.T) {
			s, req, g := nativeFixture(t)
			r, _ := create(t, s, req)
			platform := r.Platform
			switch kind {
			case "missing":
				if err := os.Remove(s.recordPath(r.IdentityID)); err != nil {
					t.Fatal(err)
				}
			case "corrupt":
				if err := os.WriteFile(s.recordPath(r.IdentityID), []byte("{}"), 0600); err != nil {
					t.Fatal(err)
				}
			case "conflict":
				duplicate := r
				duplicate.IdentityID = "ri-" + strings.Repeat("f", 32)
				duplicate.Signature, _ = s.sign(duplicate)
				raw, _ := json.Marshal(duplicate)
				if err := publish(s.recordPath(duplicate.IdentityID), raw); err != nil {
					t.Fatal(err)
				}
			case "grant":
				g.Status = "revoked"
				g.Signature, _ = s.sign(*g)
			case "resolver":
				s.resolve = func(string) (string, error) { return "", ErrUnavailable }
			case "wrong-platform":
				platform = "openclaw"
			}
			if _, err := s.NativePolicy(platform, r.AgentID); err == nil {
				t.Fatal("unverifiable native authority downgraded")
			}
		})
	}
}

func TestNativePolicySharedContractSamples(t *testing.T) {
	s, req, _ := nativeFixture(t)
	root, _ := create(t, s, req)
	// Stable public signing vectors from product records; never issued credentials.
	root.IdentityID = "ri-" + strings.Repeat("1", 32)
	root.CreatedAt = "2026-10-07T00:00:00Z"
	root.CredentialHash = strings.Repeat("0", 64)
	root.Signature, _ = s.sign(root)
	child := root
	child.SchemaVersion = "local-runtime-identity/v5"
	child.RequestScope = &RequestScope{ParentIdentityID: root.IdentityID, ParentSHA256: recordDigest(root), IssuerSHA256: strings.Repeat("2", 64), ScopeID: strings.Repeat("3", 24), RequestID: "qwen-request-0123456789abcdef", ExecutionSHA256: strings.Repeat("4", 64), SessionNamespace: requestNamespace(strings.Repeat("3", 24), "qwen-request-0123456789abcdef"), ExpiresAt: "2026-10-07T00:05:00Z"}
	child.IdentityID = requestIdentityID(root.IdentityID, child.RequestScope.RequestID)
	child.SessionTTLSeconds = 300
	child.Signature, _ = s.sign(child)
	for name, value := range map[string]any{"local-runtime-identity-native-v4.sample.json": root, "local-runtime-identity-native-v5.sample.json": child, "local-runtime-identity-create-native-v3.sample.json": req} {
		raw, _ := json.MarshalIndent(value, "", "  ")
		raw = append(raw, '\n')
		path := "../../testdata/contracts/" + name
		if os.Getenv("SIQ_UPDATE_NATIVE_IDENTITY_FIXTURES") == "1" {
			if err := os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
		}
		want, err := os.ReadFile(path)
		if err != nil || string(want) != string(raw) {
			t.Fatal("native contract drift", name, err)
		}
		if strings.Contains(name, "create") {
			continue
		}
		var parsed Record
		if json.Unmarshal(raw, &parsed) != nil || !s.verify(parsed, parsed.Signature) {
			t.Fatal("native signature unreadable")
		}
		for _, bad := range []string{strings.Replace(string(raw), `"mode": "required"`, `"mode": "optional"`, 1), strings.Replace(string(raw), `"native_skill_policy"`, `"Native_Skill_Policy"`, 1), strings.Replace(string(raw), `"mode": "required"`, `"mode": "required", "mode": "required"`, 1)} {
			if json.Unmarshal([]byte(bad), &parsed) == nil {
				t.Fatal("malformed native policy decoded")
			}
		}
	}
}
