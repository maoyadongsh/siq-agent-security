package server

import (
	"bytes"
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
	"siq-agent-security/apps/agentshield/internal/skillcontext"
	"siq-agent-security/apps/agentshield/internal/trustedcontext"
)

type nativeOnlineFixture struct {
	server     *Server
	native     *NativeRuntime
	subject    skillcontext.Subject
	credential string
	publisher  string
	fault      atomic.Value
	checks     atomic.Int64
}

func nativeOnlineServer(t *testing.T, requireApproval ...bool) *nativeOnlineFixture {
	t.Helper()
	if runtime.GOOS != "linux" || os.Getuid() <= 0 {
		t.Skip("Linux non-root managed profile")
	}
	s, st := grantBindingServer(t, "block")
	rows := instanceFixture(t, s)
	instance := rows[1].(map[string]any)["instance_id"].(string)
	agent, _ := runtimeidentity.AgentID(instance)
	approval := len(requireApproval) > 0 && requireApproval[0]
	g, rev := selectedGrantFixture(t, s, st, "c", "/work/public", approval, agent)
	record, err := s.runtimeIdentities.Create(runtimeidentity.CreateRequest{SchemaVersion: "local-runtime-identity-create/v3", InstanceID: instance, GrantID: g.GrantID, ExpectedGrantRevision: rev, ActorID: "fixture", SessionTTLSeconds: 300, NativeSkillPolicy: &runtimeidentity.NativeSkillPolicy{Mode: "required", RuntimeArtifactSHA256: strings.Repeat("c", 64)}})
	if err != nil {
		t.Fatal(err)
	}
	path, _ := s.runtimeIdentities.CredentialPath(record.IdentityID)
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	credential := string(raw)
	if _, err = s.runtimeIdentities.Enroll(credential, "native-session"); err != nil {
		t.Fatal(err)
	}
	f := &nativeOnlineFixture{subject: skillcontext.Subject{Platform: "hermes", InstanceID: instance, AgentID: agent, SessionID: "native-session", TaskID: "task"}, credential: credential, publisher: "nhp-" + strings.Repeat("e", 64)}
	f.fault.Store("")
	// This is a transport/Authority fixture. Kernel and container attestation is
	// deliberately synthetic here, independently covered by the owned probe.
	socketDir, err := os.MkdirTemp("", "siq-online-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(socketDir) })
	socketPath := filepath.Join(socketDir, "verify.sock")
	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.Chmod(socketPath, 0600); err != nil {
		t.Fatal(err)
	}
	verifier := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.checks.Add(1)
		if r.Method != "POST" || r.URL.Path != "/verify" || r.Header.Get("Authorization") != "Bearer "+f.publisher {
			w.WriteHeader(401)
			return
		}
		var request map[string]any
		if json.NewDecoder(r.Body).Decode(&request) != nil {
			w.WriteHeader(400)
			return
		}
		body := map[string]any{"schema_version": "native-host-verified/v1", "nonce": request["nonce"], "subject": request["subject"], "artifact_sha256": request["artifact_sha256"], "expires_at": time.Now().UTC().Add(4 * time.Minute).Format(time.RFC3339Nano), "install_mounts": []any{}}
		switch f.fault.Load().(string) {
		case "offline":
			w.WriteHeader(503)
			return
		case "nonce":
			body["nonce"] = strings.Repeat("a", 32)
		case "artifact":
			body["artifact_sha256"] = strings.Repeat("a", 64)
		case "subject":
			body["subject"] = map[string]any{"platform": "hermes", "instance_id": instance, "agent_id": agent, "session_id": "other"}
		case "expired":
			body["expires_at"] = time.Now().Add(-time.Second).Format(time.RFC3339Nano)
		case "excessive-lease":
			body["expires_at"] = time.Now().Add(2 * time.Hour).Format(time.RFC3339Nano)
		case "extra":
			body["allow"] = true
		case "oversize":
			_, _ = w.Write([]byte(strings.Repeat(" ", 65537)))
			return
		}
		_ = json.NewEncoder(w).Encode(body)
	})}
	go func() { _ = verifier.Serve(listener) }()
	t.Cleanup(func() { _ = verifier.Close() })
	configDir := filepath.Join(st.Dir, "native-host")
	if err = os.Mkdir(configDir, 0700); err != nil {
		t.Fatal(err)
	}
	config, _ := json.Marshal(nativeConnection{SchemaVersion: "native-host-connection/v1", Credential: f.publisher, VerificationSocket: socketPath})
	if err = os.WriteFile(filepath.Join(configDir, "connection.json"), config, 0600); err != nil {
		t.Fatal(err)
	}
	native, err := OpenNativeRuntime(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	engine, err := receipt.New(receipt.Options{Pack: s.d.Pack, Chain: s.d.Chain, Grants: st.ActiveGrant, BaselineGrants: st.BaselineGrant, EnforcementMode: "block", Version: "test", HoldChannel: "openclaw_approval", IntentLookup: receipt.ResolveStore(s.intents), NativeCalls: native.Lookup})
	if err != nil {
		t.Fatal(err)
	}
	deps := s.d
	deps.NativeRuntime = native
	deps.Engine = engine
	next, err := New(deps)
	if err != nil {
		t.Fatal(err)
	}
	f.server, f.native = next, native
	return f
}
func (f *nativeOnlineFixture) publish(t *testing.T, event map[string]any) int {
	t.Helper()
	code, _ := scopedCall(t, f.server, "/v1/native-host/events", f.publisher, map[string]any{"schema_version": "native-host-publish/v1", "subject": f.subject, "event": event})
	return code
}
func (f *nativeOnlineFixture) prepare(t *testing.T, id, path string) (map[string]any, string) {
	t.Helper()
	params := map[string]any{"path": path}
	binding, err := trustedcontext.RequestBinding(trustedcontext.Subject{Platform: f.subject.Platform, AgentID: f.subject.AgentID, SessionID: f.subject.SessionID}, f.subject.TaskID, "read_file", id, params)
	if err != nil {
		t.Fatal(err)
	}
	if code := f.publish(t, map[string]any{"kind": "call_prepare", "tool": "read_file", "tool_call_id": id, "request_binding": binding, "load_id": ""}); code != 200 {
		t.Fatal("prepare", code)
	}
	return map[string]any{"platform": "hermes", "agent_id": f.subject.AgentID, "session_id": f.subject.SessionID, "runtime_task_id": f.subject.TaskID, "tool": "read_file", "tool_call_id": id, "params": params}, binding
}
func TestNativeOnlineRealHTTPAuthorityAndCallLifecycle(t *testing.T) {
	f := nativeOnlineServer(t)
	if code := f.publish(t, map[string]any{"kind": "task_begin", "artifact_sha256": strings.Repeat("c", 64)}); code != 200 {
		t.Fatal("begin", code)
	}
	body, binding := f.prepare(t, "allowed", "/work/public/report")
	before := f.checks.Load()
	code, decision := scopedCall(t, f.server, "/v1/decide", f.credential, body)
	if code != 200 || decision["action"] != "allow" || f.checks.Load() <= before {
		t.Fatal("online allow without fresh verifier", code, decision)
	}
	if code = f.publish(t, map[string]any{"kind": "call_finish", "tool_call_id": "allowed", "request_binding": binding}); code != 200 {
		t.Fatal("finish", code)
	}
	body, _ = f.prepare(t, "denied", "/work/private/report")
	code, decision = scopedCall(t, f.server, "/v1/decide", f.credential, body)
	if code != 200 || decision["action"] != "deny" {
		t.Fatal("online denial", code, decision)
	}
	// The deny path finishes its in-flight call even though no handler reports a result.
	body, binding = f.prepare(t, "after-denial", "/work/public/report")
	code, decision = scopedCall(t, f.server, "/v1/decide", f.credential, body)
	if code != 200 || decision["action"] != "allow" {
		t.Fatal("deny left task locked", code, decision)
	}
	if code = f.publish(t, map[string]any{"kind": "call_finish", "tool_call_id": "after-denial", "request_binding": binding}); code != 200 {
		t.Fatal(code)
	}
	if code, _ = scopedCall(t, f.server, "/v1/decide", f.credential, body); code != 409 {
		t.Fatal("replayed bound call", code)
	}
	if code = f.publish(t, map[string]any{"kind": "task_end"}); code != 200 {
		t.Fatal("end", code)
	}
	rows, err := f.server.d.Chain.Read()
	if err != nil || len(rows) != 3 || receipt.Verify(rows, f.server.d.Key.Public()) != nil {
		t.Fatal("signed chain", len(rows), err)
	}
	for _, row := range rows {
		if row.SchemaVersion != "runtime-receipt/v3" || row.NativeInvocation == nil || !row.NativeInvocation.NoSkill {
			t.Fatal("missing explicit native authority")
		}
	}
}
func TestNativeOnlineRejectsOtherCredentialsAndUnpreparedParameters(t *testing.T) {
	f := nativeOnlineServer(t)
	body := map[string]any{"schema_version": "native-host-publish/v1", "subject": f.subject, "event": map[string]any{"kind": "task_begin", "artifact_sha256": strings.Repeat("c", 64)}}
	for _, credential := range []string{token, f.server.bootAdmin, f.credential, ""} {
		if code, _ := scopedCall(t, f.server, "/v1/native-host/events", credential, body); code != 401 {
			t.Fatal("publisher credential substitution", code)
		}
	}
	raw, _ := json.Marshal(body)
	req := httptest.NewRequest("POST", "http://127.0.0.1:47611/v1/native-host/events", bytes.NewReader(raw))
	req.Header.Set("Origin", "http://127.0.0.1:47611")
	req.Header.Set("Authorization", "Bearer "+f.publisher)
	response := httptest.NewRecorder()
	f.server.Handler().ServeHTTP(response, req)
	if response.Code < 400 {
		t.Fatal("browser publisher accepted")
	}
	if code := f.publish(t, body["event"].(map[string]any)); code != 200 {
		t.Fatal(code)
	}
	decision, _ := f.prepare(t, "mismatch", "/work/public/report")
	decision["params"] = map[string]any{"path": "/work/private/report"}
	if code, _ := scopedCall(t, f.server, "/v1/decide", f.credential, decision); code != 409 {
		t.Fatal("different parameters bound", code)
	}
	rows, err := f.server.d.Chain.Read()
	if err != nil || len(rows) != 0 {
		t.Fatal("rejected binding became a decision")
	}
}
func TestNativeOnlineReverseVerificationAndPrivateConfigFailClosed(t *testing.T) {
	f := nativeOnlineServer(t)
	for _, fault := range []string{"offline", "nonce", "artifact", "subject", "expired", "excessive-lease", "extra", "oversize"} {
		t.Run(fault, func(t *testing.T) {
			f.fault.Store(fault)
			if code := f.publish(t, map[string]any{"kind": "task_begin", "artifact_sha256": strings.Repeat("c", 64)}); code != 409 {
				t.Fatal("bad reverse evidence accepted", code)
			}
		})
	}
	f.fault.Store("")
	if code := f.publish(t, map[string]any{"kind": "task_begin", "artifact_sha256": strings.Repeat("c", 64)}); code != 200 {
		t.Fatal("valid fresh begin", code)
	}
	if err := os.Chmod(f.native.configPath, 0644); err != nil {
		t.Fatal(err)
	}
	if code := f.publish(t, map[string]any{"kind": "task_end"}); code != 503 {
		t.Fatal("nonprivate config accepted", code)
	}
	if err := os.Chmod(f.native.configPath, 0600); err != nil {
		t.Fatal(err)
	}
	if code := f.publish(t, map[string]any{"kind": "task_end"}); code != 503 {
		t.Fatal("private connection resurrected", code)
	}
	f = nativeOnlineServer(t)
	if code := f.publish(t, map[string]any{"kind": "task_begin", "artifact_sha256": strings.Repeat("c", 64)}); code != 200 {
		t.Fatal(code)
	}
	body, _ := f.prepare(t, "offline-before-decision", "/work/public/report")
	f.fault.Store("offline")
	if code, _ := scopedCall(t, f.server, "/v1/decide", f.credential, body); code != 409 {
		t.Fatal("offline verifier allowed decision", code)
	}
	f.fault.Store("")
	if code, _ := scopedCall(t, f.server, "/v1/decide", f.credential, body); code != 409 {
		t.Fatal("failed task resurrected", code)
	}
}

