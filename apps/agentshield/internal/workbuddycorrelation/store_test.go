package workbuddycorrelation

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/adapters"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
	"siq-agent-security/apps/agentshield/internal/state"
)

func fixture(t *testing.T) (adapters.WorkBuddyManagedConfig, receipt.Request) {
	t.Helper()
	dir := filepath.Join(t.TempDir(), "state")
	if _, err := state.Open(dir); err != nil {
		t.Fatal(err)
	}
	cfg := adapters.WorkBuddyManagedConfig{StateDir: dir, RuntimeIdentityID: "ri-" + strings.Repeat("a", 32), InstanceID: "hi-" + strings.Repeat("b", 32), AgentID: "hri-" + strings.Repeat("b", 32)}
	session, _ := runtimeidentity.WorkBuddySessionID("session")
	call, _ := runtimeidentity.WorkBuddyCallID("session", "call")
	return cfg, receipt.Request{Platform: "workbuddy", AgentID: cfg.AgentID, SessionID: session, Tool: "Read", ToolCallID: call, Params: map[string]any{"file_path": "C:\\synthetic\\input.txt", "secret": "must-not-be-persisted"}}
}

func TestWorkBuddyCorrelationExclusiveClaimAndCrash(t *testing.T) {
	cfg, req := fixture(t)
	tx, err := Lock(cfg, req)
	if err != nil {
		t.Fatal(err)
	}
	if other, err := Lock(cfg, req); err == nil {
		other.Close()
		t.Fatal("concurrent effect lock accepted")
	}
	otherRequest := req
	otherRequest.Params = map[string]any{"file_path": "C:\\different-effect.txt"}
	if other, err := Lock(cfg, otherRequest); err == nil {
		other.Close()
		t.Fatal("different effects bypassed scope capacity lock")
	}
	if err := tx.Write("pre", tx.Base); err != nil {
		t.Fatal(err)
	}
	tx.Close()
	restarted, err := Lock(cfg, req)
	if err != nil {
		t.Fatal(err)
	}
	defer restarted.Close()
	if _, err := restarted.PriorHold(); err == nil {
		t.Fatal("duplicate raw call accepted after fresh process")
	}
	if err := restarted.Write("pre", restarted.Base); err == nil {
		t.Fatal("pre claim overwritten")
	}
	restarted.Close()
	req.ToolCallID, _ = runtimeidentity.WorkBuddyCallID("session", "next-call")
	next, err := Lock(cfg, req)
	if err != nil {
		t.Fatal(err)
	}
	defer next.Close()
	if _, err := next.PriorHold(); !errors.Is(err, ErrUncertain) {
		t.Fatalf("missing response became fresh decision: %v", err)
	}
}

func TestWorkBuddyCorrelationOrphanPreIsUncertain(t *testing.T) {
	for _, outcome := range []string{"missing-decision", "allow", "hold"} {
		t.Run(outcome, func(t *testing.T) {
			cfg, req := fixture(t)
			tx, err := Lock(cfg, req)
			if err != nil {
				t.Fatal(err)
			}
			if err = tx.Write("pre", tx.Base); err != nil {
				t.Fatal(err)
			}
			if outcome != "missing-decision" {
				d := tx.Decision(outcome, &receipt.Decision{Receipt: receipt.Receipt{ReceiptID: "receipt", ActionID: "action"}})
				if err = tx.Write("decision", d); err != nil {
					t.Fatal(err)
				}
			}
			if err = os.Remove(filepath.Join(tx.dir, tx.name("pre", req.ToolCallID))); err != nil {
				t.Fatal(err)
			}
			tx.Close()
			req.ToolCallID, _ = runtimeidentity.WorkBuddyCallID("session", "new-call")
			next, err := Lock(cfg, req)
			if err != nil {
				t.Fatal(err)
			}
			defer next.Close()
			if _, err = next.PriorHold(); !errors.Is(err, ErrUncertain) {
				t.Fatalf("orphan history treated as fresh: %v", err)
			}
		})
	}
}

