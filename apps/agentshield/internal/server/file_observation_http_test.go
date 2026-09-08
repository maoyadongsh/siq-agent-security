package server

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/completion"
	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/provenance"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

func TestFileObservationHTTPReadsRealState(t *testing.T) {
	for _, mode := range []string{"block", "warn"} {
		t.Run(mode, func(t *testing.T) {
			s, st := newServer(t, mode)
			eng, err := receipt.New(receipt.Options{Pack: s.d.Pack, Chain: s.d.Chain, Grants: st.ActiveGrant, EnforcementMode: mode, IntentLookup: receipt.ResolveStore(s.intents), ProvenanceCheck: s.provenance.MatchParameters})
			if err != nil {
				t.Fatal(err)
			}
			s.d.Engine = eng
			path := filepath.Join(t.TempDir(), "report")
			data := []byte("fixture actual write")
			sum := sha256.Sum256(data)
			contract := apiIntent()
			contract.SchemaVersion = "intent/v3"
			// Explicit optional provenance isolates effect verification in this fixture.
			constraints := []provenance.Constraint{{ParameterPath: "/path", AllowedSourceTypes: []string{"USER"}, MinimumTrust: "trusted", Required: false}}
			contract.ProvenanceConstraints = &constraints
			refs := runtimeaction.ResourceRefs([]runtimeaction.Resource{{Domain: "filesystem", Value: path}})
			ref, _ := effectevidence.ResourceReference(refs[0])
			requirements := []completion.Requirement{{RequirementID: "write-report", EffectType: "file.write", ResourceRef: ref, ExpectedDigest: hex.EncodeToString(sum[:]), MinimumIndependence: "host_independent", MinimumCoverage: "partial"}}
			contract.EffectRequirements = &requirements
			contract.AllowedTools = []string{"write_file"}
			contract.AllowedEffects = []string{"file.write"}
			contract.ResourceConstraints[0].Value = filepath.Dir(path) + "/"
			effectCall(t, s, "POST", "/v1/intents", s.bootAdmin, contract, 201)
			pending := effectCall(t, s, "GET", "/v1/tasks/task-1/completion", s.bootAdmin, nil, 200)
			if pending["status"] != "incomplete" {
				t.Fatal(pending)
			}
			effectCall(t, s, "POST", "/v1/intent-bindings", s.bootAdmin, map[string]any{"platform": "hermes", "session_id": "s1", "agent_id": "a-1", "intent_id": "int-api"}, 201)
			d, err := eng.Decide(receipt.Request{Platform: "hermes", SessionID: "s1", AgentID: "a-1", Tool: "write_file", ToolCallID: "file-call", Params: map[string]any{"path": path}})
			if err != nil {
				t.Fatal(err)
			}
			if (mode == "block" && d.Action != "deny") || (mode == "warn" && d.Action != "allow") {
				t.Fatal(d.Action)
			}
			observer := effectCall(t, s, "POST", "/v1/effect-observers", s.bootAdmin, map[string]any{"source": effectevidence.Source{Type: "host_observer", SourceID: "server-file", Independence: "host_independent"}, "scope": provenance.Scope{Platform: "hermes", SessionID: "s1", AgentID: "a-1", TaskID: "task-1"}, "expires_in": 60}, 201)["token"].(string)
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
			persisted, err := s.effects.GetPendingFile("file-http-real")
			if err != nil || persisted.Before.Exists || persisted.OwnerDigest != tokenDigest(observer) {
				t.Fatal("begin did not persist original snapshot", persisted, err)
			}
			// Discard only the cache after the file changed. A retry must reuse the signed pre-write snapshot.
			s.observerMu.Lock()
			delete(s.fileObservations, "file-http-real")
			s.observerMu.Unlock()
			other := effectCall(t, s, "POST", "/v1/effect-observers", s.bootAdmin, map[string]any{"source": effectevidence.Source{Type: "host_observer", SourceID: "server-file", Independence: "host_independent"}, "scope": provenance.Scope{Platform: "hermes", SessionID: "s1", AgentID: "a-1", TaskID: "task-1"}, "expires_in": 60}, 201)["token"].(string)
			effectCall(t, s, "POST", "/v1/file-observations", other, body, 409)
			recovered := effectCall(t, s, "POST", "/v1/file-observations", observer, body, 200)
			if recovered["before"].(map[string]any)["exists"] != false {
				t.Fatal("retry resampled after tool execution", recovered)
			}

			recoveryBody := map[string]any{"observation_id": "file-http-real", "observer_id": "observer-" + tokenDigest(other)[:32], "expected_owner": tokenDigest(observer)}
			effectCall(t, s, "POST", "/v1/file-observation-recoveries", token, recoveryBody, 403)
			effectCall(t, s, "POST", "/v1/file-observation-recoveries", other, recoveryBody, 401)

			for _, mismatch := range []string{"source", "platform", "session", "agent", "task", "expired", "revoked"} {
				source := persisted.Source
				scope := persisted.Scope
				switch mismatch {
				case "source":
					source.SourceID = "other-host"
				case "platform":
					scope.Platform = "other-platform"
				case "session":
					scope.SessionID = "other-session"
				case "agent":
					scope.AgentID = "other-agent"
				case "task":
					scope.TaskID = "other-task"
				}
				bad := effectCall(t, s, "POST", "/v1/effect-observers", s.bootAdmin, map[string]any{"source": source, "scope": scope, "expires_in": 60}, 201)
				if mismatch == "expired" {
					s.observerMu.Lock()
					hash := tokenDigest(bad["token"].(string))
					entry := s.observers[hash]
					entry.Expires = time.Now().Add(-time.Second)
					s.observers[hash] = entry
					s.observerMu.Unlock()
				}
				if mismatch == "revoked" {
					effectCall(t, s, "DELETE", "/v1/effect-observers/"+bad["observer_id"].(string), s.bootAdmin, nil, 204)
				}
				effectCall(t, s, "POST", "/v1/file-observation-recoveries", s.bootAdmin, map[string]any{"observation_id": "file-http-real", "observer_id": bad["observer_id"], "expected_owner": persisted.OwnerDigest}, 403)
				current, err := s.effects.PendingFileOwner("file-http-real", time.Now())
				if err != nil || current != persisted.OwnerDigest {
					t.Fatal("rejected recovery changed owner", mismatch, err)
				}
			}
			takeover := effectCall(t, s, "POST", "/v1/file-observation-recoveries", s.bootAdmin, recoveryBody, 200)
			repeated := effectCall(t, s, "POST", "/v1/file-observation-recoveries", s.bootAdmin, recoveryBody, 200)
			if takeover["recovery"].(map[string]any)["signature"] != repeated["recovery"].(map[string]any)["signature"] || takeover["expires_at"] != persisted.ExpiresAt {
				t.Fatal("recovery not idempotent or extended deadline")
			}
			effectCall(t, s, "POST", "/v1/file-observations", observer, body, 409)
			effectCall(t, s, "POST", "/v1/file-observations", other, body, 200)
			effectCall(t, s, "POST", "/v1/file-observations/file-http-real/finish", observer, map[string]any{"path": path}, 403)
			originalObserver := observer
			observer = other
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
			complete := effectCall(t, s, "GET", "/v1/tasks/task-1/completion", s.bootAdmin, nil, 200)
			wantStatus := "verified"
			if mode == "block" {
				wantStatus = "conflicting"
			}
			if complete["status"] != wantStatus {
				t.Fatal(complete)
			}
			if err = os.Remove(path); err != nil {
				t.Fatal(err)
			}
			// Crash window: evidence published but cache completion not updated.
			s.observerMu.Lock()
			cached := s.fileObservations["file-http-real"]
			cached.Completed = false
			s.fileObservations["file-http-real"] = cached
			s.observerMu.Unlock()
			retry := effectCall(t, s, "POST", "/v1/file-observations/file-http-real/finish", observer, map[string]any{"path": path}, 200)
			if retry["signature"] != record["signature"] {
				t.Fatal("completion retry resampled/rewrote evidence")
			}
			effectCall(t, s, "POST", "/v1/file-observation-recoveries", s.bootAdmin, recoveryBody, 409)
			effectCall(t, s, "DELETE", "/v1/effect-observers/observer-"+tokenDigest(originalObserver)[:32], s.bootAdmin, nil, 204)
			effectCall(t, s, "POST", "/v1/file-observations/file-http-real/finish", observer, map[string]any{"path": path}, 409)
			body["observation_id"] = "file-http-fake"
			effectCall(t, s, "POST", "/v1/file-observations", observer, body, 201)
			fake := effectCall(t, s, "POST", "/v1/file-observations/file-http-fake/finish", observer, map[string]any{"path": path}, 201)
			later := effectCall(t, s, "GET", "/v1/tasks/task-1/completion", s.bootAdmin, nil, 200)
			if mode == "warn" && (later["status"] != "conflicting" || later["reason_code"] != "effect_evidence_conflicting") {
				t.Fatal("contradictory observations of the same action were not retained", later)
			}
			if fake["evidence"].(map[string]any)["execution_state"] != "failed" {
				t.Fatal("missing file treated as success", fake)
			}
		})
	}
}

