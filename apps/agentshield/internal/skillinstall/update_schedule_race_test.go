package skillinstall

import (
	"bytes"
	"context"
	"os"
	"siq-agent-security/apps/agentshield/internal/skillimport"
	"testing"
	"time"
)

func TestLateUpdateOutcomeCannotOverwriteUserReconfiguration(t *testing.T) {
	for _, automatic := range []bool{false, true} {
		for _, enable := range []bool{false, true} {
			t.Run(map[bool]string{false: "manual", true: "scheduled"}[automatic]+map[bool]string{false: "-disable", true: "-resave"}[enable], func(t *testing.T) {
				f, op, clock := schedulerFixture(t)
				s := f.store
				*clock = clock.Add(25 * time.Hour)
				snapshot := snapInstall(t, s, op.InstallID)
				var saved []byte
				s.upstream = func(ctx context.Context, r *skillimport.Record, url string) (*skillimport.UpstreamSnapshot, error) {
					var err error
					if enable {
						_, err = s.SaveUpdateSource(ctx, op.InstallID, saveRequest("", true))
					} else {
						_, err = s.DisableUpdateSource(ctx, op.InstallID, disableRequest())
					}
					if err != nil {
						t.Fatal(err)
					}
					saved, err = os.ReadFile(s.updateSourcePath(op.InstallID))
					if err != nil {
						t.Fatal(err)
					}
					return snapshot(ctx, r, url)
				}
				if automatic {
					result, err := s.RunScheduledChecks(context.Background(), runRequest("scheduler"))
					if err != nil || result.Stale != 1 || len(result.Checked) != 0 {
						t.Fatalf("late outcome accepted: %+v %v", result, err)
					}
				} else {
					if _, err := s.CheckUpdate(context.Background(), op.InstallID, UpdateCheckRequest{SchemaVersion: "local-skill-update-check/v1", ActorID: "reviewer"}); err == nil {
						t.Fatal("late manual outcome accepted")
					}
				}
				got, err := os.ReadFile(s.updateSourcePath(op.InstallID))
				if err != nil || len(saved) == 0 || !bytes.Equal(got, saved) {
					t.Fatal("late outcome rewrote user choice", err)
				}
			})
		}
	}
}
