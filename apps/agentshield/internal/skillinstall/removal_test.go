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

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
	"siq-agent-security/apps/agentshield/internal/state"
)

func removalRequest(t *testing.T, s *Store, id string) RemoveRequest {
	t.Helper()
	v, err := s.ReadRemoval(nil, id)
	if err != nil {
		t.Fatal(err)
	}
	return RemoveRequest{"local-skill-install-remove/v1", v.Record.Operation.Signature, *v.StateRevision, v.BindingSignature, "human", true}
}
func TestRemovalRevokesBeforeCleaningAndNeverTouchesReusedPath(t *testing.T) {
	f, op, activation := readyActivation(t)
	s := f.store
	if _, err := s.Activate(nil, op.InstallID, activation); err != nil {
		t.Fatal(err)
	}
	s.authority.SetRuntimeGrantCheck(func(g *grant.Grant) error { return s.ValidateRuntimeGrant(nil, g) })
	intents, err := s.authority.IntentAuthority(s.key)
	if err != nil {
		t.Fatal(err)
	}
	identityStore, err := runtimeidentity.Open(s.authority.Dir, s.key, intents, func(string) error { return nil })
	if err != nil {
		t.Fatal(err)
	}
	g, rev, err := s.authority.GetGrantWithSeq(f.request.GrantID)
	if err != nil {
		t.Fatal(err)
	}
	identity, err := identityStore.Create(runtimeidentity.CreateRequest{SchemaVersion: "local-runtime-identity-create/v1", InstanceID: f.request.InstanceID, GrantID: g.GrantID, ExpectedGrantRevision: rev, ActorID: "human", SessionTTLSeconds: 600})
	if err != nil {
		t.Fatal(err)
	}
	secretPath, _ := identityStore.CredentialPath(identity.IdentityID)
	secret, err := os.ReadFile(secretPath)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := identityStore.Enroll(string(secret), "before-removal"); err != nil {
		t.Fatal(err)
	}
	req := removalRequest(t, s, op.InstallID)
	target := filepath.Join(f.root, "skills", "example")
	sawRevocation := false
	s.boundary = func(phase string) error {
		if phase == "removal_authority_ready" {
			current, _, err := s.authority.GetGrantWithSeq(g.GrantID)
			if err != nil || current.Status != "revoked" || !grant.Verify(s.key.Public(), *current) {
				t.Fatal("cleanup before complete revocation", err)
			}
			if _, err := os.Stat(filepath.Join(target, "SKILL.md")); err != nil {
				t.Fatal("file deleted before revocation boundary", err)
			}
			if _, err := identityStore.Authenticate(string(secret)); err == nil {
				t.Fatal("revoked installation authenticated")
			}
			sawRevocation = true
		}
		return nil
	}
	out, err := s.Remove(nil, op.InstallID, req)
	if err != nil || out.Status != "removed" || !out.Result.GrantRevoked || !sawRevocation || out.Grant != nil || out.StateRevision != nil {
		t.Fatal(out, err)
	}
	if _, err := os.Stat(target); !os.IsNotExist(err) {
		t.Fatal("target retained", err)
	}
	if _, err := identityStore.AuthorizeSession(string(secret), "hermes", g.Subject.ID, "before-removal"); err == nil {
		t.Fatal("old session retained authority")
	}
	// A later user directory at this path does not belong to this completed removal.
	write(t, filepath.Join(target, "user.txt"), "keep user content")
	again, err := s.Remove(nil, op.InstallID, req)
	if err != nil || !sameDocument(out, again) {
		t.Fatal("retry changed completed result", err)
	}
	raw, err := os.ReadFile(filepath.Join(target, "user.txt"))
	if err != nil || string(raw) != "keep user content" {
		t.Fatal("removed reused path", err)
	}
}
func TestRemovalPreservesChangesAndRestoresOnlyOriginalRequest(t *testing.T) {
	f, op := installedInspection(t)
	s := f.store
	req := removalRequest(t, s, op.InstallID)
	target := filepath.Join(f.root, "skills", "example")
	write(t, filepath.Join(target, "user.txt"), "keep")
	// Source validity is irrelevant to withdrawing permission and cleaning owned files.
	write(t, filepath.Join(s.authority.Dir, "skill-imports", "blobs", f.importID, "payload", "SKILL.md"), "changed source")
	v, err := s.Remove(nil, op.InstallID, req)
	if !errors.Is(err, ErrRecoveryRequired) || v.Status != "cleanup_pending" {
		t.Fatal(v, err)
	}
	if _, err := os.Stat(filepath.Join(target, "SKILL.md")); err != nil {
		t.Fatal("partial preflight deleted original file", err)
	}
	wrong := req
	wrong.ActorID = "different"
	if _, err := s.Remove(nil, op.InstallID, wrong); !errors.Is(err, ErrConflict) {
		t.Fatal("retry changed actor", err)
	}
	if err := os.Remove(filepath.Join(target, "user.txt")); err != nil {
		t.Fatal(err)
	}
	v, err = s.Remove(nil, op.InstallID, req)
	if err != nil || v.Status != "removed" {
		t.Fatal(v, err)
	}
}
func TestRemovalPreservesGrantBoundToAnotherInstallation(t *testing.T) {
	f, op, activation := readyActivation(t)
	s := f.store
	otherRequest := f.request
	otherRequest.RequestID = "is-" + strings.Repeat("e", 32)
	otherRequest.DirectoryName = "other"
	p, _, err := s.Stage(nil, otherRequest)
	if err != nil {
		t.Fatal(err)
	}
	other, err := s.Apply(nil, ApplyRequest{"local-skill-install-apply/v1", p.PlanID, p.Signature, p.ActorID, true})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.Activate(nil, op.InstallID, activation); err != nil {
		t.Fatal(err)
	}
	req := removalRequest(t, s, other.InstallID)
	v, err := s.ReadRemoval(nil, other.InstallID)
	if err != nil || v.WillRevokeGrant || v.RetainedInstallID != op.InstallID {
		t.Fatal(v, err)
	}
	before, revision, err := s.authority.GetGrantWithSeq(f.request.GrantID)
	if err != nil {
		t.Fatal(err)
	}
	out, err := s.Remove(nil, other.InstallID, req)
	if err != nil || out.Status != "removed" || out.Result.GrantRevoked || out.Result.RetainedInstallID != op.InstallID {
		t.Fatal(out, err)
	}
	after, afterRevision, err := s.authority.GetGrantWithSeq(f.request.GrantID)
	if err != nil || revision != afterRevision || after.Signature != before.Signature {
		t.Fatal("other installation grant changed", err)
	}
	if err := s.ValidateRuntimeGrant(nil, after); err != nil {
		t.Fatal("other installation lost runtime authority", err)
	}
	if _, err := s.ReadOperation(nil, op.InstallID); err != nil {
		t.Fatal("other target changed", err)
	}
}
func TestPendingRemovalPreventsReactivationAndAuditFailurePreservesFiles(t *testing.T) {
	for _, phase := range []string{"claim", "audit"} {
		t.Run(phase, func(t *testing.T) {
			f, op, activation := readyActivation(t)
			s := f.store
			req := removalRequest(t, s, op.InstallID)
			if phase == "claim" {
				s.boundary = func(p string) error {
					if p == "removal_claim_published" {
						return errors.New("interrupt")
					}
					return nil
				}
			} else {
				audit := filepath.Join(s.authority.Dir, "commit-audit", f.request.GrantID+"."+fmt.Sprint(req.ExpectedGrantRevision+1)+".json")
				if err := os.MkdirAll(audit, 0700); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := s.Remove(nil, op.InstallID, req); err == nil {
				t.Fatal("interruption not reached")
			}
			if _, err := os.Stat(filepath.Join(f.root, "skills", "example", "SKILL.md")); err != nil {
				t.Fatal("failed revocation deleted target", err)
			}
			if _, err := s.Activate(nil, op.InstallID, activation); !errors.Is(err, ErrRemovalPending) {
				t.Fatal("reactivated pending removal", err)
			}
			if phase == "claim" {
				v, err := s.ReadRemoval(nil, op.InstallID)
				if err != nil || v.Status != "revocation_pending" {
					t.Fatal(v, err)
				}
				s.boundary = func(string) error { return nil }
				if v, err := s.Remove(nil, op.InstallID, req); err != nil || v.Status != "removed" {
					t.Fatal(v, err)
				}
			} else {
				if _, _, err := s.authority.GetGrantWithSeq(f.request.GrantID); !errors.Is(err, state.ErrIncompleteCommit) {
					t.Fatal(err)
				}
				if _, err := s.ReadRemoval(nil, op.InstallID); err == nil {
					t.Fatal("incomplete audit became completed removal")
				}
			}
		})
	}
}
func TestRemovalRejectsStaleAndImplicitRequests(t *testing.T) {
	f, op := installedInspection(t)
	req := removalRequest(t, f.store, op.InstallID)
	for _, mutate := range []func(*RemoveRequest){func(r *RemoveRequest) { r.ConfirmRemove = false }, func(r *RemoveRequest) { r.ExpectedGrantRevision++ }, func(r *RemoveRequest) { r.OperationSignature = strings.Repeat("f", 128) }, func(r *RemoveRequest) { r.ExpectedBindingSignature = strings.Repeat("f", 128) }, func(r *RemoveRequest) { r.ActorID = "" }} {
		bad := req
		mutate(&bad)
		if _, err := f.store.Remove(nil, op.InstallID, bad); err == nil {
			t.Fatal("invalid request accepted")
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := f.store.Remove(ctx, op.InstallID, req); !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
	if err := f.store.removalStarted(op.InstallID); err != nil {
		t.Fatal("rejected request published claim", err)
	}
}
func TestRemovalContractSamples(t *testing.T) {
	f, op := installedInspection(t)
	s := f.store
	req := removalRequest(t, s, op.InstallID)
	v, err := s.Remove(nil, op.InstallID, req)
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile("../../testdata/contracts/local-skill-install-record.v1.sample.json")
	if err != nil {
		t.Fatal(err)
	}
	var record Record
	if err := json.Unmarshal(raw, &record); err != nil {
		t.Fatal(err)
	}
	v.Record = record
	c := v.Claim
	r := v.Result
	c.InstallID = record.InstallID
	c.InstallationClaimSignature = record.ClaimSignature
	c.OperationSignature = record.Operation.Signature
	c.GrantID = record.Plan.GrantID
	c.GrantRevision = record.Plan.GrantRevision
	c.GrantSignature = record.Plan.GrantSignature
	c.CreatedAt = "2026-09-11T04:10:00Z"
	doc, err := document(c, false)
	if err != nil {
		t.Fatal(err)
	}
	c.Signature, err = s.key.SignCanonical(doc)
	if err != nil {
		t.Fatal(err)
	}
	r.InstallID = c.InstallID
	r.RemovalClaimSignature = c.Signature
	r.GrantID = c.GrantID
	r.GrantRevision = c.GrantRevision + 1
	// The post-revocation signature reference is opaque in this response. The
	// state/authority test above verifies the actual Grant; this is a wire fixture.
	r.GrantSignature = strings.Repeat("e", 128)
	r.RecordedAt = "2026-09-11T04:10:01Z"
	doc, err = document(r, false)
	if err != nil {
		t.Fatal(err)
	}
	r.Signature, err = s.key.SignCanonical(doc)
	if err != nil {
		t.Fatal(err)
	}
	req.OperationSignature = c.OperationSignature
	req.ExpectedGrantRevision = c.GrantRevision
	for name, value := range map[string]any{"remove": req, "removal-claim": c, "removal-result": r, "removal-view": v} {
		raw, err := json.MarshalIndent(value, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		raw = append(raw, '\n')
		path := "../../testdata/contracts/local-skill-install-" + name + ".v1.sample.json"
		if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
			if err := os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
		}
		expected, err := os.ReadFile(path)
		if err != nil || string(expected) != string(raw) {
			t.Fatal("removal sample differs", name, err)
		}
	}
}

func TestPendingRemovalCannotMoveGrantToAnotherInstallation(t *testing.T) {
	f, original, _ := readyActivation(t)
	req := f.request
	req.RequestID = "is-" + strings.Repeat("e", 32)
	req.DirectoryName = "other"
	plan, _, err := f.store.Stage(nil, req)
	if err != nil {
		t.Fatal(err)
	}
	other, err := f.store.Apply(nil, ApplyRequest{"local-skill-install-apply/v1", plan.PlanID, plan.Signature, plan.ActorID, true})
	if err != nil {
		t.Fatal(err)
	}
	removal := removalRequest(t, f.store, original.InstallID)
	f.store.boundary = func(phase string) error {
		if phase == "removal_claim_published" {
			return errors.New("interrupt before revocation")
		}
		return nil
	}
	if _, err := f.store.Remove(nil, original.InstallID, removal); err == nil {
		t.Fatal("interruption not reached")
	}
	activation := ActivateRequest{"local-skill-install-activate/v1", other.Signature, plan.GrantRevision, "human", true}
	if _, err := f.store.Activate(nil, other.InstallID, activation); !errors.Is(err, ErrRemovalPending) {
		t.Fatal("pending Grant moved to another installation", err)
	}
	if _, err := f.store.runtimeBinding(context.Background(), req.GrantID); !errors.Is(err, ErrNotFound) {
		t.Fatal("rejected activation published runtime binding", err)
	}
	if _, err := f.store.ReadOperation(nil, other.InstallID); err != nil {
		t.Fatal("other target changed", err)
	}
}

func TestRemovalClaimScanBudget(t *testing.T) {
	f, _ := installedInspection(t)
	dir := filepath.Join(f.store.dir, "removals")
	for i := 0; i < 256; i++ {
		write(t, filepath.Join(dir, fmt.Sprintf("ignored-%03d", i)), "unrelated entry")
	}
	if err := f.store.pendingGrantRemoval(context.Background(), f.request.GrantID); err != nil {
		t.Fatal("exact entry budget rejected", err)
	}
	write(t, filepath.Join(dir, "one-more"), "unrelated entry")
	if err := f.store.pendingGrantRemoval(context.Background(), f.request.GrantID); !errors.Is(err, ErrLimit) {
		t.Fatal("overflow did not fail closed", err)
	}
}
