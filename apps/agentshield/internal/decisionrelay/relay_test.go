package decisionrelay

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (fn roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return fn(request)
}

func testConfig() Config {
	scope := strings.Repeat("2", 24)
	run := "run-001"
	return Config{
		SchemaVersion: SchemaVersion,
		Binding: Binding{
			Platform: "hermes", RuntimeIdentityID: "ri-" + strings.Repeat("0", 32),
			InstanceID: "hi-" + strings.Repeat("1", 32), AgentID: "hri-" + strings.Repeat("1", 32),
			SandboxNamespace: "siq-openshell-dev", SandboxName: "siq-analysis-run-001",
			SandboxID: "123e4567-e89b-12d3-a456-426614174000", SandboxGeneration: 2,
			Profile: "siq_analysis", ScopeID: scope, RunID: run,
			SessionNamespace: "siq:openshell:pool:" + scope + ":" + run + ":siq_analysis",
		},
		Listener: Listener{
			URL: SandboxURL, InheritedFD: 3, Transport: ListenerTransport,
			TargetContainerID: strings.Repeat("a", 64), NetworkName: "siq-openshell-dev",
			NetworkID: strings.Repeat("b", 64), GatewayIP: "172.23.0.1",
			HostAlias: "host.openshell.internal",
		},
		Upstream: LoopbackURL, AllowedRoutes: append([]string{}, AllowedRoutes...),
		MaxRequestBytes: MaxPayloadBytes, MaxResponseBytes: MaxPayloadBytes, UpstreamTimeoutMS: 5000,
	}
}

func testCredential(cfg Config) string {
	return cfg.Binding.RuntimeIdentityID + "." + strings.Repeat("a", 64)
}

func testSession(cfg Config) string {
	return cfg.Binding.SessionNamespace + ":" + strings.Repeat("b", 64)
}

func decisionBody(cfg Config) string {
	return `{"platform":"hermes","agent_id":"` + cfg.Binding.AgentID +
		`","session_id":"` + testSession(cfg) + `","tool":"read_file"}`
}

func TestRelayForwardsOnlyBoundRuntimeIdentityRequest(t *testing.T) {
	for _, cfg := range []Config{testConfig(), candidateTestConfig(), isolatedTestConfig()} {
		t.Run(cfg.SchemaVersion, func(t *testing.T) {
			called := 0
			client := &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
				called++
				if request.URL.String() != cfg.Upstream+"/v1/decide" || request.Host != strings.TrimPrefix(cfg.Upstream, "http://") {
					t.Fatalf("unexpected upstream: %s %s", request.URL, request.Host)
				}
				if request.Header.Get("Authorization") != "Bearer "+testCredential(cfg) ||
					request.Header.Get("X-Forwarded-For") != "" || request.Header.Get("Cookie") != "" {
					t.Fatal("relay did not reconstruct the minimal credential request")
				}
				return &http.Response{
					StatusCode: 200, Header: make(http.Header),
					Body: io.NopCloser(strings.NewReader(`{"action":"allow"}`)),
				}, nil
			})}
			relay, err := NewWithClient(cfg, client)
			if err != nil {
				t.Fatal(err)
			}
			request := httptest.NewRequest(http.MethodPost, LoopbackURL+"/v1/decide", strings.NewReader(decisionBody(cfg)))
			request.Header.Set("Authorization", "Bearer "+testCredential(cfg))
			request.Header.Set("Content-Type", "application/json")
			request.Header.Set("Cookie", "admin=must-not-forward")
			request.Header.Set("X-Forwarded-For", "203.0.113.10")
			response := httptest.NewRecorder()
			relay.ServeHTTP(response, request)
			if response.Code != 200 || response.Body.String() != `{"action":"allow"}` || called != 1 {
				t.Fatalf("bound request failed: status=%d body=%q calls=%d", response.Code, response.Body.String(), called)
			}
		})
	}
}

