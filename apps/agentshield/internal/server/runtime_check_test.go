package server

import (
	"context"
	"encoding/json"
	"errors"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/runtimecheck"
)

const runtimeInstance = "hi-0123456789abcdef0123456789abcdef"

func runtimeHTTPFixture(t *testing.T) (*Server, *atomic.Bool) {
	t.Helper()
	s, _ := newServer(t, "block")
	changed := &atomic.Bool{}
	m, err := runtimecheck.New(runtimecheck.Options{Store: s.d.Store, Intents: s.intents, Key: s.d.Key, Pack: s.d.Pack, Chain: s.d.Chain, Endpoint: "http://127.0.0.1:47611", Snapshot: func(id string) (adapterinstall.RuntimeTarget, error) {
		if id != runtimeInstance {
			return adapterinstall.RuntimeTarget{}, errors.New("runtime_check_instance_unavailable")
		}
		hash := "a"
		if changed.Load() {
			hash = "b"
		}
		// This HTTP failure fixture deliberately has no executable host. Native
		// success is verified separately through the installed Hermes public CLI.
		return adapterinstall.RuntimeTarget{InstanceID: id, Home: s.d.Home, ProfilePath: s.d.Home, NativeCLI: filepath.Join(s.d.Home, "missing-host"), Digest: strings.Repeat(hash, 64)}, nil
	}})
	if err != nil {
		t.Fatal(err)
	}
	s.runtimeChecks = m
	t.Cleanup(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := s.CloseRuntimeChecks(ctx); err != nil {
			t.Error(err)
		}
	})
	return s, changed
}

func TestRuntimeCheckHTTPAuthorizationAndStrictInput(t *testing.T) {
	s, _ := runtimeHTTPFixture(t)
	preview := map[string]any{"schema_version": "local-runtime-check-preview/v1", "instance_id": runtimeInstance}
	for _, route := range []struct{ method, path string }{
		{"POST", "/v1/runtime-checks/preview"}, {"POST", "/v1/runtime-checks/start"},
		{"GET", "/v1/runtime-checks?instance_id=" + runtimeInstance}, {"GET", "/v1/runtime-checks/rc-" + strings.Repeat("a", 32)},
		{"POST", "/v1/runtime-checks/rc-" + strings.Repeat("a", 32) + "/cancel"}, {"POST", "/v1/runtime-checks/rc-" + strings.Repeat("a", 32) + "/cleanup"},
	} {
		for _, credential := range []string{"", token, strings.Repeat("f", 64)} {
			w := sessionRequest(t, s, route.method, route.path, preview, credential, nil, nil)
			if w.Code != 401 && w.Code != 403 {
				t.Fatalf("unprivileged %s: %d", route.path, w.Code)
			}
		}
	}
	raw, _ := json.Marshal(preview)
	for _, body := range []any{
		string(raw) + "{}", string(raw) + " garbage", `{"schema_version":"local-runtime-check-preview/v1","instance_id":null}`,
		map[string]any{"schema_version": "local-runtime-check-preview/v1", "instance_id": runtimeInstance, "command": "arbitrary"},
		map[string]any{"schema_version": "unknown", "instance_id": runtimeInstance}, strings.Repeat(" ", 16384) + string(raw),
	} {
		w := sessionRequest(t, s, "POST", "/v1/runtime-checks/preview", body, s.bootAdmin, nil, nil)
		if w.Code != 400 {
			t.Fatalf("invalid input accepted: %d", w.Code)
		}
	}
	for _, credential := range []string{"", token, s.bootAdmin, strings.Repeat("f", 64)} {
		w := sessionRequest(t, s, "POST", "/v1/runtime-checks/attach", map[string]any{"schema_version": "local-runtime-check-attach/v1", "check_id": "rc-" + strings.Repeat("a", 32), "instance_id": runtimeInstance, "agent_id": "rca-" + strings.Repeat("a", 32), "session_id": "native-fixture"}, credential, nil, nil)
		if w.Code != 403 {
			t.Fatalf("non-launch credential attached: %d", w.Code)
		}
	}
	w := sessionRequest(t, s, "POST", "/v1/runtime-checks/preview", preview, s.bootAdmin, nil, map[string]string{"Origin": "http://evil.example"})
	if w.Code != 403 {
		t.Fatal("cross-origin preview accepted")
	}
	grants, err := s.d.Store.ListGrants()
	if err != nil || len(grants) != 0 {
		t.Fatal("invalid requests created authority", err)
	}
}

