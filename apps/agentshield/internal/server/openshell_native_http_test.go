package server

// This harness also runs unchanged against the pre-O04 source snapshot.
// Real loopback HTTP; fixture skill and local signed state, no agent effects.
import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/openshell"
	"sync/atomic"
	"testing"
	"time"
)

func TestO04NativeHTTP(t *testing.T) {
	s, _ := newServer(t, "block")
	var commands atomic.Int64
	s.d.Openshell = openshell.New(openshell.Options{
		LookupEnv:    func(string) (string, bool) { return "", false },
		LookPath:     func(string) (string, error) { return "", fmt.Errorf("unconfigured") },
		Runner:       func([]string) (int, string, string) { commands.Add(1); return 1, "", "unexpected" },
		DockerRunner: func([]string) (int, string, string) { commands.Add(1); return 1, "", "unexpected" },
	})
	service := httptest.NewServer(s.Handler())
	defer service.Close()
	client := service.Client()
	client.Timeout = 10 * time.Second
	requests := 0
	request := func(method, path, credential string, body any, want int) map[string]any {
		t.Helper()
		var data bytes.Buffer
		if body != nil {
			if err := json.NewEncoder(&data).Encode(body); err != nil {
				t.Fatal(err)
			}
		}
		req, err := http.NewRequest(method, service.URL+path, &data)
		if err != nil {
			t.Fatal(err)
		}
		// Virtual Host matches configured loopback; transport still uses real TCP.
		req.Host = "127.0.0.1:47611"
		req.Header.Set("Content-Type", "application/json")
		if credential != "" {
			req.Header.Set("Authorization", "Bearer "+credential)
		}
		started := time.Now()
		resp, err := client.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer resp.Body.Close()
		requests++
		var out map[string]any
		if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
			t.Fatal(err)
		}
		if resp.StatusCode != want {
			t.Fatalf("%s %s status %d, want %d", method, path, resp.StatusCode, want)
		}
		out["_elapsed_ms"] = float64(time.Since(started).Nanoseconds()) / 1e6
		return out
	}
	request("GET", "/v1/status", "", nil, 401)
	request("GET", "/v1/status", "wrong", nil, 401)
	request("GET", "/v1/status", s.bootAdmin, nil, 200)
	body := map[string]any{"platform": "openclaw", "session_id": nativeOpenClawSession(t, "http-benchmark"), "agent_id": "inst_1", "tool": "web_extract", "params": map[string]any{"url": "https://api.github.com/repos"}}
	decide := func(want string) float64 {
		t.Helper()
		d := request("POST", "/v1/decide", token, body, 200)
		if d["action"] != want {
			t.Fatalf("decision %v, want %s", d["action"], want)
		}
		return d["_elapsed_ms"].(float64)
	}
	decide("deny")
	skill, err := filepath.Abs(filepath.Join("..", "admission", "testdata", "skills", "benign", "official-like"))
	if err != nil {
		t.Fatal(err)
	}
	a := request("POST", "/v1/admit", s.bootAdmin, map[string]any{"path": skill, "trust_level": "trusted"}, 200)
	aid := a["admission"].(map[string]any)["admission_id"]
	g := request("POST", "/v1/grants", s.bootAdmin, map[string]any{"admission_id": aid, "platform": "openclaw", "subject_id": "inst_1"}, 200)
	gid := g["grant"].(map[string]any)["grant_id"].(string)
	path := "/v1/grants/" + gid
	rev := stateRevision(t, g)
	decide("deny")
	challenge := request("POST", path+"/challenge", s.bootAdmin, withRevision(nil, rev), 200)["challenge"].(map[string]any)
	approved := request("POST", path+"/approve", s.bootAdmin, withRevision(map[string]any{"actor_id": "test-admin", "challenge_id": challenge["challenge_id"], "nonce": challenge["nonce"]}, rev), 200)
	deployed := request("POST", path+"/deploy", s.bootAdmin, withRevision(nil, stateRevision(t, approved)), 200)
	samples, warmup := 1, 0
	if os.Getenv("SIQ_O04_HTTP_PERF") == "1" {
		samples, warmup = 200, 5
	}
	results := map[string][]float64{}
	// Resource snapshots encompass both decision phases, revoke and warmup;
	// HTTP counts explicitly separate measured decisions from setup requests.
	readResource := func() map[string]string {
		values := map[string]string{}
		for _, name := range []string{"stat", "status", "io"} {
			if raw, err := os.ReadFile("/proc/self/" + name); err == nil {
				values[name] = string(raw)
			}
		}
		return values
	}
	before := readResource()
	measuredRequests := requests
	for i := 0; i < warmup; i++ {
		decide("allow")
	}
	for i := 0; i < samples; i++ {
		results["allow_ms"] = append(results["allow_ms"], decide("allow"))
	}
	request("POST", path+"/revoke", s.bootAdmin, withRevision(map[string]any{"actor_id": "test-admin"}, stateRevision(t, deployed)), 200)
	for i := 0; i < warmup; i++ {
		decide("deny")
	}
	for i := 0; i < samples; i++ {
		results["revoked_deny_ms"] = append(results["revoked_deny_ms"], decide("deny"))
	}
	after := readResource()
	if commands.Load() != 0 {
		t.Fatal("native HTTP journey invoked OpenShell or Docker")
	}
	receipts := request("GET", "/v1/receipts?since_seq=-1", s.bootAdmin, nil, 200)
	if receipts["verified"] != true {
		t.Fatal("receipt chain verification failed")
	}
	if os.Getenv("SIQ_O04_HTTP_PERF") == "1" {
		raw, err := json.Marshal(map[string]any{
			"scope": "service_http_fixture_native_no_agent_effects", "samples_ms": results,
			"http_requests_total": requests, "http_requests_measurement_window": requests - measuredRequests - 1,
			"expected_decisions": samples * 2, "unexpected_decisions": 0,
			"openshell_and_docker_runner_calls": commands.Load(),
			"resources_before":                  before, "resources_after": after,
		})
		if err != nil {
			t.Fatal(err)
		}
		t.Log("SIQ_O04_HTTP_RESULT=" + string(raw))
	}
}
