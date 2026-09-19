package runtimecheck

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/state"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestWindowsCheckCurrentAuthorityRevalidated(t *testing.T) {
	for _, mode := range []string{"grant_revoked", "intent_revoked", "binding_revoked", "directory_replaced", "snapshot_changed", "final_grant_revoked"} {
		t.Run(mode, func(t *testing.T) {
			fx := newManagerFixture(t)
			var reached atomic.Bool
			fx.m.launchHost = func(_ context.Context, r *run, _ adapterinstall.RuntimeTarget, nonce string, p probes) error {
				if err := fx.runProbes(r, nonce, p, true); err != nil {
					return err
				}
				reached.Store(true)
				c, b, err := fx.m.o.Intents.ResolveBinding("hermes", r.session, agentID(r.id))
				if err != nil {
					return err
				}
				if c.SchemaVersion != intent.RuntimeCheckSchema || b.SchemaVersion != "intent-grant-binding/v2" || b.SelectedGrant == nil || b.SelectedGrant.SchemaVersion != "grant/v2" || b.SelectedGrant.Skill != nil {
					return errors.New("wrong Windows authority version")
				}
				switch mode {
				case "grant_revoked", "final_grant_revoked":
					g, seq, e := fx.m.o.Store.GetGrantWithSeq(r.record.GrantID)
					if e != nil {
						return e
					}
					next, e := grant.Revoke(*g, fx.m.o.Key)
					if e != nil {
						return e
					}
					_, err = fx.m.o.Store.CommitGrant(state.GrantCommit{Grant: next, ExpectedRevision: seq, Audit: &state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339Nano), Event: "runtime_check_test_revoke", ActorID: "operator", Target: g.GrantID}})
				case "intent_revoked":
					_, err = fx.m.o.Intents.RevokeIntent(c.IntentID, c.Digest)
				case "binding_revoked":
					_, err = fx.m.o.Intents.RevokeBinding(b.BindingID, c.Digest)
				case "directory_replaced":
					allowed := filepath.Dir(p.first)
					if err = os.Rename(allowed, allowed+"-old"); err == nil {
						err = os.Mkdir(allowed, 0700)
					}
				case "snapshot_changed":
					fx.changed.Store(true)
				}
				if err != nil {
					return err
				}
				if fx.m.AuthorizeDecision(nonce, "hermes", agentID(r.id), r.session) {
					return errors.New("changed authority accepted for decision or observation")
				}
				// Final verifier must reject even though all five receipts already exist.
				return nil
			}
			plan, _ := startFixture(t, fx)
			out := awaitResult(t, fx.m, plan.ID)
			if !reached.Load() {
				t.Fatalf("did not reach live authority mutation: %+v", out)
			}
			if out.Status == "passed" || out.Cleanup != "complete" {
				t.Fatalf("stale authority passed or leaked: %+v", out)
			}
		})
	}
}

func TestWindowsCheckPreviewRequiresActivatedProfileAndTrustedRoot(t *testing.T) {
	fx := newManagerFixture(t)
	snapshot := fx.m.o.Snapshot
	for _, mode := range []string{"missing_profile", "wrong_root_identity", "wrong_instance"} {
		t.Run(mode, func(t *testing.T) {
			fx.m.o.Snapshot = func(id string) (adapterinstall.RuntimeTarget, error) {
				v, e := snapshot(id)
				if e != nil {
					return v, e
				}
				switch mode {
				case "missing_profile":
					v.FilesystemProfile = ""
					v.RootIdentityDigest = ""
				case "wrong_root_identity":
					v.RootIdentityDigest = strings.Repeat("0", 64)
				case "wrong_instance":
					v.InstanceID = "hi-" + strings.Repeat("b", 32)
				}
				return v, nil
			}
			if _, err := fx.m.Preview(testInstance, "admin"); err == nil {
				t.Fatal("untrusted target accepted")
			}
		})
	}
	fx.m.o.Snapshot = snapshot
	st, err := state.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	original := fx.m.o.Store
	fx.m.o.Store = st
	if _, err := fx.m.Preview(testInstance, "admin"); err == nil {
		t.Fatal("unactivated state accepted")
	}
	fx.m.o.Store = original
	if grants, err := original.ListGrants(); err != nil || len(grants) != 0 {
		t.Fatal("preview created authority", err)
	}
}
