package main

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

func TestCollectionReadErrorCategoriesDoNotExposePaths(t *testing.T) {
	for _, tc := range []struct {
		cause error
		want  string
	}{
		{os.ErrNotExist, "openclaw_config_missing"},
		{os.ErrPermission, "openclaw_config_permission_denied"},
		{errors.New("private fixture detail"), "openclaw_config_unavailable"},
	} {
		err := collectionReadError(&os.PathError{Op: "read", Path: "/private/fixture", Err: tc.cause})
		if err.Error() != tc.want {
			t.Fatalf("wrong category: %s", err)
		}
	}
}

func TestCollectionFailureNeverReturnsPartialOrEmptySuccess(t *testing.T) {
	for _, kind := range []string{"missing", "directory", "invalid", "wrong-type"} {
		t.Run(kind, func(t *testing.T) {
			valid, broken := t.TempDir(), t.TempDir()
			identityConfig(t, valid, []map[string]string{{"id": "observed-role"}}, false)
			path := filepath.Join(broken, "openclaw.json")
			want := "openclaw_config_unavailable"
			var err error
			switch kind {
			case "missing":
				want = "openclaw_config_missing"
			case "directory":
				err = os.Mkdir(path, 0700)
			case "invalid":
				err = os.WriteFile(path, []byte(`{"private-fixture":`), 0600)
				want = "openclaw_config_invalid"
			case "wrong-type":
				err = os.WriteFile(path, []byte(`{"agents":{"list":"private-fixture"}}`), 0600)
				want = "openclaw_config_invalid"
			}
			if err != nil {
				t.Fatal(err)
			}
			for _, roots := range [][]string{{broken}, {valid, broken}, {broken, valid}} {
				plan := protocol.ScanPlan{Scope: &protocol.Scope{Roots: roots}, Limits: defaultLimits()}
				batch, err := collectOp(plan)
				if err == nil || err.Error() != want || len(batch.Candidates) != 0 || len(batch.Evidence) != 0 || len(batch.PermissionFacts) != 0 {
					t.Fatalf("failure became inventory: error=%v batch=%+v", err, batch)
				}
				params, err := json.Marshal(collectParams{Plan: plan})
				if err != nil {
					t.Fatal(err)
				}
				response := dispatch(&protocol.Request{ID: "failure-fixture", Op: protocol.OpCollect, Params: params})
				if response.OK || response.Result != nil || response.Error == nil || response.Error.Message != want {
					t.Fatalf("failure lost in protocol: %+v", response)
				}
			}
		})
	}
}
