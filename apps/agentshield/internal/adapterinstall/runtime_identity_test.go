package adapterinstall

import (
	"encoding/json"
	"errors"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/hermeshome"
)

func managedTestOptions(t *testing.T) Options {
	t.Helper()
	o := testOpts(t, Hermes)
	root := filepath.Join(o.Home, ".hermes", "profiles", "work")
	o.Instance = &InstanceTarget{ID: hermeshome.Identifier(root), Name: "work", ConfigDir: root}
	o.RuntimeIdentityID = "ri-" + strings.Repeat("a", 32)
	// This is only a file-transaction fixture; signature verification is a server/core responsibility.
	raw, _ := json.Marshal(map[string]any{"identity_id": o.RuntimeIdentityID, "instance_id": o.Instance.ID, "agent_id": "hri-" + strings.TrimPrefix(o.Instance.ID, "hi-"), "platform": Hermes})
	putTestFile(t, filepath.Join(o.StateDir, "runtime-identities", o.RuntimeIdentityID+".json"), raw, 0600)
	return o
}
func TestManagedPlanPinsPublicIdentityInputsWithoutReadingSecret(t *testing.T) {
	for _, change := range []string{"metadata", "revocation", "secret"} {
		t.Run(change, func(t *testing.T) {
			o := managedTestOptions(t)
			p := testPlan(t, o, "install") // No secret file exists: planning must not need its contents.
			for path := range p.payload.Inputs {
				if strings.Contains(path, "runtime-identity-secrets") {
					t.Fatal("secret captured in journal inputs")
				}
			}
			switch change {
			case "metadata":
				putTestFile(t, filepath.Join(o.StateDir, "runtime-identities", o.RuntimeIdentityID+".json"), []byte("changed metadata"), 0600)
			case "revocation":
				putTestFile(t, managedRevocationPath(o), []byte("revoked"), 0600)
			case "secret":
				putTestFile(t, managedCredentialPath(o), []byte("synthetic-secret-not-journaled"), 0600)
			}
			_, err := Apply(p)
			if change != "secret" {
				if !errors.Is(err, ErrPlanChanged) {
					t.Fatal("stale identity plan accepted", err)
				}
				if exists(filepath.Join(o.configRoot(), "plugins")) {
					t.Fatal("stale plan wrote host")
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			raw, _ := json.Marshal(p.payload)
			if strings.Contains(string(raw), "synthetic-secret-not-journaled") {
				t.Fatal("credential captured")
			}
		})
	}
}
func TestManagedConfigurationCannotBeSilentlyDowngraded(t *testing.T) {
	o := managedTestOptions(t)
	config := filepath.Join(o.configRoot(), "plugins", "siq-agent-security", "config.json")
	raw, _ := json.Marshal(map[string]any{"runtime_identity_id": o.RuntimeIdentityID})
	putTestFile(t, config, raw, 0600)
	o.RuntimeIdentityID = ""
	if _, err := Prepare(o, "install"); !errors.Is(err, ErrPlanChanged) {
		t.Fatal("unowned managed config downgraded", err)
	}
}
