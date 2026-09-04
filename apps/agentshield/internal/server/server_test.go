package server

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

const token = "0123456789abcdef0123456789abcdef0123456789abcdef"

func newServer(t *testing.T, mode string) (*Server, *state.Store) {
	t.Helper()
	dir := t.TempDir()
	st, err := state.Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	key, _ := signing.FromSeed(bytes.Repeat([]byte{3}, 32))
	pack, _ := rulepack.Builtin()
	chain, err := receipt.OpenChain(dir, "local", key)
	if err != nil {
		t.Fatal(err)
	}
	eng, err := receipt.New(receipt.Options{Pack: pack, Chain: chain, Grants: st.ActiveGrant, EnforcementMode: mode, Version: "test", HoldChannel: "openclaw_approval"})
	if err != nil {
		t.Fatal(err)
	}
	s, err := New(Deps{Store: st, Engine: eng, Chain: chain, Pack: pack, Key: key, Token: token, Version: "test", Mode: mode})
	if err != nil {
		t.Fatal(err)
	}
	return s, st
}

func call(t *testing.T, s *Server, method, path, tok string, body any) (int, map[string]any) {
	t.Helper()
	var buf bytes.Buffer
	if body != nil {
		_ = json.NewEncoder(&buf).Encode(body)
	}
	req := httptest.NewRequest(method, path, &buf)
	req.RemoteAddr = "127.0.0.1:5555"
	if tok != "" {
		req.Header.Set("Authorization", "Bearer "+tok)
	}
	rr := httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)
	var out map[string]any
	_ = json.Unmarshal(rr.Body.Bytes(), &out)
	return rr.Code, out
}

func TestAuthAndLoopbackAreEnforced(t *testing.T) {
	s, _ := newServer(t, "block")
	if code, _ := call(t, s, "GET", "/v1/status", "", nil); code != 401 {
		t.Fatalf("missing token must be 401, got %d", code)
	}
	if code, _ := call(t, s, "GET", "/v1/status", "wrong", nil); code != 401 {
		t.Fatal("wrong token must be 401")
	}
	req := httptest.NewRequest("GET", "/v1/status", nil)
	req.RemoteAddr = "10.0.0.7:4444"
	req.Header.Set("Authorization", "Bearer "+token)
	rr := httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)
	if rr.Code != 403 {
		t.Fatalf("non-loopback must be 403, got %d", rr.Code)
	}
	code, st := call(t, s, "GET", "/v1/status", token, nil)
	if code != 200 || st["local_mode"] != true || st["enforcement_mode"] != "block" {
		t.Fatalf("%d %v", code, st)
	}
}

func TestEndToEndAdmitGrantDecide(t *testing.T) {
	s, _ := newServer(t, "block")
	skill, _ := filepath.Abs(filepath.Join("..", "admission", "testdata", "skills", "benign", "official-like"))

	// decide before any grant → default deny
	code, d := call(t, s, "POST", "/v1/decide", token, map[string]any{"platform": "openclaw", "session_id": "s1", "agent_id": "inst_1", "tool": "read_file", "params": map[string]any{"path": "/tmp/x"}})
	if code != 200 || d["action"] != "deny" {
		t.Fatalf("%d %v", code, d)
	}

	code, a := call(t, s, "POST", "/v1/admit", token, map[string]any{"path": skill, "trust_level": "trusted"})
	if code != 200 {
		t.Fatalf("admit: %d %v", code, a)
	}
	adm := a["admission"].(map[string]any)
	if adm["verdict"] != "admit_with_conditions" {
		t.Fatalf("%v", adm["verdict"])
	}
	admID := adm["admission_id"].(string)

	code, g := call(t, s, "POST", "/v1/grants", token, map[string]any{"admission_id": admID, "platform": "openclaw", "subject_id": "inst_1"})
	if code != 200 {
		t.Fatalf("grant: %d %v", code, g)
	}
	gid := g["grant"].(map[string]any)["grant_id"].(string)

	// still deny: grant is pending
	_, d = call(t, s, "POST", "/v1/decide", token, map[string]any{"platform": "openclaw", "session_id": "s1", "agent_id": "inst_1", "tool": "read_file", "params": map[string]any{"path": "/tmp/x"}})
	if d["action"] != "deny" {
		t.Fatal("pending grant must not authorise")
	}

	if code, r := call(t, s, "POST", "/v1/grants/"+gid+"/approve", token, map[string]any{}); code != 400 {
		t.Fatalf("approve without actor must fail: %d %v", code, r)
	}
	if code, r := call(t, s, "POST", "/v1/grants/"+gid+"/approve", token, map[string]any{"actor_id": "u-admin"}); code != 200 {
		t.Fatalf("approve: %d %v", code, r)
	}
	if code, r := call(t, s, "POST", "/v1/grants/"+gid+"/deploy", token, map[string]any{}); code != 200 {
		t.Fatalf("deploy: %d %v", code, r)
	}

	// granted tool, granted host → allow
	_, d = call(t, s, "POST", "/v1/decide", token, map[string]any{"platform": "openclaw", "session_id": "s1", "agent_id": "inst_1", "tool": "web_extract", "params": map[string]any{"url": "https://api.github.com/repos"}})
	if d["action"] != "allow" {
		t.Fatalf("%v", d)
	}
	// ungranted host → deny
	_, d = call(t, s, "POST", "/v1/decide", token, map[string]any{"platform": "openclaw", "session_id": "s1", "agent_id": "inst_1", "tool": "web_extract", "params": map[string]any{"url": "https://evil.example/"}})
	if d["action"] != "deny" || !strings.Contains(d["reason"].(string), "evil.example") {
		t.Fatalf("%v", d)
	}
	// exec requires approval (openclaw) → hold, then resolve
	_, d = call(t, s, "POST", "/v1/decide", token, map[string]any{"platform": "openclaw", "session_id": "s1", "agent_id": "inst_1", "tool": "exec", "params": map[string]any{"command": "ls"}})
	if d["action"] != "hold" || d["hold"] == nil {
		t.Fatalf("%v", d)
	}
	rid := d["receipt_id"].(string)
	if code, r := call(t, s, "POST", "/v1/hold/"+rid, token, map[string]any{"approve": true}); code != 400 {
		t.Fatalf("resolve without actor must fail: %d %v", code, r)
	}
	code, r := call(t, s, "POST", "/v1/hold/"+rid, token, map[string]any{"approve": true, "actor_id": "u-admin"})
	if code != 200 || r["action"] != "allow" {
		t.Fatalf("%d %v", code, r)
	}
	// observe taints, then egress denied
	call(t, s, "POST", "/v1/observe", token, map[string]any{"platform": "openclaw", "session_id": "s1", "agent_id": "inst_1", "tool": "web_extract", "result": "leaked: sk-" + strings.Repeat("Z", 40)})
	_, d = call(t, s, "POST", "/v1/decide", token, map[string]any{"platform": "openclaw", "session_id": "s1", "agent_id": "inst_1", "tool": "web_extract", "params": map[string]any{"url": "https://api.github.com/x"}})
	if d["action"] != "deny" || !strings.HasPrefix(d["reason"].(string), "tainted egress") {
		t.Fatalf("%v", d)
	}
	// receipts are chained and verified
	code, rc := call(t, s, "GET", "/v1/receipts?since_seq=-1", token, nil)
	if code != 200 || rc["verified"] != true || len(rc["receipts"].([]any)) < 6 {
		t.Fatalf("%d %v", code, rc["verified"])
	}
	// no params in receipts
	raw, _ := json.Marshal(rc)
	if bytes.Contains(raw, []byte("\"params\":")) || bytes.Contains(raw, []byte(strings.Repeat("Z", 40))) {
		t.Fatal("receipts leaked parameters or secret")
	}
}

