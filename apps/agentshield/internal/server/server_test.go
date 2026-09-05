package server

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/openshell"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"siq-agent-security/apps/agentshield/internal/ui"
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
	home := filepath.Join(dir, "home")
	if err := os.MkdirAll(home, 0o700); err != nil {
		t.Fatal(err)
	}
	s, err := New(Deps{Store: st, Engine: eng, Chain: chain, Pack: pack, Key: key, Token: token, Version: "test", Mode: mode,
		Home: home, Binary: "agentshield-test", UI: ui.Handler()})
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

func TestUIConfigIsLoopbackUnauthenticatedAndNotCached(t *testing.T) {
	s, _ := newServer(t, "block")
	req := httptest.NewRequest("GET", "/ui-config.json", nil)
	req.RemoteAddr = "127.0.0.1:9"
	rr := httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)
	if rr.Code != 200 {
		t.Fatalf("ui-config: %d %s", rr.Code, rr.Body.String())
	}
	if rr.Header().Get("Cache-Control") != "no-store" {
		t.Fatal("ui-config must not be cached")
	}
	var out map[string]any
	if err := json.Unmarshal(rr.Body.Bytes(), &out); err != nil {
		t.Fatal(err)
	}
	if out["token"] != token || out["local_mode"] != true {
		t.Fatalf("%v", out)
	}
	req = httptest.NewRequest("GET", "/ui-config.json", nil)
	req.RemoteAddr = "10.1.1.8:9"
	rr = httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)
	if rr.Code != 403 {
		t.Fatalf("non-loopback ui-config must be 403, got %d", rr.Code)
	}
}

func TestEmbeddedConsoleServesIndexWithoutBearer(t *testing.T) {
	s, _ := newServer(t, "block")
	req := httptest.NewRequest("GET", "/", nil)
	req.RemoteAddr = "127.0.0.1:9"
	rr := httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)
	if rr.Code != 200 || !strings.Contains(rr.Body.String(), "AgentShield") {
		t.Fatalf("%d %s", rr.Code, rr.Body.String())
	}
	req = httptest.NewRequest("GET", "/overview", nil)
	req.RemoteAddr = "127.0.0.1:9"
	rr = httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)
	if rr.Code != 200 || !strings.Contains(rr.Body.String(), "AgentShield") {
		t.Fatalf("SPA fallback: %d %s", rr.Code, rr.Body.String())
	}
	req = httptest.NewRequest("GET", "/missing.js", nil)
	req.RemoteAddr = "127.0.0.1:9"
	rr = httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)
	if rr.Code != 404 {
		t.Fatalf("missing asset must 404, got %d", rr.Code)
	}
}

func TestInventoryGETConfigPutAndAdapterHTTP(t *testing.T) {
	s, _ := newServer(t, "block")
	code, inv := call(t, s, "GET", "/v1/inventory", token, nil)
	if code != 200 {
		t.Fatalf("inventory GET: %d %v", code, inv)
	}
	if _, ok := inv["platforms"]; !ok {
		t.Fatalf("inventory missing platforms: %v", inv)
	}
	code, st := call(t, s, "GET", "/v1/status", token, nil)
	if code != 200 {
		t.Fatal(st)
	}
	plats, _ := st["platforms"].([]any)
	if len(plats) < 4 {
		t.Fatalf("status platforms: %v", st["platforms"])
	}
	code, cfg := call(t, s, "PUT", "/v1/config", token, map[string]any{"enforcement_mode": "warn"})
	if code != 200 || cfg["enforcement_mode"] != "warn" {
		t.Fatalf("config put: %d %v", code, cfg)
	}
	_, st = call(t, s, "GET", "/v1/status", token, nil)
	if st["enforcement_mode"] != "warn" {
		t.Fatalf("live mode: %v", st)
	}
	code, bad := call(t, s, "PUT", "/v1/config", token, map[string]any{"enforcement_mode": "explode"})
	if code != 400 {
		t.Fatalf("invalid mode must 400: %d %v", code, bad)
	}
	code, ad := call(t, s, "GET", "/v1/adapter/status", token, nil)
	if code != 200 {
		t.Fatalf("adapter status: %d %v", code, ad)
	}
	code, ins := call(t, s, "POST", "/v1/adapter/install", token, map[string]any{"platform": "hermes"})
	if code != 200 {
		t.Fatalf("install: %d %v", code, ins)
	}
	if ins["action"] != "install" {
		t.Fatalf("%v", ins)
	}
	_, ad = call(t, s, "GET", "/v1/adapter/status", token, nil)
	found := false
	for _, p := range ad["platforms"].([]any) {
		m := p.(map[string]any)
		if m["name"] == "hermes" && m["adapter"] == "installed" && m["tier"] == "L2" {
			found = true
			note, _ := m["note"].(string)
			if !strings.Contains(note, "仅工具层拦截") {
				t.Fatalf("L2 without OpenShell L3 must say tool-layer only: %v", m)
			}
		}
	}
	if !found {
		t.Fatalf("hermes not L2 after install: %v", ad)
	}
	code, un := call(t, s, "POST", "/v1/adapter/uninstall", token, map[string]any{"platform": "hermes"})
	if code != 200 || un["action"] != "uninstall" {
		t.Fatalf("uninstall: %d %v", code, un)
	}
	code, trae := call(t, s, "POST", "/v1/adapter/install", token, map[string]any{"platform": "trae"})
	if code != 200 || trae["action"] != "skipped" {
		t.Fatalf("trae must skip: %d %v", code, trae)
	}
}

