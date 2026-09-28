package adapterinstall

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/acltest"
	"siq-agent-security/apps/agentshield/internal/adapters"
	"siq-agent-security/apps/agentshield/internal/privatefs"
)

func TestWorkBuddyManagedPreflightRejectsPrivateObjectDrift(t *testing.T) {
	for _, target := range []string{"config_parent", "config_file", "credential_parent", "credential_file", "credential_missing", "config_hardlink"} {
		t.Run(target, func(t *testing.T) {
			o := workBuddyManagedOptions(t)
			if _, err := Install(o); err != nil {
				t.Fatal(err)
			}
			settings := filepath.Join(o.configRoot(), "settings.json")
			before, _ := os.ReadFile(settings)
			path, root, code := workBuddyManagedConfigPath(o), o.Home, "workbuddy_config_file_unavailable"
			switch target {
			case "config_parent":
				path, code = o.configRoot(), "workbuddy_config_parent_unavailable"
			case "credential_parent":
				path, root, code = filepath.Dir(managedCredentialPath(o)), o.StateDir, "workbuddy_credential_parent_unavailable"
			case "credential_file", "credential_missing":
				path, root, code = managedCredentialPath(o), o.StateDir, "workbuddy_credential_file_unavailable"
			}
			if target == "credential_missing" {
				if err := os.Remove(path); err != nil {
					t.Fatal(err)
				}
			} else if target == "config_hardlink" {
				if err := os.Link(path, filepath.Join(o.Home, "external-alias")); err != nil {
					t.Fatal(err)
				}
			} else {
				acltest.BroadenRead(t, root, path)
			}
			if _, err := Prepare(o, "install"); err == nil {
				t.Fatal("unsafe configuration accepted by install preview")
			} else {
				var failure *adapters.WorkBuddyPreflightError
				if !errors.As(err, &failure) || failure.Code != code {
					t.Fatalf("wrong preflight category: %v, want %s", err, code)
				}
			}
			d := Inspect(o)
			if checkStatus(d, "service_configuration") != "fail" || checkStatus(d, code) != "fail" || d.RuntimeState != "unverified" {
				t.Fatalf("unsafe configuration reported ready: %+v", d)
			}
			after, _ := os.ReadFile(settings)
			if string(after) != string(before) {
				t.Fatal("preview or diagnosis modified host settings")
			}
		})
	}
}

func TestWorkBuddyManagedApplyRechecksACLBeforeAndAfterWrites(t *testing.T) {
	for _, boundary := range []string{"before_apply", "prepared", "audited", "committed_retry"} {
		t.Run(boundary, func(t *testing.T) {
			o := workBuddyManagedOptions(t)
			p := testPlan(t, o, "install")
			settings := filepath.Join(o.configRoot(), "settings.json")
			before, _ := os.ReadFile(settings)
			if boundary == "committed_retry" {
				if _, err := Apply(p); err != nil {
					t.Fatal(err)
				}
			}
			var restore func()
			if boundary == "before_apply" || boundary == "committed_retry" {
				restore = acltest.BroadenRead(t, o.Home, o.configRoot())
			} else {
				transactionBoundary = func(at string) error {
					if at == boundary {
						restore = acltest.BroadenRead(t, o.Home, o.configRoot())
					}
					return nil
				}
				t.Cleanup(func() { transactionBoundary = func(string) error { return nil } })
			}
			result, err := Apply(p)
			if err == nil {
				t.Fatal("ACL drift reported successful")
			}
			if boundary == "audited" {
				if result == nil || result.Action != "recovery_required" {
					t.Fatal("unsafe rollback did not retain recovery", result, err)
				}
				if privatefs.CheckDir(o.configRoot()) == nil {
					t.Fatal("host ACL silently repaired")
				}
				restore()
				if _, err := RecoverInstance(o); err != nil {
					t.Fatal("safe retry could not restore original config", err)
				}
			}
			if boundary != "committed_retry" {
				after, _ := os.ReadFile(settings)
				if string(after) != string(before) {
					t.Fatal("host settings not restored")
				}
			}
			if boundary != "audited" && privatefs.CheckDir(o.configRoot()) == nil {
				t.Fatal("host ACL silently repaired")
			}
		})
	}
}