func TestQuarantinedAdmissionCannotBeGranted(t *testing.T) {
	s, _ := newServer(t, "block")
	skill, _ := filepath.Abs(filepath.Join("..", "admission", "testdata", "skills", "malicious", "env-webhook"))
	_, a := call(t, s, "POST", "/v1/admit", token, map[string]any{"path": skill})
	admID := a["admission"].(map[string]any)["admission_id"].(string)
	code, g := call(t, s, "POST", "/v1/grants", token, map[string]any{"admission_id": admID, "platform": "hermes", "subject_id": "inst_1"})
	if code != 400 || !strings.Contains(g["error"].(string), "quarantined") {
		t.Fatalf("%d %v", code, g)
	}
}

func TestDecideRejectsMalformedAndAuditOnlyAllows(t *testing.T) {
	s, _ := newServer(t, "audit_only")
	if code, _ := call(t, s, "POST", "/v1/decide", token, map[string]any{"platform": "openclaw"}); code != 400 {
		t.Fatal("missing fields must be 400")
	}
	req := httptest.NewRequest("POST", "/v1/decide", strings.NewReader("{not json"))
	req.RemoteAddr = "127.0.0.1:1"
	req.Header.Set("Authorization", "Bearer "+token)
	rr := httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)
	if rr.Code != 400 {
		t.Fatal("malformed JSON must be 400")
	}
	_, d := call(t, s, "POST", "/v1/decide", token, map[string]any{"platform": "openclaw", "session_id": "s", "tool": "exec", "params": map[string]any{"command": "curl https://evil.example"}})
	if d["action"] != "allow" {
		t.Fatalf("audit_only must allow: %v", d)
	}
}

func TestStateStoreVersionsGrantsAndNeverRewrites(t *testing.T) {
	s, st := newServer(t, "block")
	skill, _ := filepath.Abs(filepath.Join("..", "admission", "testdata", "skills", "benign", "pure-doc"))
	_, a := call(t, s, "POST", "/v1/admit", token, map[string]any{"path": skill})
	admID := a["admission"].(map[string]any)["admission_id"].(string)
	_, g := call(t, s, "POST", "/v1/grants", token, map[string]any{"admission_id": admID, "platform": "hermes", "subject_id": "x"})
	gid := g["grant"].(map[string]any)["grant_id"].(string)
	call(t, s, "POST", "/v1/grants/"+gid+"/approve", token, map[string]any{"actor_id": "u"})
	matches, _ := filepath.Glob(filepath.Join(st.Dir, "grants", gid+".*.json"))
	if len(matches) != 2 {
		t.Fatalf("expected 2 grant versions on disk, got %d", len(matches))
	}
	latest, err := st.GetGrant(gid)
	if err != nil || latest.Status != "approved" {
		t.Fatalf("%v %v", err, latest)
	}
	if _, err := st.GetAdmission("../../etc/passwd"); err == nil {
		t.Fatal("path traversal id must be rejected")
	}
	tok1, _ := st.Token()
	tok2, _ := st.Token()
	if tok1 != tok2 || len(tok1) != 64 {
		t.Fatal("token must be stable and 32 bytes hex")
	}
	cfg, err := st.LoadConfig()
	if err != nil || cfg.EnforcementMode != "block" || cfg.Port != 47611 {
		t.Fatalf("%v %+v", err, cfg)
	}
}

var _ = http.StatusOK
