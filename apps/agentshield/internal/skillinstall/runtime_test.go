package skillinstall

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
	"siq-agent-security/apps/agentshield/internal/state"
)

func readyActivation(t *testing.T) (fixture, *Operation, ActivateRequest) {
	t.Helper()
	f, p, req := readyInstall(t)
	op, err := f.store.Apply(nil, req)
	if err != nil {
		t.Fatal(err)
	}
	return f, op, ActivateRequest{"local-skill-install-activate/v1", op.Signature, p.GrantRevision, "human", true}
}
func TestInstalledRuntimeBindingAndImmediateInvalidation(t *testing.T) {
	for _, change := range []string{"target", "source", "binding", "revocation", "missing_verifier", "instance"} {
		t.Run(change, func(t *testing.T) {
			f, op, req := readyActivation(t)
			s := f.store
			intents, err := s.authority.IntentAuthority(s.key)
			if err != nil {
				t.Fatal(err)
			}
			result, err := s.Activate(nil, op.InstallID, req)
			if err != nil {
				t.Fatal(err)
			}
			g, revision, err := s.authority.GetGrantWithSeq(result.GrantID)
			if err != nil || g.Status != "approved" || revision != req.ExpectedRevision+1 || result.RuntimeVerified {
				t.Fatal("wrong activation", err)
			}
			if _, err := intents.SelectGrant(g.GrantID, "hermes", g.Subject.ID, revision); err == nil {
				t.Fatal("missing verifier accepted imported Grant")
			}
			rawIntent, err := intent.Open(s.authority.Dir, s.key, s.authority.GetGrantWithSeq)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := rawIntent.SelectGrant(g.GrantID, "hermes", g.Subject.ID, revision); err == nil {
				t.Fatal("raw lookup accepted approved import")
			}
			if s.authority.ActiveGrant("hermes", g.Subject.ID) != nil {
				t.Fatal("legacy implicit lookup exposed installed permissions")
			}
			s.authority.SetRuntimeGrantCheck(func(g *grant.Grant) error { return s.ValidateRuntimeGrant(context.Background(), g) })
			if err := s.ValidateRuntimeGrant(nil, g); err != nil {
				t.Fatal(err)
			}
			again, err := s.Activate(nil, op.InstallID, req)
			if err != nil || !sameDocument(result, again) {
				t.Fatal("retry mutated authority", err)
			}
			ri, err := runtimeidentity.Open(s.authority.Dir, s.key, intents, func(string) error { return nil })
			if err != nil {
				t.Fatal(err)
			}
			record, err := ri.Create(runtimeidentity.CreateRequest{SchemaVersion: "local-runtime-identity-create/v1", InstanceID: f.request.InstanceID, GrantID: g.GrantID, ExpectedGrantRevision: revision, ActorID: "human", SessionTTLSeconds: 600})
			if err != nil {
				t.Fatal(err)
			}
			path, _ := ri.CredentialPath(record.IdentityID)
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			credential := string(raw)
			if _, err := ri.Enroll(credential, "native-session"); err != nil {
				t.Fatal(err)
			}
			if _, err := ri.AuthorizeSession(credential, "hermes", g.Subject.ID, "native-session"); err != nil {
				t.Fatal(err)
			}
			switch change {
			case "target":
				write(t, filepath.Join(f.root, "skills", "example", "SKILL.md"), "changed target")
			case "source":
				write(t, filepath.Join(s.authority.Dir, "skill-imports", "blobs", f.importID, "payload", "SKILL.md"), "changed source")
			case "binding":
				write(t, s.bindingPath(g.GrantID), "{}")
			case "revocation":
				revoked, err := grant.Revoke(*g, s.key)
				if err != nil {
					t.Fatal(err)
				}
				if _, err := s.authority.CommitGrant(state.GrantCommit{Grant: revoked, ExpectedRevision: revision, Audit: &state.AuditEvent{Event: "fixture_revoke", Target: g.GrantID}}); err != nil {
					t.Fatal(err)
				}
			case "missing_verifier":
				s.authority.SetRuntimeGrantCheck(nil)
			case "instance":
				old := s.resolve
				s.resolve = func(ctx context.Context, id string) (Target, error) {
					r, e := old(ctx, id)
					r.InstanceID = "hi-" + strings.Repeat("f", 32)
					return r, e
				}
			}
			if change != "missing_verifier" {
				if _, err := s.ReadReadiness(nil, op.InstallID); err == nil {
					t.Fatal("readiness retained stale authority")
				}
			}
			if _, err := intents.GrantForReference(record.GrantRef, "hermes", g.Subject.ID); err == nil {
				t.Fatal("fixed intent lookup retained stale installation authority")
			}
			if _, err := ri.Authenticate(credential); err == nil {
				t.Fatal("stale installation authenticated")
			}
			if _, err := ri.Enroll(credential, "another-native-session"); err == nil {
				t.Fatal("stale installation enrolled")
			}
			if _, err := ri.AuthorizeSession(credential, "hermes", g.Subject.ID, "native-session"); err == nil {
				t.Fatal("existing session retained stale content authority")
			}
			if summary, err := ri.Summary(record.IdentityID); err != nil || summary.Status != "grant_unavailable" {
				t.Fatal("stale installation summary", summary, err)
			}
		})
	}
}
func TestInstalledRuntimeBindingInterruptedBeforeGrantCommit(t *testing.T) {
	f, op, req := readyActivation(t)
	s := f.store
	s.boundary = func(phase string) error {
		if phase == "runtime_binding_published" {
			return errors.New("interrupt")
		}
		return nil
	}
	if _, err := s.Activate(nil, op.InstallID, req); !errors.Is(err, ErrUnavailable) {
		t.Fatal(err)
	}
	b, err := s.runtimeBinding(context.Background(), f.request.GrantID)
	if err != nil {
		t.Fatal(err)
	}
	g, rev, err := s.authority.GetGrantWithSeq(f.request.GrantID)
	if err != nil || g.Status != "approved" || rev != req.ExpectedRevision {
		t.Fatal("interrupted binding activated permission", err)
	}
	if err := s.ValidateRuntimeGrant(nil, g); err == nil {
		t.Fatal("uncommitted binding was authority")
	}
	wrong := req
	wrong.ActorID = "other"
	if _, err := s.Activate(nil, op.InstallID, wrong); !errors.Is(err, ErrConflict) {
		t.Fatal("actor changed during retry", err)
	}
	s.boundary = func(string) error { return nil }
	s.now = func() time.Time { return time.Now().Add(time.Hour) }
	out, err := s.Activate(nil, op.InstallID, req)
	if err != nil {
		t.Fatal(err)
	}
	if out.Binding.Signature != b.Signature {
		t.Fatal("retry replaced binding")
	}
	// The old five-minute installation preview is not a runtime Grant expiry.
	if out.StateRevision != req.ExpectedRevision+1 {
		t.Fatal("wrong revision")
	}
}
func TestInstalledRuntimeActivationStrictAuthority(t *testing.T) {
	f, op, req := readyActivation(t)
	for _, patch := range []func(*ActivateRequest){func(r *ActivateRequest) { r.ConfirmInstanceScope = false }, func(r *ActivateRequest) { r.ExpectedRevision++ }, func(r *ActivateRequest) { r.OperationSignature = strings.Repeat("a", 128) }, func(r *ActivateRequest) { r.ActorID = " " }} {
		changed := req
		patch(&changed)
		if _, err := f.store.Activate(nil, op.InstallID, changed); err == nil {
			t.Fatal("invalid confirmation accepted")
		}
	}
	g, rev, _ := f.store.authority.GetGrantWithSeq(f.request.GrantID)
	if g.Status != "approved" || rev != req.ExpectedRevision {
		t.Fatal("bad request changed permission")
	}
	if _, err := grant.MarkDeployed(*g, f.store.key); !errors.Is(err, grant.ErrImportInstallationRequired) {
		t.Fatal("generic deployment bypass", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := f.store.Activate(ctx, op.InstallID, req); err == nil {
		t.Fatal("canceled activation accepted")
	}
	write(t, filepath.Join(f.root, "skills", "example", "SKILL.md"), "user-changed")
	if _, err := f.store.Activate(nil, op.InstallID, req); err == nil {
		t.Fatal("changed target accepted")
	}
}
func TestRuntimeBindingContractSamples(t *testing.T) {
	f, op, req := readyActivation(t)
	actual, err := f.store.Activate(nil, op.InstallID, req)
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile("../../testdata/contracts/local-skill-install-view.v1.sample.json")
	if err != nil {
		t.Fatal(err)
	}
	var v View
	if err := json.Unmarshal(raw, &v); err != nil {
		t.Fatal(err)
	}
	b := &actual.Binding
	p := v.Plan
	b.BindingID = bindingID(p.GrantID)
	b.InstallID = v.InstallID
	b.PlanSignature = p.Signature
	b.OperationSignature = v.Operation.Signature
	b.GrantID = p.GrantID
	b.ApprovedRevision = p.GrantRevision
	b.ApprovedSignature = p.GrantSignature
	b.PermissionDigest = p.GrantPermissionDigest
	b.InstanceID = p.InstanceID
	b.Source = p.Source
	b.ActorID = "human"
	b.CreatedAt = "2026-09-11T03:00:03Z"
	doc, err := document(b, false)
	if err != nil {
		t.Fatal(err)
	}
	b.Signature, err = f.store.key.SignCanonical(doc)
	if err != nil {
		t.Fatal(err)
	}
	actual.GrantID = p.GrantID
	actual.StateRevision = p.GrantRevision + 1
	req.OperationSignature = b.OperationSignature
	req.ExpectedRevision = p.GrantRevision
	for name, value := range map[string]any{"runtime-binding": b, "activate": req, "activated": actual} {
		encoded, err := json.MarshalIndent(value, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		encoded = append(encoded, '\n')
		path := "../../testdata/contracts/local-skill-install-" + name + ".v1.sample.json"
		if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
			if err := os.WriteFile(path, encoded, 0600); err != nil {
				t.Fatal(err)
			}
		}
		expected, err := os.ReadFile(path)
		if err != nil || string(expected) != string(encoded) {
			t.Fatal("contract sample differs", name, err)
		}
	}
}

func TestInstalledRuntimeAuditFailureHasNoAuthority(t *testing.T) {
	f, op, req := readyActivation(t)
	s := f.store
	audit := filepath.Join(s.authority.Dir, "commit-audit", f.request.GrantID+"."+fmt.Sprint(req.ExpectedRevision+1)+".json")
	if err := os.MkdirAll(audit, 0700); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Activate(nil, op.InstallID, req); err == nil {
		t.Fatal("missing audit accepted")
	}
	if _, _, err := s.authority.GetGrantWithSeq(f.request.GrantID); !errors.Is(err, state.ErrIncompleteCommit) {
		t.Fatal("incomplete grant readable", err)
	}
	if _, _, err := s.authority.RuntimeGrantWithSeq(f.request.GrantID); err == nil {
		t.Fatal("incomplete grant became authority")
	}
}
