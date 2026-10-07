package server

// Explicitly opted-in integration harness. Uses actual signed stores and the
// actual HTTP server; the external owning runner supplies the real kernel
// verifier and OpenShell process. Never part of the shipped daemon.

import (
	"encoding/json"
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
	}
	record, err := s.runtimeIdentities.Create(runtimeidentity.CreateRequest{SchemaVersion: "local-runtime-identity-create/v3", InstanceID: instance, GrantID: baseline.GrantID, ExpectedGrantRevision: revision, ActorID: "owned-integration-operator", SessionTTLSeconds: 300, NativeSkillPolicy: &runtimeidentity.NativeSkillPolicy{Mode: "required", RuntimeArtifactSHA256: input.Artifact}})
	if err != nil {
		t.Fatal(err)
	}
	credentialPath, err := s.runtimeIdentities.CredentialPath(record.IdentityID)
	if err != nil {
		t.Fatal(err)
	}
	credential, err := os.ReadFile(credentialPath)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = s.runtimeIdentities.Enroll(string(credential), input.Session); err != nil {
		t.Fatal(err)
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
	write("ready.json", map[string]any{"endpoint": "http://" + listener.Addr().String(), "credential_path": credentialPath, "state_dir": st.Dir, "subject": map[string]string{"platform": "hermes", "instance_id": instance, "agent_id": agent, "session_id": input.Session}, "installs": mounts})
	deadline := time.Now().Add(150 * time.Second)
	for {
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
	write("authority-result.json", map[string]any{"signed_chain_verified": true, "receipt_count": len(chain), "receipts": chain})
}
