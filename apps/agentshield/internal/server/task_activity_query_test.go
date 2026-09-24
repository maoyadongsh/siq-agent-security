package server

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/receipt"
)

func TestActivityQueryFiltersBeforePaginationAndCountsDecisions(t *testing.T) {
	s, _ := newServer(t, "block")
	agent := "agent"
	appendReceipt := func(id, task, kind, action, at string) {
		t.Helper()
		rc := receipt.Receipt{ReceiptID: id, Platform: "hermes", AgentID: &agent, SessionID: "session", TaskID: task,
			IntentID: "intent", IntentDigest: "digest", IntentBinding: "bound", RecordType: kind, Action: action, IssuedAt: at}
		if err := s.d.Chain.Append(&rc); err != nil {
			t.Fatal(err)
		}
	}
	for i := 0; i < 55; i++ {
		appendReceipt(fmt.Sprintf("r-%d", i), fmt.Sprintf("task-%02d", i), "decision", "allow", "2026-09-22T10:00:00Z")
	}
	appendReceipt("deny", "task-00", "decision", "deny", "2026-09-23T10:00:00+08:00")
	appendReceipt("observe", "task-00", "observation", "allow", "2026-09-23T02:00:00Z")
	appendReceipt("resolve", "task-00", "hold_resolution", "allow", "2026-09-23T02:00:00Z")
	appendReceipt("unknown-time", "unknown-time", "", "hold", "invalid")
	read := func(query string) activityQueryPage {
		t.Helper()
		data := effectCall(t, s, "GET", "/v1/task-activities/query"+query, s.bootAdmin, nil, 200)
		raw, _ := json.Marshal(data)
		var page activityQueryPage
		if err := json.Unmarshal(raw, &page); err != nil {
			t.Fatal(err)
		}
		return page
	}
	first := read("?limit=1&action=deny&from=2026-09-23T02:00:00Z&to=2026-09-23T02:00:01Z")
	if first.Total != 1 || len(first.Items) != 1 || first.Items[0].Binding["task_id"] != "task-00" || first.Items[0].Decisions["allow"] != 1 || first.Items[0].Decisions["deny"] != 1 || first.Items[0].Count != 4 {
		t.Fatalf("wrong decisions/filter: %+v", first)
	}
	if got := read("?to=2026-09-23T02:00:00Z").Total; got != 54 {
		t.Fatal("exclusive upper bound or unknown time included", got)
	}
	if got := read("?from=2026-09-23T02:00:00Z").Total; got != 1 {
		t.Fatal("inclusive lower bound or unknown time excluded", got)
	}
	all := read("")
	if all.Total != 56 || len(all.Items) != 50 || all.Items[0].Binding["task_id"] != "unknown-time" || all.Items[0].LastRecorded != nil || all.Items[1].Binding["task_id"] != "task-00" || all.Next == nil || *all.Next != 50 {
		t.Fatal("wrong recent ordering/pagination")
	}
	second := read("?offset=50&snapshot=" + all.Snapshot)
	if len(second.Items) != 6 || second.Next != nil || second.Items[5].Binding["task_id"] != "task-01" {
		t.Fatal("wrong second page")
	}
	effectCall(t, s, "GET", "/v1/task-activities/"+first.Items[0].ID+"?snapshot="+first.Snapshot, s.bootAdmin, nil, 200)
	if os.Getenv("SIQ_UPDATE_ACTIVITY_FIXTURES") == "1" {
		raw, _ := json.MarshalIndent(first, "", "  ")
		if err := os.WriteFile(filepath.Join("..", "..", "testdata", "contracts", "local-task-activity-query.json"), append(raw, '\n'), 0600); err != nil {
			t.Fatal(err)
		}
	}
	for _, q := range []string{"?from=bad", "?from=2026-09-23T00:00:00Z&to=2026-09-22T00:00:00Z", "?from=2026-09-23T00:00:00Z&to=2026-09-23T00:00:00Z", "?action=success", "?action=allow&action=deny", "?from=&from=", "?offset=1", "?unknown=1"} {
		effectCall(t, s, "GET", "/v1/task-activities/query"+q, s.bootAdmin, nil, 400)
	}
	effectCall(t, s, "GET", "/v1/task-activities/query", token, nil, 403)
	effectCall(t, s, "GET", "/v1/task-activities/query", "", nil, 401)
	effectCall(t, s, "POST", "/v1/task-activities/query", s.bootAdmin, nil, 405)
	appendReceipt("new", "new", "decision", "redact", "2026-09-23T04:00:00Z")
	effectCall(t, s, "GET", "/v1/task-activities/query?snapshot="+all.Snapshot, s.bootAdmin, nil, 409)
}

func TestActivityQueryUnassignedAndIntegrity(t *testing.T) {
	s, st := newServer(t, "block")
	rc := receipt.Receipt{ReceiptID: "unbound", Platform: "hermes", SessionID: "session", Action: "unexpected", IssuedAt: "2026-09-23T00:00:00Z"}
	if err := s.d.Chain.Append(&rc); err != nil {
		t.Fatal(err)
	}
	data := effectCall(t, s, "GET", "/v1/task-activities/query?view=unassigned", s.bootAdmin, nil, 200)
	raw, _ := json.Marshal(data)
	var page activityQueryPage
	if err := json.Unmarshal(raw, &page); err != nil {
		t.Fatal(err)
	}
	if len(page.Items) != 1 || page.Items[0].Binding != nil || page.Items[0].Attribution != "unknown" || page.Items[0].Decisions["other"] != 1 {
		t.Fatal("invented binding or lost unknown decision")
	}
	files, err := filepath.Glob(filepath.Join(st.Dir, "receipts", "local", "*.jsonl"))
	if err != nil || len(files) != 1 {
		t.Fatal("missing fixture")
	}
	content, _ := os.ReadFile(files[0])
	if err := os.WriteFile(files[0], []byte(strings.Replace(string(content), "unexpected", "tampered", 1)), 0600); err != nil {
		t.Fatal(err)
	}
	effectCall(t, s, "GET", "/v1/task-activities/query?action=deny", s.bootAdmin, nil, 500)
}