func TestAdmissionOneReturnsSkillCard(t *testing.T) {
	s, _ := newServer(t, "block")
	skill, _ := filepath.Abs(filepath.Join("..", "admission", "testdata", "skills", "benign", "pure-doc"))
	_, a := call(t, s, "POST", "/v1/admit", token, map[string]any{"path": skill})
	id := a["admission"].(map[string]any)["admission_id"].(string)
	code, one := call(t, s, "GET", "/v1/admissions/"+id, token, nil)
	if code != 200 {
		t.Fatalf("%d %v", code, one)
	}
	if one["admission"] == nil {
		t.Fatalf("missing admission: %v", one)
	}
	card, _ := one["skill_card"].(string)
	if card == "" {
		t.Fatalf("missing card: %v", one)
	}
}

func TestOpenshellUnconfiguredIsL0(t *testing.T) {
	s, _ := newServer(t, "block")
	code, st := call(t, s, "GET", "/v1/status", token, nil)
	if code != 200 {
		t.Fatal(st)
	}
	found := false
	for _, p := range st["platforms"].([]any) {
		m := p.(map[string]any)
		if m["name"] == "openshell" {
			found = true
			if m["tier"] != "L0" {
				t.Fatalf("unconfigured OpenShell must be L0: %v", m)
			}
		}
	}
	if !found {
		t.Fatalf("openshell platform missing: %v", st["platforms"])
	}
	code, probe := call(t, s, "GET", "/v1/openshell/probe", token, nil)
	if code != 200 || probe["ok"] != false {
		t.Fatalf("probe: %d %v", code, probe)
	}
	code, doctor := call(t, s, "GET", "/v1/openshell/doctor", token, nil)
	if code != 200 || doctor["source"] != "none" || doctor["started_gateway"] != false || doctor["tier"] != "L0" {
		t.Fatalf("doctor: %d %v", code, doctor)
	}
	code, apply := call(t, s, "POST", "/v1/openshell/apply", token, map[string]any{"target": "s1", "network": []any{}})
	if code != 503 {
		t.Fatalf("apply without backend must 503, got %d %v", code, apply)
	}
}

