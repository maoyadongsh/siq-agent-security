package receipt

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"sync"
	"testing"
)

func TestTrustedTaskBoundarySurvivesLateResultsAndRestart(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "openclaw", false), true)
	request := req("openclaw", "read_file", map[string]any{"path": "/work/report", "note": "alice@example.com"})
	var old *Decision
	for i := 0; i < 3; i++ {
		var err error
		request.ToolCallID = fmt.Sprint(i)
		old, err = fx.eng.Decide(request)
		if err != nil || old.Action != ActionAllow {
			t.Fatal(old, err)
		}
	}
	oldRequest := correlatedRequest(request, old)
	held, err := fx.eng.Decide(req("openclaw", "exec", map[string]any{"command": "ls"}))
	if err != nil || held.Action != ActionHold {
		t.Fatal(held, err)
	}
	before := fx.eng.sessions[request.SessionID]
	taintCount := len(before.taints)
	if taintCount == 0 {
		t.Fatal("fixture must carry untrusted taint")
	}
	fx.eng.opts.IntentLookup = func(_, _, _ string) (*IntentContract, error) {
		return &IntentContract{IntentID: "int-task", TaskID: "task-1", Digest: "digest", AuthorityRevision: "r1", Principal: "u-1", AgentID: "inst_1", Purpose: "read", AllowedEffects: []string{"read_file"}, ValidUntil: "2099-01-01T00:00:00Z"}, nil
	}
	first, err := fx.eng.Decide(request)
	if err != nil || first.Action != ActionAllow || first.Receipt.TaskSeq != 1 || first.Receipt.ParentActionID != "" {
		t.Fatal(first, err)
	}
	if len(fx.eng.sessions[request.SessionID].taints) < taintCount {
		t.Fatal("binding erased taints")
	}
	if _, err = fx.eng.ResolveHold(held.Receipt, true, "admin"); err != nil {
		t.Fatal(err)
	}
	if _, err = fx.eng.Observe(oldRequest, "old result"); err != nil {
		t.Fatal(err)
	}
	if s := fx.eng.sessions[request.SessionID]; s.parentActionID != first.Receipt.ActionID || s.taskSeq != 1 {
		t.Fatal("late result changed task chain")
	}
	restarted, err := New(fx.eng.opts)
	if err != nil {
		t.Fatal(err)
	}
	next, err := restarted.Decide(request)
	if err != nil || next.Receipt.TaskSeq != 2 || next.Receipt.ParentActionID != first.Receipt.ActionID || next.Receipt.IntentID != "int-task" {
		t.Fatal(next, err)
	}
	if len(restarted.sessions[request.SessionID].taints) < taintCount {
		t.Fatal("recovery erased taints")
	}
}
func TestConcurrentDecisionsHaveOneOrderedTaskChain(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "hermes", false), false)
	fx.eng.opts.IntentLookup = func(_, _, _ string) (*IntentContract, error) {
		return &IntentContract{IntentID: "int-task", TaskID: "task-1", Digest: "digest", AuthorityRevision: "r1", Principal: "u-1", AgentID: "inst_1", Purpose: "read", AllowedEffects: []string{"read_file"}, ValidUntil: "2099-01-01T00:00:00Z"}, nil
	}
	const count = 32
	results := make(chan Receipt, count)
	var wg sync.WaitGroup
	for i := 0; i < count; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			r := req("hermes", "read_file", map[string]any{"path": "/home/u/proj/report"})
			r.ToolCallID = fmt.Sprint(i)
			d, err := fx.eng.Decide(r)
			if err != nil || d.Action != ActionAllow {
				t.Error(d, err)
				return
			}
			results <- d.Receipt
		}(i)
	}
	wg.Wait()
	close(results)
	receipts := []Receipt{}
	for r := range results {
		receipts = append(receipts, r)
	}
	if len(receipts) != count {
		t.Fatal(len(receipts))
	}
	sort.Slice(receipts, func(i, j int) bool { return receipts[i].TaskSeq < receipts[j].TaskSeq })
	ids := map[string]bool{}
	parent := ""
	for i, r := range receipts {
		if r.TaskSeq != i+1 || r.ParentActionID != parent || ids[r.ActionID] {
			t.Fatal("broken concurrent chain", r.TaskSeq)
		}
		ids[r.ActionID] = true
		parent = r.ActionID
	}
	all, err := fx.chain.Read()
	if err != nil {
		t.Fatal(err)
	}
	if err = Verify(all, fx.k.Public()); err != nil {
		t.Fatal(err)
	}
	restarted, err := New(fx.eng.opts)
	if err != nil {
		t.Fatal(err)
	}
	next, err := restarted.Decide(req("hermes", "read_file", nil))
	if err != nil || next.Receipt.TaskSeq != count+1 || next.Receipt.ParentActionID != parent {
		t.Fatal(next, err)
	}
}
func TestReceiptBeforeOptionalMetadataStillVerifies(t *testing.T) {
	raw, err := os.ReadFile("../../testdata/contracts/receipt.pre-resource-refs.sample.json")
	if err != nil {
		t.Fatal(err)
	}
	var r Receipt
	if err = json.Unmarshal(raw, &r); err != nil {
		t.Fatal(err)
	}
	if err = Verify([]Receipt{r}, key(t).Public()); err != nil {
		t.Fatal(err)
	}
}
