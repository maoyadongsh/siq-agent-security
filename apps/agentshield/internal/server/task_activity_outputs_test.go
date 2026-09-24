package server

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/rawcontent"
	"siq-agent-security/apps/agentshield/internal/receipt"
)

func TestActivityOutputsActualCaptureAndExplicitRead(t *testing.T) {
	s, issued, credential, agent := managedIdentityFixture(t, "block")
	session := "output-session"
	if code, out := scopedCall(t, s, "/v1/runtime-sessions", credential, map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": session}); code != 200 {
		t.Fatal(code, out)
	}
	_, binding, err := s.runtimeIdentities.AuthorizeSessionContext(credential, "hermes", agent, session)
	if err != nil {
		t.Fatal(err)
	}
	rc := receipt.Receipt{ReceiptID: "output-fixture", Platform: "hermes", SessionID: session, AgentID: &agent, TaskID: binding.TaskID, IntentID: binding.IntentID, IntentDigest: binding.IntentDigest, AuthorityRevision: binding.AuthorityRevision, IntentBinding: "bound", Action: "allow"}
	if err := s.d.Chain.Append(&rc); err != nil {
		t.Fatal(err)
	}
	list := effectCall(t, s, "GET", "/v1/task-activities", s.bootAdmin, nil, 200)
	id := list["items"].([]any)[0].(map[string]any)["activity_id"].(string)
	query := "?view=tasks&snapshot=" + list["snapshot"].(string)
	base := "/v1/task-activities/" + id + "/outputs"
	for _, cred := range []string{"", token, credential} {
		w := sessionRequest(t, s, "GET", base+query, nil, cred, nil, nil)
		if w.Code != 401 && w.Code != 403 {
			t.Fatal("output metadata accepted non-admin", w.Code)
		}
	}
	disabled := effectCall(t, s, "GET", base+query, s.bootAdmin, nil, 200)
	if disabled["status"] != "disabled" {
		t.Fatal(disabled)
	}
	activateRawTaskContent(t, s)
	grant, err := s.rawAuthority.Issue(binding.TaskID, []string{"output"}, "operator", time.Hour, time.Hour, 4096, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	prepared, _ := rawcontent.Prepare("output", []rawcontent.Field{{Path: "/result", Value: "legacy output"}})
	legacy, err := s.rawAuthority.Capture(grant.GrantID, binding.TaskID, prepared, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	empty := effectCall(t, s, "GET", base+query, s.bootAdmin, nil, 200)
	if empty["status"] != "ready" || len(empty["items"].([]any)) != 0 {
		t.Fatal("legacy record attributed", empty)
	}
	w := sessionRequest(t, s, "POST", "/v1/raw-task-content/native-captures", map[string]any{"schema_version": "local-raw-task-content-native-capture/v1", "platform": "hermes", "agent_id": agent, "session_id": session, "kind": "output", "fields": []map[string]any{{"path": "/result", "value": "PRIVATE_OUTPUT <script>unsafe()</script>", "secret": false}}}, credential, nil, nil)
	if w.Code != 201 {
		t.Fatal(w.Code, w.Body.String())
	}
	response := effectCall(t, s, "GET", base+query, s.bootAdmin, nil, 200)
	encoded, _ := json.Marshal(response)
	if strings.Contains(string(encoded), "PRIVATE_OUTPUT") {
		t.Fatal("list exposed plaintext")
	}
	items := response["items"].([]any)
	if len(items) != 1 {
		t.Fatal(response)
	}
	item := items[0].(map[string]any)
	body := map[string]any{"schema_version": "local-task-output-read/v1", "record_id": item["record_id"], "expected_plaintext_sha256": item["plaintext_sha256"], "confirm_display": true}
	read := base + "/read" + query
	result := effectCall(t, s, "POST", read, s.bootAdmin, body, 200)
	if os.Getenv("SIQ_UPDATE_OUTPUT_FIXTURES") == "1" {
		for name, value := range map[string]any{"local-task-outputs": response, "local-task-output-read": body, "local-task-output-content": result} {
			raw, err := json.MarshalIndent(value, "", "  ")
			if err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join("../../testdata/contracts", name+".json"), append(raw, '\n'), 0644); err != nil {
				t.Fatal(err)
			}
		}
	}
	if result["activity_id"] != id || result["snapshot"] != list["snapshot"] {
		t.Fatal("content not activity-bound", result)
	}
	for _, change := range []map[string]any{{"confirm_display": false}, {"session_id": "borrowed"}, {"record_id": "../bad"}} {
		bad := map[string]any{}
		for k, v := range body {
			bad[k] = v
		}
		for k, v := range change {
			bad[k] = v
		}
		effectCall(t, s, "POST", read, s.bootAdmin, bad, 400)
	}
	bad := map[string]any{}
	for k, v := range body {
		bad[k] = v
	}
	bad["expected_plaintext_sha256"] = strings.Repeat("a", 64)
	effectCall(t, s, "POST", read, s.bootAdmin, bad, 409)
	bad["record_id"], bad["expected_plaintext_sha256"] = legacy.RecordID, legacy.PlaintextHash
	effectCall(t, s, "POST", read, s.bootAdmin, bad, 404)
	effectCall(t, s, "GET", base+"/read"+query, s.bootAdmin, nil, 405)
	effectCall(t, s, "GET", base, s.bootAdmin, nil, 400)
	effectCall(t, s, "GET", base+"?view=tasks&snapshot="+strings.Repeat("a", 64), s.bootAdmin, nil, 409)
	// A distinct native session can capture its own output but cannot lend it
	// to this activity, even under the same local runtime identity.
	otherSession := "other-output-session"
	if code, out := scopedCall(t, s, "/v1/runtime-sessions", credential, map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": otherSession}); code != 200 {
		t.Fatal(code, out)
	}
	_, other, err := s.runtimeIdentities.AuthorizeSessionContext(credential, "hermes", agent, otherSession)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.rawAuthority.Issue(other.TaskID, []string{"output"}, "operator", time.Hour, time.Hour, 4096, time.Now()); err != nil {
		t.Fatal(err)
	}
	w = sessionRequest(t, s, "POST", "/v1/raw-task-content/native-captures", map[string]any{"schema_version": "local-raw-task-content-native-capture/v1", "platform": "hermes", "agent_id": agent, "session_id": otherSession, "kind": "output", "fields": []map[string]any{{"path": "/result", "value": "OTHER_SESSION_OUTPUT", "secret": false}}}, credential, nil, nil)
	if w.Code != 201 {
		t.Fatal(w.Code, w.Body.String())
	}
	otherOutput := sessionBody(t, w)
	bad["record_id"], bad["expected_plaintext_sha256"] = otherOutput["record_id"], otherOutput["plaintext_sha256"]
	effectCall(t, s, "POST", read, s.bootAdmin, bad, 404)
	// Runtime revocation stops new capture, while retained historical content
	// remains explicitly readable by the paired local administrator.
	if _, err := s.runtimeIdentities.Revoke(issued["identity"].(map[string]any)["identity_id"].(string), "operator"); err != nil {
		t.Fatal(err)
	}
	effectCall(t, s, "POST", read, s.bootAdmin, body, 200)
	if _, _, err := s.runtimeIdentities.AuthorizeSessionContext(credential, "hermes", agent, session); err == nil {
		t.Fatal("historical lookup resurrected runtime authority")
	}
	if err := s.rawStore.Delete(binding.TaskID, item["record_id"].(string)); err != nil {
		t.Fatal(err)
	}
	effectCall(t, s, "POST", read, s.bootAdmin, body, http.StatusNotFound)
}
