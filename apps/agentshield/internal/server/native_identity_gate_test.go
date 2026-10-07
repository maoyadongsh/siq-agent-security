package server

import (
	"os"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
)

func TestNativeIdentityCannotExecuteBeforeTrustedHostWiring(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		t.Run(mode, func(t *testing.T) {
			s, st := grantBindingServer(t, mode)
			rows := instanceFixture(t, s)
			id := rows[1].(map[string]any)["instance_id"].(string)
			agent, _ := runtimeidentity.AgentID(id)
			g, rev := selectedGrantFixture(t, s, st, "c", "/work/public", false, agent)
			req := runtimeidentity.CreateRequest{SchemaVersion: "local-runtime-identity-create/v3", InstanceID: id, GrantID: g.GrantID, ExpectedGrantRevision: rev, ActorID: "fixture-human", SessionTTLSeconds: 300, NativeSkillPolicy: &runtimeidentity.NativeSkillPolicy{Mode: "required", RuntimeArtifactSHA256: strings.Repeat("c", 64)}}
			if code, _ := call(t, s, "POST", "/v1/runtime-identities", token, req); code != 400 {
				t.Fatal("new enrollment HTTP prematurely exposed", code)
			}
			// Store issuance alone cannot enable native execution over HTTP.
			r, err := s.runtimeIdentities.Create(req)
			if err != nil {
				t.Fatal(err)
			}
			path, _ := s.runtimeIdentities.CredentialPath(r.IdentityID)
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			credential := string(raw)
			if _, err := s.runtimeIdentities.Enroll(credential, "native-session"); err != nil {
				t.Fatal(err)
			}
			body := map[string]any{"platform": "hermes", "agent_id": agent, "session_id": "native-session", "tool": "read_file", "tool_call_id": "native-call", "params": map[string]any{"path": "/work/public/report"}}
			for _, claim := range []bool{true, false} {
				body["native_skill_required"] = claim
				code, out := scopedCall(t, s, "/v1/decide", credential, body)
				if code != 503 || out["error"] != "native_skill_runtime_unavailable" {
					t.Fatal("mandatory identity fell back", code, out)
				}
			}
			all, err := s.d.Chain.Read()
			if err != nil || len(all) != 0 {
				t.Fatal("unwired native identity produced decision", err)
			}
		})
	}
}
