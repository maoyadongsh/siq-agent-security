//go:build linux

package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/edge/agent/installplan"
)

func TestVerifyEnterpriseReleaseNeverAcceptsUnsignedOrKeyOverride(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SIQ_EDGE_STATE_DIR", filepath.Join(dir, "no-state"))
	path := filepath.Join(dir, "release.json")
	for _, raw := range []string{`{}`, `{"schema_version":"enterprise-release-candidate/v1","signed":false}`,
		`{"schema_version":"enterprise-release/v1","signature":"` + strings.Repeat("0", 128) + `"}`,
		strings.Repeat("x", installplan.MaxBytes+1)} {
		if err := os.WriteFile(path, []byte(raw), 0600); err != nil {
			t.Fatal(err)
		}
		var out bytes.Buffer
		if err := verifyEnterpriseRelease([]string{"--release", path}, &out); err == nil || out.Len() != 0 {
			t.Fatal("invalid release reported verified")
		}
	}
	for _, args := range [][]string{{}, {"--release", path, "--pubkey", "fixture"}, {"--release", path, "extra"}} {
		if verifyEnterpriseRelease(args, &bytes.Buffer{}) == nil {
			t.Fatal("invalid flags accepted")
		}
	}
	link := filepath.Join(dir, "linked.json")
	if err := os.Symlink(path, link); err != nil {
		t.Fatal(err)
	}
	if verifyEnterpriseRelease([]string{"--release", link}, &bytes.Buffer{}) == nil {
		t.Fatal("linked envelope accepted")
	}
	if _, err := os.Stat(filepath.Join(dir, "no-state")); !os.IsNotExist(err) {
		t.Fatal("verification created device state")
	}
}
