package server

import (
	"bytes"
	"encoding/json"
	"fmt"
	"reflect"
	"testing"
	"time"

	exportpkg "siq-agent-security/apps/agentshield/internal/export"
	"siq-agent-security/apps/agentshield/internal/rawcontent"
	"siq-agent-security/apps/agentshield/internal/receipt"
)

// Component clock injection is deliberately separate from the real-wall-clock
// B04 leg. Both signed export forms must remain scoped after raw data deletion.
func TestTaskExportsAcrossRawRevocationDeletionAndExpiry(t *testing.T) {
	s, st := newServer(t, "block")
	activateRawTaskContent(t, s)
	now := time.Now()
	var firstGrant rawcontent.Grant
	var firstRecord rawcontent.Envelope
	expected := map[string][]string{}
	secret := "PRIVATE_EXPORT_LIFECYCLE_CANARY"
	for i := 0; i < 3; i++ {
		input := apiIntent()
		input.IntentID = fmt.Sprintf("int-export-%d", i)
		input.TaskID = fmt.Sprintf("task-export-%d", i)
		contract, err := s.intents.Issue(input)
		if err != nil {
			t.Fatal(err)
		}
		rc := receipt.Receipt{ReceiptID: fmt.Sprintf("receipt-%d", i), Platform: input.Agent.Platform,
			AgentID: &input.Agent.ID, SessionID: "same-session", TaskID: input.TaskID,
			IntentID: input.IntentID, IntentDigest: contract.Digest, IntentBinding: "bound", Action: "allow",
			Tool: secret, ParamsExcerpt: &secret}
		if err := s.d.Chain.Append(&rc); err != nil {
			t.Fatal(err)
		}
		expected[input.TaskID] = []string{rc.Hash}
		capturedAt := now
		if i == 2 {
			capturedAt = now.Add(-2 * time.Hour)
		}
		g, err := s.rawAuthority.Issue(input.TaskID, []string{"note"}, "fixture", 3*time.Hour, time.Hour, 4096, capturedAt)
		if err != nil {
			t.Fatal(err)
		}
		content, err := rawcontent.Prepare("note", []rawcontent.Field{{Path: "/fixture", Value: secret}})
		if err != nil {
			t.Fatal(err)
		}
		envelope, err := s.rawAuthority.Capture(g.GrantID, input.TaskID, content, capturedAt)
		if err != nil {
			t.Fatal(err)
		}
		if i == 0 {
			firstGrant, firstRecord = g, envelope
		}
	}
	page := effectCall(t, s, "GET", "/v1/task-activities", s.bootAdmin, nil, 200)
	snapshot := page["snapshot"].(string)
	verify := func(phase string) {
		t.Helper()
		for _, value := range page["items"].([]any) {
			item := value.(map[string]any)
			id := item["activity_id"].(string)
			task := item["binding"].(map[string]any)["task_id"].(string)
			for _, kind := range []string{"export", "trace-export"} {
				path := "/v1/task-activities/" + id + "/" + kind + "?snapshot=" + snapshot
				w := sessionRequest(t, s, "GET", path, nil, s.bootAdmin, nil, nil)
				if w.Code != 200 || bytes.Contains(w.Body.Bytes(), []byte(secret)) || bytes.Contains(w.Body.Bytes(), []byte("ciphertext_base64")) {
					t.Fatal(phase, kind, "unsafe export", w.Code)
				}
				var rows []exportpkg.ActivityExportRow
				if kind == "export" {
					var doc exportpkg.ActivityDocument
					if err := json.Unmarshal(w.Body.Bytes(), &doc); err != nil {
						t.Fatal(err)
					}
					if err := exportpkg.VerifyActivity(s.d.Key.Public(), doc); err != nil {
						t.Fatal(err)
					}
					rows = doc.Receipts
				} else {
					var doc exportpkg.TraceDocument
					if err := json.Unmarshal(w.Body.Bytes(), &doc); err != nil {
						t.Fatal(err)
					}
					if err := exportpkg.VerifyTrace(s.d.Key.Public(), doc); err != nil {
						t.Fatal(err)
					}
					rows = doc.Receipts
					if len(doc.Sources) != 1 || doc.Sources[0].ReceiptHash != expected[task][0] {
						t.Fatal("foreign trace source")
					}
				}
				got := []string{}
				for _, row := range rows {
					got = append(got, row.SourceHash)
				}
				if !reflect.DeepEqual(got, expected[task]) {
					t.Fatal(phase, kind, "cross-task receipt leakage")
				}
			}
		}
	}
	verify("before")
	if _, err := s.rawAuthority.Revoke(firstGrant.GrantID, firstGrant.Signature, "fixture", now); err != nil {
		t.Fatal(err)
	}
	if _, _, err := s.rawStore.Read("task-export-0", firstRecord.RecordID, now); err != nil {
		t.Fatal("capture revoke hid retained content", err)
	}
	verify("revoked")
	effectCall(t, s, "POST", "/v1/raw-task-content/records/"+firstRecord.RecordID+"/delete", s.bootAdmin,
		map[string]any{"schema_version": "local-raw-task-content-record-delete/v1", "task_id": "task-export-0", "confirm_record_id": firstRecord.RecordID}, 200)
	verify("deleted")
	before := up07Snapshot(t, st.Dir)
	result := effectCall(t, s, "POST", "/v1/raw-task-content/purge-expired", s.bootAdmin,
		map[string]any{"schema_version": "local-raw-task-content-purge-expired/v1", "confirm_expired_only": true}, 200)
	if result["deleted_records"] != float64(1) {
		t.Fatal("wrong expired purge scope")
	}
	after := up07Snapshot(t, st.Dir)
	for name, digest := range before {
		if len(name) >= len("raw-task-content/") && name[:len("raw-task-content/")] == "raw-task-content/" {
			continue
		}
		if after[name] != digest {
			t.Fatal("purge altered non-content history", name)
		}
	}
	verify("expired_purged")
}