func TestOpenshellProbeL3AndNetworkApply(t *testing.T) {
	full, err := os.ReadFile(filepath.Join("..", "openshell", "testdata", "policy_get_full.txt"))
	if err != nil {
		t.Fatal(err)
	}
	v2, err := os.ReadFile(filepath.Join("..", "openshell", "testdata", "policy_get_full_v2.txt"))
	if err != nil {
		t.Fatal(err)
	}
	cli := openshell.New(openshell.Options{EnvScript: "/nonexistent/env.sh", PollInterval: -1, Runner: func(args []string) (int, string, string) {
		if len(args) >= 2 && args[0] == "gateway" && args[1] == "info" {
			return 0, "Gateway Info\n  Gateway version: 0.0.104\n", ""
		}
		if len(args) == 1 && args[0] == "status" {
			return 0, "Server Status\n  Gateway: siq-openshell-dev\n", ""
		}
		if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
			return 0, string(full), ""
		}
		if len(args) >= 2 && args[0] == "policy" && args[1] == "set" {
			return 0, "Policy version 2 submitted (hash: 5385cd2cf66f)\n", ""
		}
		return 1, "", "unexpected " + strings.Join(args, " ")
	}})
	s, _ := newServer(t, "block")
	s.d.Openshell = cli
	code, probe := call(t, s, "GET", "/v1/openshell/probe", token, nil)
	if code != 200 || probe["ok"] != true || probe["tier"] != "L3" {
		t.Fatalf("probe L3: %d %v", code, probe)
	}
	_, st := call(t, s, "GET", "/v1/status", token, nil)
	found := false
	for _, p := range st["platforms"].([]any) {
		m := p.(map[string]any)
		if m["name"] == "openshell" && m["tier"] == "L3" {
			found = true
		}
	}
	if !found {
		t.Fatalf("status missing L3: %v", st["platforms"])
	}

	// After set, readback should see v2 network so verify can pass.
	cli2 := openshell.New(openshell.Options{EnvScript: "/nonexistent/env.sh", PollInterval: -1, Runner: func(args []string) (int, string, string) {
		if len(args) >= 2 && args[0] == "gateway" && args[1] == "info" {
			return 0, "Gateway Info\n  Gateway version: 0.0.104\n", ""
		}
		if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
			return 0, string(v2), ""
		}
		if len(args) >= 2 && args[0] == "policy" && args[1] == "set" {
			return 0, "Policy version 2 submitted (hash: 5385cd2cf66f)\n", ""
		}
		return 1, "", "unexpected"
	}})
	s.d.Openshell = cli2
	code, applied := call(t, s, "POST", "/v1/openshell/apply", token, map[string]any{
		"target": "s1", "expected_revision": "2",
		"network":      []any{map[string]any{"endpoint": "api.example.com:443", "effect": "allow"}},
		"expect_allow": []string{"api.example.com:443"},
		"expect_deny":  []string{"192.0.2.1:1"},
	})
	if code != 200 || applied["passed"] != true || applied["verify_level"] != "readback_verified" {
		t.Fatalf("apply: %d %v", code, applied)
	}
	rb := applied["effective_readback"].(map[string]any)
	if rb["backend"] != "openshell" || rb["revision"] != "2" {
		t.Fatalf("readback: %v", rb)
	}
}

func TestOpenshellApplyRejectsCreatePathAndRevisionConflict(t *testing.T) {
	full, err := os.ReadFile(filepath.Join("..", "openshell", "testdata", "policy_get_full.txt"))
	if err != nil {
		t.Fatal(err)
	}
	cli := openshell.New(openshell.Options{EnvScript: "/nonexistent/env.sh", PollInterval: -1, Runner: func(args []string) (int, string, string) {
		if strings.Contains(strings.Join(args, " "), "create") {
			t.Fatalf("create_generation must not run: %v", args)
		}
		if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
			return 0, string(full), ""
		}
		return 1, "", "unexpected"
	}})
	s, _ := newServer(t, "block")
	s.d.Openshell = cli
	code, out := call(t, s, "POST", "/v1/openshell/apply", token, map[string]any{
		"target": "s1", "expected_revision": "99",
		"network": []any{map[string]any{"endpoint": "api.example.com:443"}},
	})
	if code != 409 {
		t.Fatalf("conflict: %d %v", code, out)
	}
}

