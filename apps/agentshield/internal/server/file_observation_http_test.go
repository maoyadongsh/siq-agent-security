package server

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/provenance"
	"siq-agent-security/apps/agentshield/internal/receipt"
)

func TestFileObservationHTTPReadsRealState(t *testing.T) {
	for _, mode := range []string{"block", "warn"} {
		t.Run(mode, func(t *testing.T) {
			s, st := newServer(t, mode)
			eng, err := receipt.New(receipt.Options{Pack: s.d.Pack, Chain: s.d.Chain, Grants: st.ActiveGrant, EnforcementMode: mode, IntentLookup: receipt.ResolveStore(s.intents)})
			if err != nil {
				t.Fatal(err)
			}
			s.d.Engine = eng
			path := filepath.Join(t.TempDir(), "report")
			contract := apiIntent()
			contract.AllowedTools = []string{"write_file"}
			contract.AllowedEffects = []string{"file.write"}
			contract.ResourceConstraints[0].Value = filepath.Dir(path) + "/"
			effectCall(t, s, "POST", "/v1/intents", s.bootAdmin, contract, 201)
			effectCall(t, s, "POST", "/v1/intent-bindings", s.bootAdmin, map[string]any{"platform": "hermes", "session_id": "s1", "agent_id": "a-1", "intent_id": "int-api"}, 201)
			d, err := eng.Decide(receipt.Request{Platform: "hermes", SessionID: "s1", AgentID: "a-1", Tool: "write_file", ToolCallID: "file-call", Params: map[string]any{"path": path}})
			if err != nil {
				t.Fatal(err)
			}
			if (mode == "block" && d.Action != "deny") || (mode == "warn" && d.Action != "allow") {
				t.Fatal(d.Action)
			}
			observer := effectCall(t, s, "POST", "/v1/effect-observers", s.bootAdmin, map[string]any{"source": effectevidence.Source{Type: "host_observer", SourceID: "server-file", Independence: "host_independent"}, "scope": provenance.Scope{Platform: "hermes", SessionID: "s1", AgentID: "a-1", TaskID: "task-1"}, "expires_in": 60}, 201)["token"].(string)
			data := []byte("fixture actual write")
			sum := sha256.Sum256(data)
			body := map[string]any{"observation_id": "file-http-real", "action_id": d.Receipt.ActionID, "decision_receipt_id": d.Receipt.ReceiptID, "path": path, "expected_digest": hex.EncodeToString(sum[:]), "max_bytes": 1024}
			effectCall(t, s, "POST", "/v1/file-observations", token, body, 403)
			body["path"] = path + "-other"
			effectCall(t, s, "POST", "/v1/file-observations", observer, body, 400)
			body["path"] = path
			body["before"] = map[string]any{"exists": false}
			effectCall(t, s, "POST", "/v1/file-observations", observer, body, 400)
			delete(body, "before")
			effectCall(t, s, "POST", "/v1/file-observations", observer, body, 201)
			effectCall(t, s, "POST", "/v1/file-observations", observer, body, 200)
			// This is a controlled fixture write, not execution of analyzed tool text.
			if err = os.WriteFile(path, data, 0600); err != nil {
				t.Fatal(err)
			}
			effectCall(t, s, "POST", "/v1/file-observations/file-http-real/finish", observer, map[string]any{"path": path + "-other"}, 400)
			record := effectCall(t, s, "POST", "/v1/file-observations/file-http-real/finish", observer, map[string]any{"path": path}, 201)
			material := record["file_observation"].(map[string]any)
			if material["before"].(map[string]any)["exists"] != false || material["after"].(map[string]any)["digest"] != hex.EncodeToString(sum[:]) {
				t.Fatal(material)
			}
			want := ""
			if mode == "block" {
				want = "unauthorized_effect_observed"
			}
			if record["finding_code"] != want {
				t.Fatal(record)
			}
			if err = os.Remove(path); err != nil {
				t.Fatal(err)
			}
			retry := effectCall(t, s, "POST", "/v1/file-observations/file-http-real/finish", observer, map[string]any{"path": path}, 200)
			if retry["signature"] != record["signature"] {
				t.Fatal("completion retry resampled/rewrote evidence")
			}
			body["observation_id"] = "file-http-fake"
			effectCall(t, s, "POST", "/v1/file-observations", observer, body, 201)
			fake := effectCall(t, s, "POST", "/v1/file-observations/file-http-fake/finish", observer, map[string]any{"path": path}, 201)
			if fake["evidence"].(map[string]any)["execution_state"] != "failed" {
				t.Fatal("missing file treated as success", fake)
			}
		})
	}
}
