//go:build linux

package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"siq-agent-security/edge/agent/installplan"
)

func TestSetupReviewIsReadOnlyAndShowsActualScope(t *testing.T) {
	for _, scenario := range []string{"valid", "start", "mismatch", "expired"} {
		t.Run(scenario, func(t *testing.T) {
			root := t.TempDir()
			state := filepath.Join(root, "state")
			t.Setenv("SIQ_EDGE_STATE_DIR", state)
			if os.Mkdir(state, 0700) != nil || os.WriteFile(filepath.Join(state, "state.json"), []byte("synthetic-local-state-not-for-preview"), 0600) != nil {
				t.Fatal("private fixture")
			}
			raw, err := os.ReadFile("installplan/testdata/plan.json")
			if err != nil {
				t.Fatal(err)
			}
			p, err := installplan.Parse(raw)
			if err != nil {
				t.Fatal(err)
			}
			p.TargetArch = runtime.GOARCH
			p.IssuedAt = time.Now().Add(-time.Minute).UTC().Format("2006-01-02T15:04:05Z")
			p.ExpiresAt = time.Now().Add(10 * time.Minute).UTC().Format("2006-01-02T15:04:05Z")
			if scenario == "expired" {
				p.IssuedAt = time.Now().Add(-20 * time.Minute).UTC().Format("2006-01-02T15:04:05Z")
				p.ExpiresAt = time.Now().Add(-10 * time.Minute).UTC().Format("2006-01-02T15:04:05Z")
			}
			raw, err = json.Marshal(p)
			if err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(root, "plan.json")
			if os.WriteFile(path, raw, 0600) != nil {
				t.Fatal("fixture")
			}
			tenant := p.TenantID
			if scenario == "mismatch" {
				tenant = "other"
			}
			args := []string{"--review-only", "--plan", path, "--tenant", tenant, "--environment", p.EnvironmentID, "--control-plane", p.ControlPlaneOrigin}
			if scenario == "start" {
				args = append(args, "--start")
			}
			var out bytes.Buffer
			err = setupEnterprise(context.Background(), args, &out)
			if scenario == "expired" || scenario == "mismatch" {
				if err != errEnterpriseSetup || out.Len() != 0 {
					t.Fatal("invalid review accepted")
				}
			} else {
				if err != nil {
					t.Fatal("valid review failed")
				}
				var review struct {
					Status   string           `json:"status"`
					Digest   string           `json:"confirmation_sha256"`
					Start    bool             `json:"start_service"`
					Verified bool             `json:"release_signature_verified"`
					Confirm  bool             `json:"requires_explicit_confirmation"`
					Business bool             `json:"business_permissions_granted"`
					Plan     installplan.Plan `json:"plan"`
				}
				if json.Unmarshal(out.Bytes(), &review) != nil {
					t.Fatal("invalid review JSON")
				}
				h := sha256.Sum256(raw)
				if review.Status != "review_only" || review.Digest != hex.EncodeToString(h[:]) || review.Start != (scenario == "start") || review.Verified || review.Business || !review.Confirm {
					t.Fatal("incorrect review boundaries")
				}
				if review.Plan.Connectors[0].Scope.Roots[0] != p.Connectors[0].Scope.Roots[0] || !strings.Contains(out.String(), "SOUL.md") {
					t.Fatal("scope omitted")
				}
			}
			files, err := os.ReadDir(root)
			if err != nil || len(files) != 2 {
				t.Fatal("review wrote state or staging")
			}
			private, err := os.ReadFile(filepath.Join(state, "state.json"))
			if err != nil || string(private) != "synthetic-local-state-not-for-preview" || strings.Contains(out.String(), string(private)) {
				t.Fatal("review changed or exposed private state")
			}
		})
	}
}
