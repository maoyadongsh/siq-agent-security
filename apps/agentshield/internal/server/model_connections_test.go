package server

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestModelConnectionsRealHTTPAndConfigChanges(t *testing.T) {
	s, _ := newServer(t, "block")
	home := t.TempDir()
	s.d.Home = home
	s.d.HermesHome = ""
	root := filepath.Join(home, ".hermes")
	if os.Mkdir(root, 0700) != nil {
		t.Fatal("fixture")
	}
	calls := 0
	changed := false
	model := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if r.URL.Path != "/v1/models" || r.Header.Get("Authorization") != "Bearer SYNTHETIC_PRIVATE_KEY" {
			t.Error("wrong destination or credential")
		}
		if changed {
			_ = os.WriteFile(filepath.Join(root, "config.yaml"), []byte("model:\n  default: different\n"), 0600)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":[{"id":"fixture-model"}]}`))
	}))
	defer model.Close()
	config := "model:\n  default: fixture-model\n  provider: custom:fixture\n  base_url: " + model.URL + "/v1\n  api_key: SYNTHETIC_PRIVATE_KEY\n"
	if os.WriteFile(filepath.Join(root, "config.yaml"), []byte(config), 0600) != nil {
		t.Fatal("fixture")
	}
	service := httptest.NewServer(s.Handler())
	defer service.Close()
	call := func(method, path, credential, body string, want int) map[string]any {
		t.Helper()
		req, _ := http.NewRequest(method, service.URL+path, strings.NewReader(body))
		req.Host = "127.0.0.1:47611"
		req.Header.Set("Content-Type", "application/json")
		if credential != "" {
			req.Header.Set("Authorization", "Bearer "+credential)
		}
		r, err := service.Client().Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer r.Body.Close()
		if r.StatusCode != want {
			t.Fatalf("%s status %d want %d", path, r.StatusCode, want)
		}
		var out map[string]any
		if json.NewDecoder(r.Body).Decode(&out) != nil {
			t.Fatal("response")
		}
		raw, _ := json.Marshal(out)
		if strings.Contains(string(raw), "SYNTHETIC_PRIVATE_KEY") {
			t.Fatal("key escaped")
		}
		return out
	}
	call("GET", "/v1/model-connections", "", "", 401)
	call("GET", "/v1/model-connections", token, "", 403)
	catalog := call("GET", "/v1/model-connections", s.bootAdmin, "", 200)
	if calls != 0 {
		t.Fatal("discovery used network")
	}
	item := catalog["items"].([]any)[0].(map[string]any)
	request := map[string]any{"schema_version": "local-model-connection-check/v1", "id": item["id"], "fingerprint": item["fingerprint"]}
	raw, _ := json.Marshal(request)
	call("POST", "/v1/model-connections/check", token, string(raw), 403)
	result := call("POST", "/v1/model-connections/check", s.bootAdmin, string(raw), 200)
	if result["status"] != "listed" || result["inference_verified"] != false || calls != 1 {
		t.Fatal("model check did not reach service")
	}
	for _, body := range []string{`{} {}`, `{"schema_version":"local-model-connection-check/v1","endpoint":"http://169.254.169.254"}`, `{"schema_version":"unknown"}`} {
		call("POST", "/v1/model-connections/check", s.bootAdmin, body, 400)
	}
	if os.Getenv("SIQ_UPDATE_MODEL_FIXTURES") == "1" {
		for name, value := range map[string]any{"local-model-connections": catalog, "local-model-connection-check": request, "local-model-connection-result": result} {
			raw, _ := json.MarshalIndent(value, "", "  ")
			if os.WriteFile(filepath.Join("..", "..", "testdata", "contracts", name+".json"), append(raw, '\n'), 0600) != nil {
				t.Fatal("fixture write")
			}
		}
	}
	changed = true
	call("POST", "/v1/model-connections/check", s.bootAdmin, string(raw), 409)
	if calls != 2 {
		t.Fatal("inflight drift not tested")
	}
	call("POST", "/v1/model-connections/check", s.bootAdmin, string(raw), 409)
	if calls != 2 {
		t.Fatal("stale selection reached external service")
	}
}
