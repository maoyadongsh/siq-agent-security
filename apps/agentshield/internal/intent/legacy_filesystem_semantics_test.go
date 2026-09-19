package intent

import (
	"bytes"
	"os"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/provenance"
)

// A valid historical regex must not gain Windows filesystem authority when a
// newer resource profile is introduced. Exercise persisted, verified contracts,
// not an unsigned hand-built matcher value.
func TestLegacyFilesystemRegexDoesNotGainWindowsAuthority(t *testing.T) {
	for _, version := range []string{"intent/v2", "intent/v3"} {
		t.Run(version, func(t *testing.T) {
			store := testStore(t)
			contract := testContract()
			contract.SchemaVersion = version
			contract.ResourceConstraints = []ResourceConstraint{{Domain: "filesystem", Operator: "regex", Value: ".*"}}
			if version == "intent/v3" {
				constraints := []provenance.Constraint{}
				contract.ProvenanceConstraints = &constraints
			}
			issued, err := store.Issue(contract)
			if err != nil {
				t.Fatalf("issue valid legacy regex: %v", err)
			}
			recordPath, err := store.path(issued.IntentID)
			if err != nil {
				t.Fatal(err)
			}
			before, err := os.ReadFile(recordPath)
			if err != nil {
				t.Fatal(err)
			}
			now := time.Date(2026, 9, 16, 0, 0, 0, 0, time.UTC)
			for _, tc := range []struct {
				name string
				path string
				deny bool
			}{
				{"posix", "/fixture/report.txt", false},
				{"posix_navigation", "/fixture/sub/../report.txt", false},
				// This is a POSIX path in old contracts, not Windows UNC.
				{"posix_double_slash", "//server/share/report.txt", false},
				{"windows_backslash", `C:\Fixture\report.txt`, true},
				{"windows_forward_slash", "C:/Fixture/report.txt", true},
				{"windows_lower_drive", "c:/Fixture/report.txt", true},
				{"windows_unc", `\\server\share\report.txt`, true},
				{"windows_extended", `\\?\C:\Fixture\report.txt`, true},
				{"windows_device", `\\.\PhysicalDrive0`, true},
			} {
				t.Run(tc.name, func(t *testing.T) {
					verified, err := store.Get(issued.IntentID)
					if err != nil {
						t.Fatalf("read and verify legacy signature: %v", err)
					}
					if verified.Digest != issued.Digest || verified.Signature != issued.Signature {
						t.Fatal("legacy signed identity changed")
					}
					err = verified.Authorize("hermes", "a-1", "u-1", "read_file", map[string]any{"path": tc.path}, now)
					if tc.deny {
						assertCode(t, err, "intent_resource_not_allowed")
					} else if err != nil {
						t.Fatalf("legacy POSIX authority narrowed: %v", err)
					}
				})
			}
			after, err := os.ReadFile(recordPath)
			if err != nil {
				t.Fatal(err)
			}
			if !bytes.Equal(before, after) {
				t.Fatal("authorization rewrote the immutable legacy contract")
			}
		})
	}
}
