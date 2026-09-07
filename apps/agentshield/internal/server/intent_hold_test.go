package server

import (
	"encoding/json"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/receipt"
)

func TestHoldHTTPRequiresManagementApprovalAcrossRecovery(t *testing.T) {
	for _, approve := range []bool{true, false} {
		name := "rejected"
		if approve {
			name = "approved"
		}
		t.Run(name, func(t *testing.T) {
			s, st := newServer(t, "block")
			// Deliberately bypass call(): its legacy convenience behavior
			// promotes the fixture token on management routes. This test must
			// send the exact bearer whose privileges it claims to exercise.
			post := func(path, bearer string, body any, want int) map[string]any {
				t.Helper()
				req := loopbackRequest("POST", path, body)
				if bearer != "" {
					req.Header.Set("Authorization", "Bearer "+bearer)
				}
				w := httptest.NewRecorder()
				s.Handler().ServeHTTP(w, req)
				if w.Code != want {
					t.Fatalf("%s: got HTTP %d, want %d: %s", path, w.Code, want, w.Body.String())
				}
				var result map[string]any
				if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
					t.Fatal(err)
				}
				return result
			}
			recoverEngine := func() {
				t.Helper()
				eng, err := receipt.New(receipt.Options{
					Pack: s.d.Pack, Chain: s.d.Chain, Grants: st.ActiveGrant,
					EnforcementMode: "block", IntentEnforcement: "optional",
					IntentLookup: receipt.ResolveStore(s.intents), HoldChannel: "openclaw_approval",
				})
				if err != nil {
					t.Fatal(err)
				}
				s.d.Engine = eng
			}
			recoverEngine()
			skill, err := filepath.Abs(filepath.Join("..", "admission", "testdata", "skills", "benign", "official-like"))
			if err != nil {
				t.Fatal(err)
			}
			admitted := post("/v1/admit", s.bootAdmin, map[string]any{"path": skill}, 200)
			granted := post("/v1/grants", s.bootAdmin, map[string]any{
				"admission_id": admitted["admission"].(map[string]any)["admission_id"],
				"platform":     "openclaw", "subject_id": "inst_1",
			}, 200)
			grantPath := "/v1/grants/" + granted["grant"].(map[string]any)["grant_id"].(string)
			patched := post(grantPath+"/patch-desired", s.bootAdmin, withRevision(map[string]any{
				"models": []string{"fixture-model"},
			}, stateRevision(t, granted)), 200)
			revision := stateRevision(t, patched)
			challenge := post(grantPath+"/challenge", s.bootAdmin, withRevision(nil, revision), 200)["challenge"].(map[string]any)
			approvedGrant := post(grantPath+"/approve", s.bootAdmin, withRevision(map[string]any{
				"actor_id": "fixture-admin", "challenge_id": challenge["challenge_id"], "nonce": challenge["nonce"],
			}, revision), 200)
			post(grantPath+"/deploy", s.bootAdmin, withRevision(nil, stateRevision(t, approvedGrant)), 200)

			// Unbound optional mode exercises exec holds. Bound intents reject
			// arbitrary shell effects before the grant approval gate.
			request := map[string]any{
				"platform": "openclaw", "session_id": "hold-session", "agent_id": "inst_1",
				"tool": "exec", "tool_call_id": "held-call", "params": map[string]any{"command": "printf fixture"},
			}
			decision := post("/v1/decide", token, request, 200)
			if decision["action"] != "hold" {
				t.Fatalf("edited grant lost per-use approval: %v", decision)
			}
			heldPath := "/v1/hold/" + decision["receipt_id"].(string)
			resolution := map[string]any{"approve": true, "actor_id": "spoofed-platform-operator"}
			post(heldPath, "", resolution, 401)
			post(heldPath, token, resolution, 403)
			request["action_id"] = decision["action_id"]
			request["decision_receipt_id"] = decision["receipt_id"]
			request["result"] = "synthetic result"
			request["context"] = map[string]any{"platform_approved": true, "approval_decision": "allow-once", "actor_id": "spoofed-platform-operator"}
			denied := post("/v1/observe", token, request, 400)
			if denied["reason_code"] != "observation_action_not_authorized" {
				t.Fatalf("wrong rejection for forged platform approval: %v", denied)
			}
			before, err := s.d.Chain.Read()
			if err != nil || len(before) != 1 {
				t.Fatalf("unauthorized requests changed receipt chain: %d %v", len(before), err)
			}
			resolution = map[string]any{"approve": approve, "actor_id": "fixture-admin"}
			resolved := post(heldPath, s.bootAdmin, resolution, 200)
			recoverEngine()
			replayed := post(heldPath, s.bootAdmin, resolution, 200)
			if replayed["receipt_id"] != resolved["receipt_id"] {
				t.Fatal("recovered approval retry created another resolution")
			}
			post(heldPath, s.bootAdmin, map[string]any{"approve": !approve, "actor_id": "fixture-admin"}, 409)
			wantRecords := 2
			if approve {
				observation := post("/v1/observe", token, request, 200)
				retry := post("/v1/observe", token, request, 200)
				if observation["receipt_id"] != retry["receipt_id"] || observation["action_id"] != decision["action_id"] {
					t.Fatal("approved observation lost identity or idempotency")
				}
				request["result"] = "conflicting synthetic result"
				post("/v1/observe", token, request, 409)
				wantRecords++
			} else {
				post("/v1/observe", token, request, 400)
			}
			all, err := s.d.Chain.Read()
			if err != nil || len(all) != wantRecords {
				t.Fatalf("unexpected receipt count: %d %v", len(all), err)
			}
			if err := receipt.Verify(all, s.d.Key.Public()); err != nil {
				t.Fatal(err)
			}
		})
	}
}