func TestToolSuccessConflictsWithIndependentMissingOutputHTTP(t *testing.T) {
	s, st := newServer(t, "warn")
	eng, err := receipt.New(receipt.Options{Pack: s.d.Pack, Chain: s.d.Chain, Grants: st.ActiveGrant, EnforcementMode: "warn", IntentLookup: receipt.ResolveStore(s.intents), ProvenanceCheck: s.provenance.MatchParameters})
	if err != nil {
		t.Fatal(err)
	}
	s.d.Engine = eng
	path := filepath.Join(t.TempDir(), "missing-output")
	sum := sha256.Sum256([]byte("expected output"))
	expected := hex.EncodeToString(sum[:])
	ref, err := effectevidence.ResourceReference(runtimeaction.ResourceRefs([]runtimeaction.Resource{{Domain: "filesystem", Value: path}})[0])
	if err != nil {
		t.Fatal(err)
	}
	c := apiIntent()
	c.SchemaVersion = "intent/v3"
	c.AllowedTools, c.AllowedEffects = []string{"write_file"}, []string{"file.write"}
	c.ResourceConstraints[0].Value = filepath.Dir(path) + "/"
	constraints := []provenance.Constraint{{ParameterPath: "/path", AllowedSourceTypes: []string{"USER"}, MinimumTrust: "trusted", Required: false}}
	c.ProvenanceConstraints = &constraints
	requirements := []completion.Requirement{{RequirementID: "output", EffectType: "file.write", ResourceRef: ref, ExpectedDigest: expected, MinimumIndependence: "host_independent", MinimumCoverage: "partial"}}
	c.EffectRequirements = &requirements
	effectCall(t, s, "POST", "/v1/intents", s.bootAdmin, c, 201)
	effectCall(t, s, "POST", "/v1/intent-bindings", s.bootAdmin, map[string]any{"platform": "hermes", "session_id": "s1", "agent_id": "a-1", "intent_id": "int-api"}, 201)
	d := effectCall(t, s, "POST", "/v1/decide", token, map[string]any{"platform": "hermes", "session_id": "s1", "agent_id": "a-1", "tool": "write_file", "tool_call_id": "missing-call", "params": map[string]any{"path": path}}, 200)
	if d["action"] != "allow" {
		t.Fatal(d)
	}
	issueObserver := func(source effectevidence.Source) string {
		return effectCall(t, s, "POST", "/v1/effect-observers", s.bootAdmin, map[string]any{"source": source, "scope": provenance.Scope{Platform: "hermes", SessionID: "s1", AgentID: "a-1", TaskID: "task-1"}, "expires_in": 60}, 201)["token"].(string)
	}
	toolSource := effectevidence.Source{Type: "tool_report", SourceID: "fixture-tool", Independence: "self_reported"}
	claim := effectevidence.Evidence{SchemaVersion: "effect-evidence/v1", EvidenceID: "tool-success", ActionID: d["action_id"].(string), DecisionReceiptID: d["receipt_id"].(string), EffectType: "file.write", ResourceRef: ref, ExecutionState: "completed", Source: toolSource, Coverage: "unknown", Result: "unknown", EvidenceDigest: expected, ObservedAt: time.Now().UTC().Format(time.RFC3339Nano), SigningSchema: "local_canonical/v1"}
	effectCall(t, s, "POST", "/v1/tool-effect-reports", s.bootAdmin, claim, 401)
	bad := claim
	bad.Source = effectevidence.Source{Type: "host_observer", SourceID: "forged", Independence: "host_independent"}
	effectCall(t, s, "POST", "/v1/tool-effect-reports", token, bad, 400)
	bad = claim
	bad.DecisionReceiptID = "other-receipt"
	effectCall(t, s, "POST", "/v1/tool-effect-reports", token, bad, 400)
	bad = claim
	bad.EffectType = "file.read"
	effectCall(t, s, "POST", "/v1/tool-effect-reports", token, bad, 400)
	bad = claim
	bad.ResourceRef = "filesystem:sha256:" + expected
	effectCall(t, s, "POST", "/v1/tool-effect-reports", token, bad, 400)
	first := effectCall(t, s, "POST", "/v1/tool-effect-reports", token, claim, 201)
	repeated := effectCall(t, s, "POST", "/v1/tool-effect-reports", token, claim, 201)
	if first["signature"] != repeated["signature"] {
		t.Fatal("tool report replay changed signed record")
	}
	bad = claim
	bad.ExecutionState = "failed"
	effectCall(t, s, "POST", "/v1/tool-effect-reports", token, bad, 409)
	check := func(want string) {
		out := effectCall(t, s, "GET", "/v1/tasks/task-1/completion", s.bootAdmin, nil, 200)
		if out["status"] != want {
			t.Fatal(out, want)
		}
	}
	check("unknown")
	host := issueObserver(effectevidence.Source{Type: "host_observer", SourceID: "fixture-host", Independence: "host_independent"})
	effectCall(t, s, "POST", "/v1/tool-effect-reports", host, claim, 401)
	effectCall(t, s, "POST", "/v1/file-observations", host, map[string]any{"observation_id": "missing", "action_id": d["action_id"], "decision_receipt_id": d["receipt_id"], "path": path, "expected_digest": expected, "max_bytes": 1024}, 201)
	// The controlled tool claims success but creates no output; the host samples reality.
	effectCall(t, s, "POST", "/v1/file-observations/missing/finish", host, map[string]any{"path": path}, 201)
	check("conflicting")
}