func TestRelayRuntimeEnrollmentUsesSameSessionBoundary(t *testing.T) {
	for _, cfg := range []Config{testConfig(), candidateTestConfig(), isolatedTestConfig()} {
		t.Run(cfg.SchemaVersion, func(t *testing.T) {
			called := 0
			client := &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
				called++
				return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`{}`))}, nil
			})}
			relay, _ := NewWithClient(cfg, client)
			body := `{"schema_version":"local-runtime-session-enroll/v1","session_id":"` + testSession(cfg) + `"}`
			request := httptest.NewRequest(http.MethodPost, LoopbackURL+"/v1/runtime-sessions", strings.NewReader(body))
			request.Header.Set("Authorization", "Bearer "+testCredential(cfg))
			response := httptest.NewRecorder()
			relay.ServeHTTP(response, request)
			if response.Code != 200 || called != 1 {
				t.Fatalf("enrollment rejected: status=%d calls=%d", response.Code, called)
			}
		})
	}
}

func TestRelayRejectsCrossBoundaryAndManagementRequestsBeforeUpstream(t *testing.T) {
	for _, cfg := range []Config{testConfig(), candidateTestConfig(), isolatedTestConfig()} {
		t.Run(cfg.SchemaVersion, func(t *testing.T) {
			called := 0
			client := &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
				called++
				return nil, nil
			})}
			relay, _ := NewWithClient(cfg, client)
			validBody := decisionBody(cfg)
			cases := []struct {
				name, method, target, credential, body string
			}{
				{"admin-route", http.MethodPost, LoopbackURL + "/v1/runtime-identities", testCredential(cfg), validBody},
				{"query", http.MethodPost, LoopbackURL + "/v1/decide?admin=1", testCredential(cfg), validBody},
				{"method", http.MethodGet, LoopbackURL + "/v1/decide", testCredential(cfg), validBody},
				{"other-identity", http.MethodPost, LoopbackURL + "/v1/decide", "ri-" + strings.Repeat("f", 32) + "." + strings.Repeat("a", 64), validBody},
				{"global-token", http.MethodPost, LoopbackURL + "/v1/decide", strings.Repeat("a", 64), validBody},
				{"other-platform", http.MethodPost, LoopbackURL + "/v1/decide", testCredential(cfg), strings.Replace(validBody, `"hermes"`, `"openclaw"`, 1)},
				{"other-agent", http.MethodPost, LoopbackURL + "/v1/decide", testCredential(cfg), strings.Replace(validBody, cfg.Binding.AgentID, "hri-"+strings.Repeat("f", 32), 1)},
				{"other-session", http.MethodPost, LoopbackURL + "/v1/decide", testCredential(cfg), strings.Replace(validBody, testSession(cfg), cfg.Binding.SessionNamespace+":"+strings.Repeat("c", 63)+"x", 1)},
				{"unscoped-session", http.MethodPost, LoopbackURL + "/v1/decide", testCredential(cfg), strings.Replace(validBody, testSession(cfg), "native-session", 1)},
				{"case-duplicate", http.MethodPost, LoopbackURL + "/v1/decide", testCredential(cfg), strings.TrimSuffix(validBody, "}") + `,"Session_ID":"` + testSession(cfg) + `"}`},
				{"exact-duplicate", http.MethodPost, LoopbackURL + "/v1/decide", testCredential(cfg), strings.TrimSuffix(validBody, "}") + `,"session_id":"` + testSession(cfg) + `"}`},
			}
			for _, test := range cases {
				t.Run(test.name, func(t *testing.T) {
					request := httptest.NewRequest(test.method, test.target, strings.NewReader(test.body))
					request.Header.Set("Authorization", "Bearer "+test.credential)
					response := httptest.NewRecorder()
					relay.ServeHTTP(response, request)
					if response.Code < 400 {
						t.Fatalf("unsafe request accepted: %d", response.Code)
					}
				})
			}
			if called != 0 {
				t.Fatalf("blocked requests reached upstream %d times", called)
			}
		})
	}
}