func TestRuntimeCheckHTTPConfirmationDriftAndFailureCleanup(t *testing.T) {
	s, changed := runtimeHTTPFixture(t)
	code, plan := call(t, s, "POST", "/v1/runtime-checks/preview", token, map[string]any{"schema_version": "local-runtime-check-preview/v1", "instance_id": runtimeInstance})
	if code != 200 {
		t.Fatal(code, plan)
	}
	body := map[string]any{"schema_version": "local-runtime-check-start/v1", "check_id": plan["check_id"], "plan_digest": plan["plan_digest"], "actor_id": "operator", "confirm": false}
	if code, _ := call(t, s, "POST", "/v1/runtime-checks/start", token, body); code != 400 {
		t.Fatal("missing confirmation accepted", code)
	}
	body["confirm"] = true
	body["plan_digest"] = strings.Repeat("0", 64)
	if code, _ := call(t, s, "POST", "/v1/runtime-checks/start", token, body); code != 403 {
		t.Fatal("digest substitution accepted", code)
	}
	body["plan_digest"] = plan["plan_digest"]
	// A second valid admin can manage checks, but cannot confirm another
	// session's unconsumed preview.
	other, err := newSessionToken()
	if err != nil {
		t.Fatal(err)
	}
	s.sessMu.Lock()
	s.sessions[other] = time.Now().Add(adminSessionTTL)
	s.sessMu.Unlock()
	if code, _ := call(t, s, "POST", "/v1/runtime-checks/start", other, body); code != 403 {
		t.Fatal("cross-session confirmation accepted", code)
	}
	changed.Store(true)
	if code, _ := call(t, s, "POST", "/v1/runtime-checks/start", token, body); code != 409 {
		t.Fatal("drift accepted", code)
	}
	changed.Store(false)
	code, started := call(t, s, "POST", "/v1/runtime-checks/start", token, body)
	if code != 202 || started["status"] != "preparing" {
		t.Fatal(code, started)
	}
	id := plan["check_id"].(string)
	if code, _ := call(t, s, "POST", "/v1/runtime-checks/start", token, body); code != 404 {
		t.Fatal("replay accepted", code)
	}
	deadline := time.Now().Add(5 * time.Second)
	var result map[string]any
	for time.Now().Before(deadline) {
		code, result = call(t, s, "GET", "/v1/runtime-checks/"+id, token, nil)
		if code != 200 {
			t.Fatal(code, result)
		}
		if result["status"] == "failed" {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	if result["status"] != "failed" || result["cleanup"] != "complete" || result["finished_at"] == nil {
		t.Fatal(result)
	}
	for _, action := range []string{"cancel", "cleanup"} {
		code, repeated := call(t, s, "POST", "/v1/runtime-checks/"+id+"/"+action, token, nil)
		if code != 200 || repeated["status"] != "failed" || repeated["cleanup"] != "complete" {
			t.Fatal(code, repeated)
		}
	}
	code, list := call(t, s, "GET", "/v1/runtime-checks?instance_id="+runtimeInstance, token, nil)
	if code != 200 || len(list["items"].([]any)) != 1 {
		t.Fatal(code, list)
	}
	grants, err := s.d.Store.ListGrants()
	if err != nil || len(grants) != 1 || grants[0].Status != "revoked" {
		t.Fatal("authority survived failed host", err)
	}
}
