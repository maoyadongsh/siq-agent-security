package server

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/runtimecheck"
)

func TestRuntimeCheckActivityExactBindingBeyondReceiptPage(t *testing.T) {
	s, _ := newServer(t, "block")
	agent := "self-check-agent"
	for i := 0; i < 503; i++ {
		rc := receipt.Receipt{ReceiptID: fmt.Sprintf("fixture-%d", i), Platform: "hermes", AgentID: &agent,
			SessionID: "native-session", TaskID: "actual-task-not-derived-from-check-id", IntentID: "intent", IntentDigest: "digest", IntentBinding: "bound", Action: "allow"}
		if i < 501 {
			rc.TaskID = "unrelated-task"
		}
		if err := s.d.Chain.Append(&rc); err != nil {
			t.Fatal(err)
		}
	}
	all, projection, err := s.d.Engine.TaskActivitySnapshot()
	if err != nil {
		t.Fatal(err)
	}
	result := runtimecheck.Result{ID: "rc-" + strings.Repeat("a", 32), InstanceID: runtimeInstance, ReceiptIDs: []string{"fixture-501", "fixture-502"}}
	out, err := resolveRuntimeCheckActivity(result, all, projection)
	if err != nil || out.Activity.First != 501 || out.Activity.Count != 2 || out.Activity.Binding["task_id"] != "actual-task-not-derived-from-check-id" {
		t.Fatalf("wrong exact activity: %+v %v", out, err)
	}
	page := projectActivityPage(all, projection, "tasks", 0, 50)
	if out.Snapshot != page.Snapshot || out.Activity.ID != page.Items[1].ID {
		t.Fatal("reference does not match existing detail identity")
	}
	effectCall(t, s, "GET", "/v1/task-activities/"+out.Activity.ID+"?snapshot="+out.Snapshot, s.bootAdmin, nil, 200)
	if os.Getenv("SIQ_UPDATE_ACTIVITY_FIXTURES") == "1" {
		raw, _ := json.MarshalIndent(out, "", "  ")
		if err := os.WriteFile(filepath.Join("..", "..", "testdata", "contracts", "local-runtime-check-activity.json"), append(raw, '\n'), 0600); err != nil {
			t.Fatal(err)
		}
	}
	for name, ids := range map[string][]string{
		"empty": {}, "missing": {"fixture-missing"}, "partial": {"fixture-501", "fixture-missing"},
		"duplicate": {"fixture-501", "fixture-501"}, "other_task": {"fixture-500", "fixture-501"},
	} {
		t.Run(name, func(t *testing.T) {
			changed := result
			changed.ReceiptIDs = ids
			if _, err := resolveRuntimeCheckActivity(changed, all, projection); err == nil {
				t.Fatal("ambiguous or incomplete binding accepted")
			}
		})
	}
	for _, history := range []string{"invalid_prefix", "failed_history"} {
		changed := projection
		if history == "invalid_prefix" {
			changed.Verification.PrefixValid = false
		} else {
			changed.Verification.HistoryIntegrity = "failed"
		}
		if _, err := resolveRuntimeCheckActivity(result, all, changed); err == nil {
			t.Fatal("invalid integrity accepted")
		}
	}
}

func TestRuntimeCheckActivityRejectsAmbiguousReceipts(t *testing.T) {
	for _, scenario := range []string{"agent", "session", "intent", "digest", "platform", "unbound", "duplicate_receipt"} {
		t.Run(scenario, func(t *testing.T) {
			s, _ := newServer(t, "block")
			agent, other := "agent", "other"
			first := receipt.Receipt{ReceiptID: "a", Platform: "hermes", AgentID: &agent, SessionID: "session", TaskID: "same-task", IntentID: "intent", IntentDigest: "digest", IntentBinding: "bound", Action: "allow"}
			second := first
			second.ReceiptID = "b"
			switch scenario {
			case "agent":
				second.AgentID = &other
			case "session":
				second.SessionID = other
			case "intent":
				second.IntentID = other
			case "digest":
				second.IntentDigest = other
			case "platform":
				first.Platform, second.Platform = "openclaw", "openclaw"
			case "unbound":
				second.IntentBinding = "unbound"
			case "duplicate_receipt":
				second.ReceiptID = "a"
			}
			for _, rc := range []*receipt.Receipt{&first, &second} {
				if err := s.d.Chain.Append(rc); err != nil {
					t.Fatal(err)
				}
			}
			all, p, err := s.d.Engine.TaskActivitySnapshot()
			if err != nil {
				t.Fatal(err)
			}
			ids := []string{"a", "b"}
			if scenario == "duplicate_receipt" {
				ids = []string{"a"}
			}
			if _, err := resolveRuntimeCheckActivity(runtimecheck.Result{ReceiptIDs: ids}, all, p); err == nil {
				t.Fatal("cross-boundary or ambiguous link accepted")
			}
		})
	}
}

func TestRuntimeCheckActivityHTTPReadOnly(t *testing.T) {
	s, _ := runtimeHTTPFixture(t)
	path := "/v1/runtime-checks/rc-" + strings.Repeat("a", 32) + "/activity"
	for _, credential := range []string{"", token, strings.Repeat("f", 64)} {
		w := sessionRequest(t, s, "GET", path, nil, credential, nil, nil)
		if w.Code != 401 && w.Code != 403 {
			t.Fatal("unprivileged lookup accepted", w.Code)
		}
	}
	effectCall(t, s, "GET", path, s.bootAdmin, nil, 404)
	effectCall(t, s, "POST", path, s.bootAdmin, nil, 405)
	effectCall(t, s, "GET", path+"?task_id=guessed", s.bootAdmin, nil, 400)
	grants, err := s.d.Store.ListGrants()
	if err != nil || len(grants) != 0 {
		t.Fatal("lookup created authority", err)
	}
}