func TestRelayRejectsOversizedResponseAndRedirect(t *testing.T) {
	cfg := testConfig()
	for name, response := range map[string]*http.Response{
		"oversized": {StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(bytes.NewReader(make([]byte, MaxPayloadBytes+1)))},
		"redirect":  {StatusCode: 302, Header: http.Header{"Location": []string{"http://example.invalid/steal"}}, Body: io.NopCloser(strings.NewReader("redirect"))},
	} {
		t.Run(name, func(t *testing.T) {
			client := &http.Client{Transport: roundTripFunc(func(*http.Request) (*http.Response, error) { return response, nil })}
			relay, _ := NewWithClient(cfg, client)
			request := httptest.NewRequest(http.MethodPost, LoopbackURL+"/v1/decide", strings.NewReader(decisionBody(cfg)))
			request.Header.Set("Authorization", "Bearer "+testCredential(cfg))
			recorder := httptest.NewRecorder()
			relay.ServeHTTP(recorder, request)
			if recorder.Code != http.StatusBadGateway {
				t.Fatalf("unsafe upstream response accepted: %d", recorder.Code)
			}
		})
	}
}

func TestConfigRejectsSecretsRouteExpansionAndUnsafeFiles(t *testing.T) {
	cfg := testConfig()
	raw, _ := jsonMarshal(cfg)
	if _, err := ParseConfig(raw); err != nil {
		t.Fatal(err)
	}
	for _, mutate := range []func([]byte) []byte{
		func(value []byte) []byte {
			return bytes.Replace(value, []byte(`"schema_version"`), []byte(`"token":"secret","schema_version"`), 1)
		},
		func(value []byte) []byte {
			return bytes.Replace(value, []byte(`"schema_version"`), []byte(`"schema_version":"wrong","schema_version"`), 1)
		},
		func(value []byte) []byte {
			return bytes.Replace(value, []byte(`"/v1/decide"`), []byte(`"/v1/runtime-identities"`), 1)
		},
	} {
		if _, err := ParseConfig(mutate(raw)); err == nil {
			t.Fatal("unsafe configuration accepted")
		}
	}
	dir := t.TempDir()
	path := filepath.Join(dir, "relay.json")
	if err := os.WriteFile(path, raw, 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadConfig(path); err == nil {
		t.Fatal("world-readable configuration accepted")
	}
	if err := os.Chmod(path, 0o600); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(dir, "relay-link.json")
	if err := os.Symlink(path, link); err == nil {
		if _, err := LoadConfig(link); err == nil {
			t.Fatal("symlink configuration accepted")
		}
	}
}

func TestConfigAcceptsOnlyBoundedCanonicalBridgeListenerPorts(t *testing.T) {
	cfg := testConfig()
	for _, port := range []int{ListenerPortMin, ListenerPortMin + 1, ListenerPortMax} {
		cfg.Listener.URL = fmt.Sprintf("http://host.openshell.internal:%d", port)
		if err := cfg.Validate(); err != nil {
			t.Fatalf("bounded listener port %d rejected: %v", port, err)
		}
		actual, err := cfg.ListenerPort()
		if err != nil || actual != port {
			t.Fatalf("listener port mismatch: got=%d err=%v", actual, err)
		}
	}
	for _, endpoint := range []string{
		"http://host.openshell.internal:47610",
		"http://host.openshell.internal:47711",
		"http://127.0.0.1:47612",
		"http://user@host.openshell.internal:47612",
		"http://host.openshell.internal:47612/",
		"http://host.openshell.internal:47612?scope=other",
	} {
		cfg.Listener.URL = endpoint
		if err := cfg.Validate(); err == nil {
			t.Fatalf("unsafe listener endpoint accepted: %s", endpoint)
		}
	}
}

func TestLoadConfigFileSupportsPrivilegeDroppedDescriptor(t *testing.T) {
	cfg := testConfig()
	raw, _ := jsonMarshal(cfg)
	dir := t.TempDir()
	path := filepath.Join(dir, "relay.json")
	if err := os.WriteFile(path, raw, 0o600); err != nil {
		t.Fatal(err)
	}
	file, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	loaded, err := LoadConfigFile(file)
	if err != nil || loaded.Binding.RuntimeIdentityID != cfg.Binding.RuntimeIdentityID {
		t.Fatal("descriptor config failed", err)
	}
	if err := os.Chmod(path, 0o640); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadConfigFile(file); err == nil {
		t.Fatal("non-private descriptor config accepted")
	}
}

func jsonMarshal(value any) ([]byte, error) {
	// Kept local so tests exercise the public JSON parser instead of struct validation only.
	return json.Marshal(value)
}

func candidateTestConfig() Config {
	cfg := testConfig()
	cfg.SchemaVersion = CandidateSchemaVersion
	cfg.Binding.SandboxNamespace = "siq-openshell-scope-validation"
	cfg.Binding.SandboxName = "siq-qwen38-scoped-0123456789abcdef"
	return cfg
}

func TestCandidateConfigRequiresExactVersionNamespaceAndName(t *testing.T) {
	cfg := candidateTestConfig()
	raw, err := os.ReadFile("../../testdata/contracts/openshell-decision-relay-candidate.json")
	if err != nil {
		t.Fatal(err)
	}
	sample, err := ParseConfig(raw)
	if err != nil || sample.SchemaVersion != cfg.SchemaVersion || sample.Binding.SandboxNamespace != cfg.Binding.SandboxNamespace {
		t.Fatal("candidate contract sample rejected", err)
	}
	for name, mutate := range map[string]func(*Config){
		"legacy-version":    func(c *Config) { c.SchemaVersion = SchemaVersion },
		"unknown-version":   func(c *Config) { c.SchemaVersion = "openshell-decision-relay/v4" },
		"primary-namespace": func(c *Config) { c.Binding.SandboxNamespace = "siq-openshell-dev" },
		"unknown-namespace": func(c *Config) { c.Binding.SandboxNamespace = "arbitrary-gateway" },
		"primary-name":      func(c *Config) { c.Binding.SandboxName = "siq-analysis-run-001" },
		"invalid-nonce":     func(c *Config) { c.Binding.SandboxName += "x" },
		"wrong-network":     func(c *Config) { c.Listener.NetworkName = c.Binding.SandboxNamespace },
	} {
		t.Run(name, func(t *testing.T) {
			changed := cfg
			mutate(&changed)
			raw, err := json.Marshal(changed)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := ParseConfig(raw); err == nil {
				t.Fatal("mixed candidate binding accepted")
			}
		})
	}
}

func isolatedTestConfig() Config {
	cfg := candidateTestConfig()
	cfg.SchemaVersion, cfg.Upstream = IsolatedSchemaVersion, IsolatedLoopbackURL
	return cfg
}
func TestIsolatedCandidateRejectsDifferentUpstreamOrCompanyBinding(t *testing.T) {
	cfg := isolatedTestConfig()
	if err := cfg.Validate(); err != nil {
		t.Fatal(err)
	}
	for name, mutate := range map[string]func(*Config){
		"main-upstream":  func(c *Config) { c.Upstream = LoopbackURL },
		"other-loopback": func(c *Config) { c.Upstream = "http://127.0.0.1:47812" },
		"main-namespace": func(c *Config) { c.Binding.SandboxNamespace = "siq-openshell-dev" },
		"main-name":      func(c *Config) { c.Binding.SandboxName = "siq-analysis-run-001" },
		"old-version":    func(c *Config) { c.SchemaVersion = CandidateSchemaVersion },
	} {
		t.Run(name, func(t *testing.T) {
			changed := cfg
			mutate(&changed)
			if changed.Validate() == nil {
				t.Fatal("isolated contract drift accepted")
			}
		})
	}
}