func TestWorkBuddyCorrelationStrictPrivateHints(t *testing.T) {
	cfg, req := fixture(t)
	tx, err := Lock(cfg, req)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Close()
	if err := tx.Write("pre", tx.Base); err != nil {
		t.Fatal(err)
	}
	d := tx.Decision("hold", &receipt.Decision{Receipt: receipt.Receipt{ReceiptID: "receipt-hold", ActionID: "action-hold"}, Hold: &receipt.Hold{TimeoutMS: 60000}})
	if err := tx.Write("decision", d); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(tx.dir, tx.name("decision", req.ToolCallID))
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), "must-not-be-persisted") || strings.Contains(string(raw), "input.txt") {
		t.Fatal("private hint stored raw parameters")
	}
	if _, err = tx.Read("decision", req.ToolCallID); err != nil {
		t.Fatal(err)
	}
	for name, bad := range map[string]string{
		"duplicate":         strings.Replace(string(raw), `"action_id":`, `"action_id":"forged","action_id":`, 1),
		"escaped duplicate": strings.Replace(string(raw), `"action_id":`, `"action_\u0069d":"forged","action_id":`, 1),
		"alias":             strings.Replace(string(raw), `"action_id"`, `"Action_ID"`, 1),
		"unknown":           strings.TrimSuffix(string(raw), "}") + `,"allow":true}`,
		"trailing":          string(raw) + `{}`,
		"null":              strings.Replace(string(raw), `"action_id":"action-hold"`, `"action_id":null`, 1),
		"number":            strings.Replace(string(raw), `"action_id":"action-hold"`, `"action_id":42`, 1),
		"version":           strings.Replace(string(raw), "correlation/v1", "correlation/v99", 1),
		"different call":    strings.Replace(string(raw), req.ToolCallID, "workbuddy-call/v1:"+strings.Repeat("e", 64), 1),
		"large":             strings.Repeat(" ", Limit) + string(raw),
	} {
		t.Run(name, func(t *testing.T) {
			if err := os.WriteFile(path, []byte(bad), 0600); err != nil {
				t.Fatal(err)
			}
			if _, err := tx.Read("decision", req.ToolCallID); err == nil {
				t.Fatal("bad private hint accepted")
			}
		})
	}
}

func TestWorkBuddyCorrelationChangedParametersCannotReuseCall(t *testing.T) {
	cfg, req := fixture(t)
	tx, err := Lock(cfg, req)
	if err != nil {
		t.Fatal(err)
	}
	if err = tx.Write("pre", tx.Base); err != nil {
		t.Fatal(err)
	}
	tx.Close()
	req.Params = map[string]any{"file_path": "C:\\synthetic\\different.txt"}
	next, err := Lock(cfg, req)
	if err != nil {
		t.Fatal(err)
	}
	defer next.Close()
	if err = next.Write("pre", next.Base); err == nil {
		t.Fatal("same native call reauthorized different params")
	}
	if _, err = next.Read("pre", req.ToolCallID); err == nil {
		t.Fatal("changed post accepted old pre")
	}
}

func TestWorkBuddyCorrelationCapacity(t *testing.T) {
	cfg, req := fixture(t)
	tx, err := Lock(cfg, req)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Close()
	// These are deliberate synthetic junk entries in our private test root;
	// capacity is checked before any of them can be interpreted as a hint.
	for i := 0; i < MaxRecords; i++ {
		if err := os.WriteFile(filepath.Join(tx.dir, fmt.Sprintf("junk-%04d", i)), []byte("{}"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	if _, err = tx.entries(); err == nil {
		t.Fatal("unbounded directory accepted")
	}
	if err = tx.Write("pre", tx.Base); err == nil {
		t.Fatal("capacity exhaustion fell through to HTTP")
	}
}

func TestWorkBuddyCorrelationSchemaExample(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "..", "..", "packages", "contracts", "fixtures", "workbuddy_hook_correlation_v1_example.json"))
	if err != nil {
		t.Fatal(err)
	}
	var record Record
	if err := adapters.DecodeWorkBuddyObject(raw, required, allowed, &record); err != nil {
		t.Fatal(err)
	}
	if err := validate(raw, record, record); err != nil {
		t.Fatal(err)
	}
}
