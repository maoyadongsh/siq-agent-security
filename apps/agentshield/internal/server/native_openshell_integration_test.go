package server

// Explicitly opted-in integration harness. Uses actual signed stores and the
// actual HTTP server; the external owning runner supplies the real kernel
// verifier and OpenShell process. Never part of the shipped daemon.

import (
	"bytes"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
	"siq-agent-security/apps/agentshield/internal/skillimport"
	"siq-agent-security/apps/agentshield/internal/skillinstall"
	"siq-agent-security/apps/agentshield/internal/state"
)

func TestOwnedOpenShellNativeOnlineIntegration(t *testing.T) {
	dir := os.Getenv("SIQ_NATIVE_OPENSHELL_TEST_DIR")
	if dir == "" {
		t.Skip("explicit owned OpenShell integration runner required")
	}
	if !filepath.IsAbs(dir) || filepath.Clean(dir) != dir {
		t.Fatal("integration directory must be absolute")
	}
	info, err := os.Lstat(dir)
	if err != nil || !info.IsDir() || info.Mode().Perm() != 0700 {
		t.Fatal("integration directory must be private")
	}
	var input struct {
		Artifact    string `json:"artifact"`
		Source      string `json:"source"`
		RuntimeRoot string `json:"runtime_root"`
		Session     string `json:"session"`
	}
	raw, err := os.ReadFile(filepath.Join(dir, "input.json"))
	if err != nil || len(raw) > 65536 || json.Unmarshal(raw, &input) != nil || len(input.Artifact) != 64 {
		t.Fatal("invalid integration input")
	}
	write := func(name string, value any) {
		t.Helper()
		raw, err := json.MarshalIndent(value, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		file, err := os.OpenFile(filepath.Join(dir, name), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = file.Write(raw); err != nil {
			file.Close()
			t.Fatal(err)
		}
		if err = file.Close(); err != nil {
			t.Fatal(err)
		}
	}
	s, st := grantBindingServer(t, "block")
	rows := instanceFixture(t, s)
	instance := rows[1].(map[string]any)["instance_id"].(string)
	agent, err := runtimeidentity.AgentID(instance)
	if err != nil {
		t.Fatal(err)
	}
	facts := []admission.DeclaredFact{}
	for _, tool := range []string{"skill_view", "read_file", "write_file"} {
		facts = append(facts, admission.DeclaredFact{Domain: "tool", Action: "tool.invoke", Resource: admission.Resource{Type: "tool", Value: tool}, Effect: "allow", State: "declared", Authority: "skill_manifest"})
	}
	facts = append(facts, admission.DeclaredFact{Domain: "filesystem", Action: "fs.write", Resource: admission.Resource{Type: "path", Value: "/sandbox/native-business"}, Effect: "allow", State: "declared", Authority: "skill_manifest"})
	base, err := grant.Build(admission.Admission{AdmissionID: "adm-owned-native-baseline", ContentHash: strings.Repeat("c", 64), Verdict: "admit", DeclaredFacts: facts}, grant.Options{Key: s.d.Key, Platform: "hermes", Subject: grant.Subject{Type: "agent_instance", ID: agent}})
	if err != nil {
		t.Fatal(err)
	}
	baseline, err := grant.Approve(base.Grant, grant.Approval{ActorType: "human", ActorID: "owned-integration-operator", ApprovedAt: time.Now().UTC().Format(time.RFC3339Nano)}, s.d.Key)
	if err != nil {
		t.Fatal(err)
	}
	baseline, err = grant.MarkDeployed(baseline, s.d.Key)
	if err != nil {
		t.Fatal(err)
	}
	revision, err := st.PutGrantCAS(baseline, -1)
	if err != nil {
		t.Fatal(err)
	}
	var mounts []nativeMount
	grantIDs := map[string]string{"baseline": baseline.GrantID}
	for index, name := range []string{"reader", "writer"} {
		id := "si-" + strings.Repeat(string(rune('a'+index)), 32)
		if _, _, _, err = s.skillImports.Create(nil, skillimport.CreateRequest{SchemaVersion: "local-skill-import-create/v1", ImportID: id, SourceKind: "local_dir", Path: filepath.Join(input.Source, name), ActorID: "owned-integration-operator"}); err != nil {
			t.Fatal(err)
		}
		_, derived, err := s.skillImports.PermissionAdmission(nil, id)
		if err != nil {
			t.Fatal(err)
		}
		if err = st.PutImportAdmission(derived); err != nil {
			t.Fatal(err)
		}
		built, err := grant.BuildImported(derived.Admission, grant.Options{Key: s.d.Key, Platform: "hermes", Subject: grant.Subject{Type: "agent_instance", ID: agent}}, "owned-integration-operator", "ip-"+strings.Repeat(string(rune('a'+index)), 32))
		if err != nil {
			t.Fatal(err)
		}
		fs := &grant.FilesystemPatch{ReadOnly: []string{"/sandbox/native-business"}}
		if name == "writer" {
			fs = &grant.FilesystemPatch{ReadWrite: []string{"/sandbox/native-business"}}
		}
		patched, policy, err := grant.PatchDesired(built.Grant, grant.DesiredPatch{HasTools: true, Tools: []string{"skill_view", "read_file", "write_file"}, HasFilesystem: true, Filesystem: fs}, s.d.Key)
		if err != nil {
			t.Fatal(err)
		}
		approved, err := grant.Approve(patched, grant.Approval{ActorType: "human", ActorID: "owned-integration-operator", ApprovedAt: time.Now().UTC().Format(time.RFC3339Nano)}, s.d.Key)
		if err != nil {
			t.Fatal(err)
		}
		rev, err := st.CommitGrant(state.GrantCommit{Grant: approved, ExpectedRevision: -1, DesiredPolicy: policy, Audit: &state.AuditEvent{Event: "owned_integration_approval", Target: approved.GrantID}})
		if err != nil {
			t.Fatal(err)
		}
		plan, _, err := s.skillInstallations.Stage(nil, skillinstall.Request{SchemaVersion: "local-skill-install-stage-create/v1", RequestID: "is-" + strings.Repeat(string(rune('a'+index)), 32), GrantID: approved.GrantID, ExpectedRevision: rev, InstanceID: instance, DirectoryName: name, ActorID: "owned-integration-operator"})
		if err != nil {
			t.Fatal(err)
		}
		op, err := s.skillInstallations.Apply(nil, skillinstall.ApplyRequest{SchemaVersion: "local-skill-install-apply/v1", PlanID: plan.PlanID, PlanSignature: plan.Signature, ActorID: "owned-integration-operator", ConfirmInstall: true})
		if err != nil {
			t.Fatal(err)
		}
		if _, err = s.skillInstallations.Activate(nil, op.InstallID, skillinstall.ActivateRequest{SchemaVersion: "local-skill-install-activate/v1", OperationSignature: op.Signature, ExpectedRevision: rev, ActorID: "owned-integration-operator", ConfirmInstanceScope: true}); err != nil {
			t.Fatal(err)
		}
		mounts = append(mounts, nativeMount{InstanceID: instance, InstallID: op.InstallID, ClaimSignature: op.ClaimSignature, HostRoot: filepath.Join(s.d.Home, ".hermes", "profiles", "work", "skills", name), RuntimeRoot: input.RuntimeRoot + "/" + name})
		grantIDs[name] = approved.GrantID
	}
	connection, err := os.ReadFile(filepath.Join(dir, "connection.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err = os.Mkdir(filepath.Join(st.Dir, "native-host"), 0700); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(filepath.Join(st.Dir, "native-host", "connection.json"), connection, 0600); err != nil {
		t.Fatal(err)
	}
	native, err := OpenNativeRuntime(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	engine, err := receipt.New(receipt.Options{Pack: s.d.Pack, Chain: s.d.Chain, Grants: st.ActiveGrant, BaselineGrants: st.BaselineGrant, EnforcementMode: "block", Version: "owned-openshell-integration", HoldChannel: "openclaw_approval", IntentLookup: receipt.ResolveStore(s.intents), NativeCalls: native.Lookup})
	if err != nil {
		t.Fatal(err)
	}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	deps := s.d
	deps.Engine, deps.NativeRuntime = engine, native
	deps.ListenPort = listener.Addr().(*net.TCPAddr).Port
	next, err := New(deps)
	if err != nil {
		t.Fatal(err)
	}
	httpServer := &http.Server{Handler: next.Handler(), ReadHeaderTimeout: 5 * time.Second}
	go func() { _ = httpServer.Serve(listener) }()
	defer httpServer.Close()
	// Exercise the real management/session HTTP boundaries; do not issue the
	// native identity or enroll its session by calling internal stores directly.
	transport := &http.Transport{Proxy: nil}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: 5 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	post := func(path, credential string, body any, status int) map[string]any {
		t.Helper()
		data, err := json.Marshal(body)
		if err != nil {
			t.Fatal("owned HTTP request encoding failed")
		}
		request, err := http.NewRequest(http.MethodPost, "http://"+listener.Addr().String()+path, bytes.NewReader(data))
		if err != nil {
			t.Fatal("owned HTTP request creation failed")
		}
		request.Header.Set("Content-Type", "application/json")
		if credential != "" {
			request.Header.Set("Authorization", "Bearer "+credential)
		}
		response, err := client.Do(request)
		if err != nil {
			t.Fatal("owned HTTP request failed")
		}
		defer response.Body.Close()
		raw, err := io.ReadAll(io.LimitReader(response.Body, 65537))
		var value map[string]any
		if err != nil || response.StatusCode != status || len(raw) > 65536 || json.Unmarshal(raw, &value) != nil {
			t.Fatal("owned HTTP response invalid", path, response.StatusCode)
		}
		return value
	}
	paired := post("/v1/pair", "", map[string]any{"code": testPairingCode}, 200)
	issued := post("/v1/runtime-identities", paired["session"].(string), runtimeidentity.CreateRequest{
		SchemaVersion: "local-runtime-identity-create/v3", InstanceID: instance, GrantID: baseline.GrantID,
		ExpectedGrantRevision: revision, ActorID: "owned-integration-operator", SessionTTLSeconds: 300,
		NativeSkillPolicy: &runtimeidentity.NativeSkillPolicy{Mode: "required", RuntimeArtifactSHA256: input.Artifact}}, 201)
	if issued["schema_version"] != "local-runtime-identity-issued/v3" || issued["identity"].(map[string]any)["runtime_state"] != "unverified" {
		t.Fatal("native issuance overstated runtime status")
	}
	credentialPath := issued["credential_path"].(string)
	credential, err := os.ReadFile(credentialPath)
	if err != nil {
		t.Fatal(err)
	}
	enrolled := post("/v1/runtime-sessions", string(credential), map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": input.Session}, 200)
	if enrolled["schema_version"] != "local-runtime-session-enrolled/v3" || enrolled["runtime_state"] != "unverified" {
		t.Fatal("native enrollment overstated runtime status")
	}
	write("ready.json", map[string]any{"endpoint": "http://" + listener.Addr().String(), "credential_path": credentialPath, "state_dir": st.Dir, "subject": map[string]string{"platform": "hermes", "instance_id": instance, "agent_id": agent, "session_id": input.Session}, "installs": mounts})
	// Private, fixture-only operator controls. Nothing is mounted into the
	// sandbox, and no route or production approval path is added.
	controls := map[string]bool{}
	deadline := time.Now().Add(150 * time.Second)
	for {
		for _, name := range []string{"context", "writer", "baseline"} {
			if controls[name] {
				continue
			}
			if _, err := os.Stat(filepath.Join(dir, "revoke-"+name)); err != nil {
				if !os.IsNotExist(err) {
					t.Fatal(err)
				}
				continue
			}
			if name == "context" {
				chain, err := s.d.Chain.Read()
				if err != nil {
					t.Fatal(err)
				}
				found := false
				for _, r := range chain {
					if r.ToolCallID == nil || *r.ToolCallID != "context-before-revoke" || r.Action != receipt.ActionAllow || r.NativeInvocation == nil || len(r.NativeInvocation.Contexts) != 1 {
						continue
					}
					ref := r.NativeInvocation.Contexts[0]
					if _, err := native.host.Contexts().Revoke(ref.ContextID, ref.ContextSignature); err != nil {
						t.Fatal(err)
					}
					found = true
				}
				if !found {
					t.Fatal("live allowed context was not found for revocation")
				}
			} else {
				current, rev, err := st.GetGrantWithSeq(grantIDs[name])
				if err != nil {
					t.Fatal(err)
				}
				revoked, err := grant.Revoke(*current, s.d.Key)
				if err != nil {
					t.Fatal(err)
				}
				if _, err := st.CommitGrant(state.GrantCommit{Grant: revoked, ExpectedRevision: rev, Audit: &state.AuditEvent{Event: "owned_integration_revocation", Target: revoked.GrantID}}); err != nil {
					t.Fatal(err)
				}
				readback, err := st.GetGrant(revoked.GrantID)
				if err != nil || readback.Status != "revoked" || !grant.Verify(s.d.Key.Public(), *readback) {
					t.Fatal("signed revocation readback failed", err)
				}
			}
			controls[name] = true
			write("revoked-"+name+".json", map[string]any{"revoked": true})
		}
		if _, err := os.Stat(filepath.Join(dir, "finish")); err == nil {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("owned integration runner did not finish")
		}
		time.Sleep(50 * time.Millisecond)
	}
	chain, err := s.d.Chain.Read()
	if err != nil || len(chain) == 0 || receipt.Verify(chain, s.d.Key.Public()) != nil {
		t.Fatal("actual signed receipt chain missing or invalid", err)
	}
	write("authority-result.json", map[string]any{"signed_chain_verified": true, "receipt_count": len(chain), "receipts": chain, "revocations": controls, "management_http_issuance": true, "session_http_enrollment": true})
}
