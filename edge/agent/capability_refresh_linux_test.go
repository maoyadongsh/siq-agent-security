//go:build linux

package main

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"siq-agent-security/edge/agent/installplan"
	"siq-agent-security/edge/agent/protocol"
)

func TestServiceCapabilityTrustBeforeExecution(t *testing.T) {
	for _, name := range []string{"valid_expired_consent", "digest", "environment", "origin", "directory", "missing_manifest", "signature", "production_signature"} {
		t.Run(name, func(t *testing.T) {
			s, _ := consentFixture(t)
			p, err := installplan.Parse(s.DiscoveryPlan)
			if err != nil {
				t.Fatal(err)
			}
			p.TargetArch = runtime.GOARCH
			s.DiscoveryPlan, _ = json.Marshal(p)
			s.DiscoveryPlanSHA256, _ = compactPlanDigest(s.DiscoveryPlan)
			stage := t.TempDir()
			bin := filepath.Join(stage, "bin", runtime.GOARCH)
			if err := os.WriteFile(filepath.Join(stage, "release.json"), []byte(`{"unsigned":true}`), 0400); err != nil {
				t.Fatal(err)
			}
			switch name {
			case "digest":
				s.DiscoveryPlanSHA256 = "bad"
			case "environment":
				s.EnvironmentID = "other"
			case "origin":
				s.ControlPlaneURL = "https://other.test"
			case "directory":
				bin = stage
			case "missing_manifest":
				bin = filepath.Join(t.TempDir(), "bin", runtime.GOARCH)
			}
			verified, probed := 0, 0
			verify := func(plan installplan.Plan, raw []byte, root string) error {
				verified++
				if root != stage || plan.EnvironmentID != s.EnvironmentID {
					t.Error("wrong verification context")
				}
				if name == "signature" {
					return errors.New("invalid signature")
				}
				return nil
			}
			if name == "production_signature" {
				verify = installplan.VerifyStagedBundle
			}
			caps, err := measureServiceCapabilitiesAt(context.Background(), s, bin, verify, func(_ context.Context, path string, c installplan.Connector) (*protocol.ConnectorCapabilities, *protocol.ValidationResult, error) {
				probed++
				if verified != 1 {
					t.Fatal("execution before verification")
				}
				result := describedFixture()
				result.Version = c.Version
				return result, &protocol.ValidationResult{Valid: true}, nil
			})
			if name == "valid_expired_consent" {
				if err != nil || caps == nil || probed == 0 {
					t.Fatalf("valid persisted consent: %v", err)
				}
			} else if err == nil || caps != nil || probed != 0 {
				t.Fatalf("unsafe execution in %s", name)
			}
		})
	}
}
