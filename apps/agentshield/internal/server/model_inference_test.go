package server

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestModelInferenceLifecycle(t *testing.T) {
	s, _ := newServer(t, "block")
	s.d.Home = t.TempDir()
	s.d.HermesHome = ""
	root := filepath.Join(s.d.Home, ".hermes")
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	var calls atomic.Int32
	var drift atomic.Bool
	release := make(chan struct{})
	model := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.URL.Path != "/v1/chat/completions" || r.Header.Get("Authorization") != "Bearer SYNTHETIC_PRIVATE_KEY" {
			t.Error("unexpected model request")
		}
		var body struct {
			Model    string
			Messages []struct{ Role, Content string }
		}
		if json.NewDecoder(r.Body).Decode(&body) != nil || len(body.Messages) != 1 {
			w.WriteHeader(400)
			return
		}
		<-release
		if drift.Load() {
			_ = os.WriteFile(filepath.Join(root, "config.yaml"), []byte("model:\n  default: different\n"), 0600)
		}
		marker := strings.TrimSuffix(strings.TrimPrefix(body.Messages[0].Content, "This is a connection test. Reply with exactly "), " and no other text.")
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{"model": body.Model, "choices": []any{map[string]any{"finish_reason": "stop", "message": map[string]string{"role": "assistant", "content": marker}}}})
	}))
	defer model.Close()
	defer func() {
		select {
		case <-release:
		default:
			close(release)
		}
	}()
	config := "model:\n  default: fixture-model\n  provider: custom:fixture\n  api_mode: openai_chat\n  base_url: " + model.URL + "/v1\n  api_key: SYNTHETIC_PRIVATE_KEY\n"
	if err := os.WriteFile(filepath.Join(root, "config.yaml"), []byte(config), 0600); err != nil {
		t.Fatal(err)
	}
	call := func(method, path, auth, body string, want int) map[string]any {
		t.Helper()
		req := httptest.NewRequest(method, "http://127.0.0.1:47611"+path, strings.NewReader(body))
		if auth != "" {
			req.Header.Set("Authorization", "Bearer "+auth)
		}
		req.RemoteAddr = "127.0.0.1:55000"
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, req)
		if w.Code != want {
			t.Fatalf("%s status %d want %d", path, w.Code, want)
		}
		if strings.Contains(w.Body.String(), "SYNTHETIC_PRIVATE_KEY") || strings.Contains(w.Body.String(), "SIQ_MODEL_TEST_") {
			t.Fatal("private key or model content escaped")
		}
		var value map[string]any
		if err := json.Unmarshal(w.Body.Bytes(), &value); err != nil {
			t.Fatal(err)
		}
		return value
	}
	catalog := call("GET", "/v1/model-connections", s.bootAdmin, "", 200)
	item := catalog["items"].([]any)[0].(map[string]any)
	request := map[string]any{"schema_version": "local-model-inference-create/v1", "request_id": "mt-" + strings.Repeat("1", 32), "model_id": item["id"], "fingerprint": item["fingerprint"], "confirm_test": true}
	encode := func() string { raw, _ := json.Marshal(request); return string(raw) }
	path := "/v1/model-inference-tests"
	query := path + "?model_id=" + item["id"].(string)
	call("POST", path, "", encode(), 401)
	call("POST", path, token, encode(), 403)
	call("GET", query, token, "", 403)
	if call("GET", query, s.bootAdmin, "", 200)["record"] != nil {
		t.Fatal("unexpected history")
	}
	for _, raw := range []string{`{}`, encode() + `{}`, strings.Replace(encode(), `"confirm_test":true`, `"confirm_test":false,"confirm_test":true`, 1), strings.Replace(encode(), `"confirm_test":true`, `"confirm_test":false`, 1), strings.Replace(encode(), `"confirm_test":true`, `"confirm_test":true,"prompt":"private"`, 1), strings.Repeat(" ", 4097) + encode()} {
		call("POST", path, s.bootAdmin, raw, 400)
	}
	call("GET", query+"&model_id="+item["id"].(string), s.bootAdmin, "", 400)
	call("POST", path+"?url=external", s.bootAdmin, encode(), 400)
	if calls.Load() != 0 {
		t.Fatal("invalid request called model")
	}
	running := call("POST", path, s.bootAdmin, encode(), 202)
	if running["status"] != "running" || running["inference_verified"] != false || running["business_data_sent"] != false {
		t.Fatal("invalid running state")
	}
	if call("POST", path, s.bootAdmin, encode(), 200)["request_id"] != request["request_id"] {
		t.Fatal("duplicate identity lost")
	}
	request["fingerprint"] = strings.Repeat("f", 64)
	call("POST", path, s.bootAdmin, encode(), 409)
	request["fingerprint"] = item["fingerprint"]
	request["request_id"] = "mt-" + strings.Repeat("2", 32)
	call("POST", path, s.bootAdmin, encode(), 409)
	request["request_id"] = running["request_id"]
	close(release)
	wait := func(want string) map[string]any {
		t.Helper()
		deadline := time.Now().Add(5 * time.Second)
		for time.Now().Before(deadline) {
			latest := call("GET", query, s.bootAdmin, "", 200)
			record := latest["record"].(map[string]any)
			if record["status"] != "running" {
				if record["status"] != want {
					t.Fatalf("status %v want %s", record["status"], want)
				}
				return latest
			}
			time.Sleep(10 * time.Millisecond)
		}
		t.Fatal("inference did not finish")
		return nil
	}
	latest := wait("passed")
	finished := latest["record"].(map[string]any)
	if calls.Load() != 1 || finished["inference_verified"] != true {
		t.Fatal("duplicate call or false result")
	}
	if call("POST", path, s.bootAdmin, encode(), 200)["status"] != "passed" || calls.Load() != 1 {
		t.Fatal("finished request replayed")
	}
	if os.Getenv("SIQ_UPDATE_MODEL_FIXTURES") == "1" {
		for name, value := range map[string]any{"local-model-inference-create": request, "local-model-inference-record": finished, "local-model-inference-latest": latest} {
			raw, _ := json.MarshalIndent(value, "", "  ")
			if err := os.WriteFile(filepath.Join("..", "..", "testdata", "contracts", name+".json"), append(raw, '\n'), 0600); err != nil {
				t.Fatal(err)
			}
		}
	}
	drift.Store(true)
	request["request_id"] = "mt-" + strings.Repeat("2", 32)
	call("POST", path, s.bootAdmin, encode(), 202)
	wait("configuration_changed")
	request["request_id"] = "mt-" + strings.Repeat("3", 32)
	call("POST", path, s.bootAdmin, encode(), 409)
	if calls.Load() != 2 {
		t.Fatal("stale configuration reached model")
	}
	// Capacity rejects new IDs without evicting old idempotency records.
	s.modelTestMu.Lock()
	for len(s.modelTests) < 1024 {
		s.modelTests[fmt.Sprintf("fixture-%d", len(s.modelTests))] = modelInferenceRecord{}
	}
	s.modelTestMu.Unlock()
	call("POST", path, s.bootAdmin, encode(), 409)
	request["request_id"] = running["request_id"]
	if call("POST", path, s.bootAdmin, encode(), 200)["status"] != "passed" || calls.Load() != 2 {
		t.Fatal("history evicted")
	}
}
