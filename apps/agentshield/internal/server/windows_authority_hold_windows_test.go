package server

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/receipt"
)

func windowsHeldRequest(t *testing.T, f windowsAuthorityHTTPFixture) (map[string]any, map[string]any, map[string]any) {
	t.Helper()
	body := f.decision("write_file", "held-write", f.output)
	decision := windowsAuthorityHTTP(t, f.s, "POST", "/v1/decide", f.credential, body, 200)
	if decision["action"] != "hold" {
		t.Fatal("per-use approval not requested", decision)
	}
	if _, err := os.Stat(f.output); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("decision performed a file write", err)
	}
	status := f.decision("write_file", "held-write", f.output)
	status["action_id"], status["decision_receipt_id"] = decision["action_id"], decision["receipt_id"]
	reserve := map[string]any{"schema_version": "hold-execution-reserve/v1", "platform": "hermes", "agent_id": f.agent, "session_id": f.session, "task_id": f.taskID, "runtime_task_id": body["runtime_task_id"], "tool": "write_file", "original_tool_call_id": "held-write", "retry_tool_call_id": "held-write-retry", "action_id": decision["action_id"], "decision_receipt_id": decision["receipt_id"], "params": body["params"]}
	return decision, status, reserve
}

func TestWindowsAuthorityHoldReservesOnceAfterEngineRecovery(t *testing.T) {
	f := newWindowsAuthorityHTTPFixture(t, "block", true)
	decision, status, reserve := windowsHeldRequest(t, f)
	windowsAuthorityHTTP(t, f.s, "POST", "/v1/hold-executions/reserve", f.credential, reserve, 400)
	heldRoute := "/v1/hold/" + decision["receipt_id"].(string)
	resolution := map[string]any{"approve": true, "actor_id": "component-operator"}
	windowsAuthorityHTTP(t, f.s, "POST", heldRoute, f.credential, resolution, 401)
	windowsAuthorityHTTP(t, f.s, "POST", heldRoute, f.s.bootAdmin, resolution, 200)
	// Reload the engine from the persisted signed chain, with the same production
	// state-backed authority resolver. This is engine recovery, not an OS restart.
	intents, err := f.st.IntentAuthority(f.s.d.Key)
	if err != nil {
		t.Fatal(err)
	}
	chain, err := receipt.OpenChain(f.st.Dir, "local", f.s.d.Key)
	if err != nil {
		t.Fatal(err)
	}
	engine, err := receipt.New(receipt.Options{Pack: f.s.d.Pack, Chain: chain, Grants: f.st.ActiveGrant, BaselineGrants: f.st.BaselineGrant, ContextLookup: intents.GetContext, EnforcementMode: "block", IntentEnforcement: "required", IntentLookup: receipt.ResolveStore(intents), HoldChannel: "console", HoldTimeoutMS: 120000})
	if err != nil {
		t.Fatal(err)
	}
	f.s.d.Engine = engine
	current := windowsAuthorityHTTP(t, f.s, "POST", "/v1/hold-status", f.credential, status, 200)
	if current["status"] != "approved" {
		t.Fatal("recovery lost valid Windows approval", current)
	}
	for _, path := range []string{f.outside, f.output + " "} {
		wrong := map[string]any{}
		for k, v := range reserve {
			wrong[k] = v
		}
		wrong["params"] = map[string]any{"path": path}
		windowsAuthorityHTTP(t, f.s, "POST", "/v1/hold-executions/reserve", f.credential, wrong, 400)
	}
	reserved := windowsAuthorityHTTP(t, f.s, "POST", "/v1/hold-executions/reserve", f.credential, reserve, 201)
	windowsAuthorityHTTP(t, f.s, "POST", "/v1/hold-executions/reserve", f.credential, reserve, 409)
	query := map[string]any{"schema_version": "hold-execution-status-request/v1", "platform": "hermes", "agent_id": f.agent, "session_id": f.session, "task_id": f.taskID, "runtime_task_id": reserve["runtime_task_id"], "tool": "write_file", "retry_tool_call_id": "held-write-retry", "action_id": decision["action_id"], "decision_receipt_id": decision["receipt_id"], "reservation_receipt_id": reserved["reservation_receipt_id"], "params": reserve["params"]}
	uncertain := windowsAuthorityHTTP(t, f.s, "POST", "/v1/hold-executions/status", f.credential, query, 200)
	if uncertain["status"] != "uncertain" {
		t.Fatal("reservation mistaken for execution", uncertain)
	}
	records, err := chain.Read()
	if err != nil {
		t.Fatal(err)
	}
	count := 0
	for _, r := range records {
		if r.RecordType == "hold_reservation" {
			count++
		}
	}
	if count != 1 {
		t.Fatal("duplicate or missing execution reservation", count)
	}
	if err := receipt.Verify(records, f.s.d.Key.Public()); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(f.output); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("reservation fabricated execution", err)
	}
}

func TestWindowsAuthorityHoldRechecksDirectoryAndRevocation(t *testing.T) {
	for _, kind := range []string{"directory", "grant", "identity"} {
		t.Run(kind, func(t *testing.T) {
			f := newWindowsAuthorityHTTPFixture(t, "block", true)
			decision, status, reserve := windowsHeldRequest(t, f)
			windowsAuthorityHTTP(t, f.s, "POST", "/v1/hold/"+decision["receipt_id"].(string), f.s.bootAdmin, map[string]any{"approve": true, "actor_id": "component-operator"}, 200)
			want := 401
			switch kind {
			case "directory":
				if err := os.Rename(f.root, f.root+"-original"); err != nil {
					t.Fatal(err)
				}
				if err := os.Mkdir(f.root, 0700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join(f.root, filepath.Base(f.input)), []byte("replacement"), 0600); err != nil {
					t.Fatal(err)
				}
				result := windowsAuthorityHTTP(t, f.s, "POST", "/v1/hold-status", f.credential, status, 200)
				if result["status"] != "denied" || result["reason_code"] != "hold_authority_changed" {
					t.Fatal("replaced directory kept approval", result)
				}
				want = 400
			case "grant":
				windowsAuthorityHTTP(t, f.s, "POST", "/v1/grants/"+f.grantID+"/revoke", f.s.bootAdmin, map[string]any{"expected_revision": f.revision, "actor_id": "component-operator"}, 200)
			case "identity":
				windowsAuthorityHTTP(t, f.s, "POST", "/v1/runtime-identities/"+f.identityID+"/revoke", f.s.bootAdmin, map[string]any{"schema_version": "local-runtime-identity-revoke/v1", "actor_id": "component-operator"}, 200)
			}
			windowsAuthorityHTTP(t, f.s, "POST", "/v1/hold-executions/reserve", f.credential, reserve, want)
			records, err := f.s.d.Chain.Read()
			if err != nil {
				t.Fatal(err)
			}
			for _, r := range records {
				if r.RecordType == "hold_reservation" {
					t.Fatal("invalid authority consumed approval")
				}
			}
			if _, err := os.Stat(f.output); !errors.Is(err, os.ErrNotExist) {
				t.Fatal("denied resume wrote output", err)
			}
		})
	}
}