func TestLedgerAssetsPermissionsFindings(t *testing.T) {
	s, _ := newServer(t, "block")
	demo := filepath.Join(s.d.Home, ".hermes", "skills", "demo")
	if err := os.MkdirAll(demo, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(demo, "SKILL.md"), []byte("---\nname: demo\nallowed-tools: web_fetch\n---\n# d\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	code, body := call(t, s, "GET", "/v1/assets", token, nil)
	if code != 200 {
		t.Fatalf("assets: %d %v", code, body)
	}
	list, _ := body["assets"].([]any)
	var skillID string
	for _, raw := range list {
		row, _ := raw.(map[string]any)
		if row["source_type"] == "skill_dir" && row["name"] == "demo" {
			skillID, _ = row["id"].(string)
			if row["status"] != "unadmitted" {
				t.Fatalf("unadmitted skill: %v", row)
			}
		}
	}
	if skillID == "" {
		t.Fatalf("demo skill missing: %v", body)
	}
	code, detail := call(t, s, "GET", "/v1/assets/"+skillID, token, nil)
	if code != 200 || detail["id"] != skillID {
		t.Fatalf("detail: %d %v", code, detail)
	}
	if code, miss := call(t, s, "GET", "/v1/assets/no-such-asset", token, nil); code != 404 {
		t.Fatalf("missing asset: %d %v", code, miss)
	}

	toxic, _ := filepath.Abs(filepath.Join("..", "admission", "testdata", "skills", "malicious", "env-webhook"))
	call(t, s, "POST", "/v1/admit", token, map[string]any{"path": toxic})
	code, fnd := call(t, s, "GET", "/v1/findings", token, nil)
	if code != 200 {
		t.Fatalf("findings: %d %v", code, fnd)
	}
	findings, _ := fnd["findings"].([]any)
	if len(findings) == 0 {
		t.Fatal("quarantine admission must project findings")
	}

	clean, _ := filepath.Abs(filepath.Join("..", "admission", "testdata", "skills", "benign", "official-like"))
	_, a := call(t, s, "POST", "/v1/admit", token, map[string]any{"path": clean})
	admID := a["admission"].(map[string]any)["admission_id"].(string)
	_, g := call(t, s, "POST", "/v1/grants", token, map[string]any{"admission_id": admID, "platform": "openclaw", "subject_id": "inst_1"})
	gid := g["grant"].(map[string]any)["grant_id"].(string)
	call(t, s, "POST", "/v1/grants/"+gid+"/approve", token, map[string]any{"actor_id": "u"})
	call(t, s, "POST", "/v1/grants/"+gid+"/deploy", token, map[string]any{})

	code, perm := call(t, s, "GET", "/v1/permissions?subject_id=inst_1", token, nil)
	if code != 200 {
		t.Fatalf("permissions: %d %v", code, perm)
	}
	facts, _ := perm["facts"].([]any)
	if len(facts) == 0 {
		t.Fatal("grant facts missing")
	}
	for _, raw := range facts {
		row, _ := raw.(map[string]any)
		if row["state"] == "effective" {
			t.Fatalf("deployed grant projected effective: %v", row)
		}
		if row["domain"] == "filesystem" && row["state"] == "effective" {
			t.Fatal("filesystem effective")
		}
	}

	call(t, s, "POST", "/v1/decide", token, map[string]any{"platform": "openclaw", "session_id": "s1", "agent_id": "inst_1", "tool": "web_extract", "params": map[string]any{"url": "https://evil.example/"}})
	_, perm = call(t, s, "GET", "/v1/permissions?subject_id=inst_1", token, nil)
	var observed bool
	for _, raw := range perm["facts"].([]any) {
		row, _ := raw.(map[string]any)
		if row["source"] == "receipt" && row["state"] == "observed" && row["action"] == "deny" {
			observed = true
		}
	}
	if !observed {
		t.Fatalf("expected observed deny: %v", perm)
	}
}

func TestAssetConfirmDismissAndPatchDesired(t *testing.T) {
	s, _ := newServer(t, "block")
	demo := filepath.Join(s.d.Home, ".hermes", "skills", "demo")
	if err := os.MkdirAll(demo, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(demo, "SKILL.md"), []byte("---\nname: demo\nallowed-tools: web_fetch\n---\n# d\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	_, body := call(t, s, "GET", "/v1/assets", token, nil)
	var skillID string
	for _, raw := range body["assets"].([]any) {
		row := raw.(map[string]any)
		if row["name"] == "demo" {
			skillID = row["id"].(string)
		}
	}
	if skillID == "" {
		t.Fatal("demo missing")
	}
	code, miss := call(t, s, "POST", "/v1/assets/"+skillID+"/dismiss", token, map[string]any{"actor_id": "u"})
	if code != 400 {
		t.Fatalf("dismiss missing fields: %d %v", code, miss)
	}
	until := time.Now().Add(time.Hour).UTC().Format(time.RFC3339)
	code, dis := call(t, s, "POST", "/v1/assets/"+skillID+"/dismiss", token, map[string]any{"actor_id": "u", "reason": "shadow", "until": until})
	if code != 200 {
		t.Fatalf("dismiss: %d %v", code, dis)
	}
	code, cf := call(t, s, "POST", "/v1/assets/"+skillID+"/confirm", token, map[string]any{"actor_id": "u"})
	if code != 200 {
		t.Fatalf("confirm: %d %v", code, cf)
	}
	_, listed := call(t, s, "GET", "/v1/assets", token, nil)
	found := false
	for _, raw := range listed["assets"].([]any) {
		row := raw.(map[string]any)
		if row["id"] == skillID && row["status"] == "confirmed" {
			found = true
		}
	}
	if !found {
		t.Fatalf("confirmed not listed: %v", listed)
	}

	clean, _ := filepath.Abs(filepath.Join("..", "admission", "testdata", "skills", "benign", "official-like"))
	_, a := call(t, s, "POST", "/v1/admit", token, map[string]any{"path": clean})
	admID := a["admission"].(map[string]any)["admission_id"].(string)
	_, g := call(t, s, "POST", "/v1/grants", token, map[string]any{"admission_id": admID, "platform": "hermes", "subject_id": "inst_p"})
	gid := g["grant"].(map[string]any)["grant_id"].(string)
	code, patched := call(t, s, "POST", "/v1/grants/"+gid+"/patch-desired", token, map[string]any{
		"tools":   []string{"web_fetch"},
		"network": []any{map[string]any{"endpoint": "api.example.com:443", "effect": "allow"}},
	})
	if code != 200 {
		t.Fatalf("patch: %d %v", code, patched)
	}
	call(t, s, "POST", "/v1/grants/"+gid+"/approve", token, map[string]any{"actor_id": "u"})
	code, again := call(t, s, "POST", "/v1/grants/"+gid+"/patch-desired", token, map[string]any{"tools": []string{"read_file"}})
	if code != 400 {
		t.Fatalf("patch after approve: %d %v", code, again)
	}
	_, aud := call(t, s, "GET", "/v1/audit", token, nil)
	if evs, _ := aud["events"].([]any); len(evs) == 0 {
		t.Fatalf("audit empty: %v", aud)
	}
}

func TestDriftCheckFailClosedAndFinding(t *testing.T) {
	s, _ := newServer(t, "block")
	code, no := call(t, s, "POST", "/v1/openshell/drift-check", token, map[string]any{})
	if code != 503 {
		t.Fatalf("no cli: %d %v", code, no)
	}
	failCLI := openshell.New(openshell.Options{EnvScript: "/nonexistent/env.sh", PollInterval: -1, Runner: func(args []string) (int, string, string) {
		return 1, "", "boom"
	}})
	s.d.Openshell = failCLI
	_, before := call(t, s, "GET", "/v1/findings", token, nil)
	beforeN := 0
	if f, ok := before["findings"].([]any); ok {
		beforeN = len(f)
	}
	code, fail := call(t, s, "POST", "/v1/openshell/drift-check", token, map[string]any{})
	if code < 500 {
		t.Fatalf("probe fail must 5xx: %d %v", code, fail)
	}
	_, after := call(t, s, "GET", "/v1/findings", token, nil)
	afterN := 0
	if f, ok := after["findings"].([]any); ok {
		afterN = len(f)
	}
	if afterN != beforeN {
		t.Fatalf("failed drift-check must not add findings: %d → %d", beforeN, afterN)
	}

	full, err := os.ReadFile(filepath.Join("..", "openshell", "testdata", "policy_get_full.txt"))
	if err != nil {
		t.Fatal(err)
	}
	okCLI := openshell.New(openshell.Options{EnvScript: "/nonexistent/env.sh", PollInterval: -1, Runner: func(args []string) (int, string, string) {
		if len(args) >= 2 && args[0] == "gateway" && args[1] == "info" {
			return 0, "Gateway Info\n  Gateway version: 0.0.104\n", ""
		}
		if len(args) == 1 && args[0] == "status" {
			return 0, "Server Status\n  Gateway: siq-openshell-dev\n", ""
		}
		if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
			return 0, string(full), ""
		}
		return 1, "", "unexpected"
	}})
	s.d.Openshell = okCLI
	clean, _ := filepath.Abs(filepath.Join("..", "admission", "testdata", "skills", "benign", "official-like"))
	_, a := call(t, s, "POST", "/v1/admit", token, map[string]any{"path": clean})
	admID := a["admission"].(map[string]any)["admission_id"].(string)
	_, g := call(t, s, "POST", "/v1/grants", token, map[string]any{"admission_id": admID, "platform": "hermes", "subject_id": "s1"})
	gid := g["grant"].(map[string]any)["grant_id"].(string)
	call(t, s, "POST", "/v1/grants/"+gid+"/patch-desired", token, map[string]any{
		"network": []any{map[string]any{"endpoint": "api.github.com:443", "effect": "allow"}},
	})
	call(t, s, "POST", "/v1/grants/"+gid+"/approve", token, map[string]any{"actor_id": "u"})
	call(t, s, "POST", "/v1/grants/"+gid+"/deploy", token, map[string]any{})
	code, drift := call(t, s, "POST", "/v1/openshell/drift-check", token, map[string]any{})
	if code != 200 {
		t.Fatalf("drift: %d %v", code, drift)
	}
	written, _ := drift["findings_written"].([]any)
	if len(written) == 0 {
		t.Fatalf("expected drift finding vs empty network readback: %v", drift)
	}
}

var _ = http.StatusOK