func TestNativeOnlineHoldFinishesWithoutHandlerObservation(t *testing.T) {
	f := nativeOnlineServer(t, true)
	if code := f.publish(t, map[string]any{"kind": "task_begin", "artifact_sha256": strings.Repeat("c", 64)}); code != 200 {
		t.Fatal(code)
	}
	for _, id := range []string{"hold-one", "hold-two"} {
		body, _ := f.prepare(t, id, "/work/public/report")
		code, result := scopedCall(t, f.server, "/v1/decide", f.credential, body)
		if code != 200 || result["action"] != "hold" {
			t.Fatal("hold did not close call", code, result)
		}
	}
}

func TestNativeOnlineContractSamples(t *testing.T) {
	f := nativeOnlineServer(t)
	artifact := strings.Repeat("c", 64)
	payload := map[string]any{"schema_version": "native-host-publish/v1", "subject": f.subject, "event": map[string]any{"kind": "task_begin", "artifact_sha256": artifact}}
	nativeReadbackSample(t, "native-host-publish-v1", payload)
	code, result := scopedCall(t, f.server, "/v1/native-host/events", f.publisher, payload)
	if code != 200 {
		t.Fatal(code)
	}
	nativeReadbackSample(t, "native-host-published-v1", result)
	verified, err := f.native.verify(context.Background(), f.subject, artifact)
	if err != nil {
		t.Fatal(err)
	}
	verified.Nonce = strings.Repeat("d", 32)
	nativeReadbackSample(t, "native-host-verified-v1", verified)
	nativeReadbackSample(t, "native-host-verification-v1", map[string]any{"schema_version": "native-host-verification/v1", "nonce": verified.Nonce, "subject": f.subject, "artifact_sha256": artifact})
	nativeReadbackSample(t, "native-host-connection-v1", nativeConnection{SchemaVersion: "native-host-connection/v1", Credential: "nhp-" + strings.Repeat("b", 64), VerificationSocket: "/synthetic/native-host/verify.sock"})
}
