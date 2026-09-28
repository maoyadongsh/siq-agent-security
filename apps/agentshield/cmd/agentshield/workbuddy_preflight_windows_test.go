package main

import (
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"

	"siq-agent-security/apps/agentshield/internal/acltest"
	"siq-agent-security/apps/agentshield/internal/adapters"
)

func TestWorkBuddyHookAndDiagnosisSharePrivatePreconditions(t *testing.T) {
	for _, target := range []string{"config_parent", "config_file", "credential_parent", "credential_file", "config_hardlink", "credential_hardlink"} {
		t.Run(target, func(t *testing.T) {
			var requests atomic.Int32
			cfg, config := managedWorkBuddyFixture(t, func(w http.ResponseWriter, r *http.Request) { requests.Add(1) })
			path, root, code := config, filepath.Dir(config), "workbuddy_config_file_unavailable"
			switch target {
			case "config_parent":
				path, code = filepath.Dir(config), "workbuddy_config_parent_unavailable"
			case "credential_parent":
				path, root, code = filepath.Dir(cfg.CredentialPath), cfg.StateDir, "workbuddy_credential_parent_unavailable"
			case "credential_file", "credential_hardlink":
				path, root, code = cfg.CredentialPath, cfg.StateDir, "workbuddy_credential_file_unavailable"
			}
			if strings.HasSuffix(target, "hardlink") {
				if err := os.Link(path, filepath.Join(t.TempDir(), "alias")); err != nil {
					t.Fatal(err)
				}
			} else {
				acltest.BroadenRead(t, root, path)
			}
			_, err := adapters.InspectWorkBuddyManagedConfig(config, cfg.StateDir)
			var failure *adapters.WorkBuddyPreflightError
			if !errors.As(err, &failure) || failure.Code != code {
				t.Fatalf("wrong diagnosis: %v", err)
			}
			out := runManagedWorkBuddy(t, cfg, config, managedWorkBuddyInput)
			if out.HookSpecificOutput.PermissionDecision != "deny" || requests.Load() != 0 {
				t.Fatalf("private precondition did not block before network: %+v, requests %d", out, requests.Load())
			}
			if strings.Contains(out.HookSpecificOutput.PermissionDecisionReason, code) {
				t.Fatal("private diagnostic category exposed to model")
			}
		})
	}
}

func TestWorkBuddyDiagnosisDoesNotReadCredentialContents(t *testing.T) {
	var requests atomic.Int32
	cfg, config := managedWorkBuddyFixture(t, func(w http.ResponseWriter, r *http.Request) { requests.Add(1) })
	// Malformed secret bytes do not affect metadata-only diagnosis. Only the hook
	// consumes the bearer, and it must reject it before sending a request.
	if err := os.WriteFile(cfg.CredentialPath, []byte("invalid synthetic credential"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := adapters.InspectWorkBuddyManagedConfig(config, cfg.StateDir); err != nil {
		t.Fatal(err)
	}
	out := runManagedWorkBuddy(t, cfg, config, managedWorkBuddyInput)
	if out.HookSpecificOutput.PermissionDecision != "deny" || requests.Load() != 0 {
		t.Fatal("invalid credential sent")
	}
}
