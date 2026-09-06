package ledger

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/state"
)

func TestRefreshRejectsMalformedLatestRecord(t *testing.T) {
	for _, kind := range []string{"assets", "findings"} {
		for _, raw := range []string{"{", "null", "{}"} {
			t.Run(kind+raw, func(t *testing.T) {
				st, err := state.Open(t.TempDir())
				if err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join(st.Dir, kind, "broken.0.json"), []byte(raw), 0o600); err != nil {
					t.Fatal(err)
				}
				snap := Snapshot{Records: []AssetRecord{{CandidateID: "retained"}}}
				if err := Refresh(st, nil, &snap, time.Now()); err == nil {
					t.Fatal("corrupt latest record hidden by a successful refresh")
				}
				if len(snap.Records) != 1 || snap.Records[0].CandidateID != "retained" {
					t.Fatal("failed refresh replaced the previous snapshot")
				}
			})
		}
	}
}
