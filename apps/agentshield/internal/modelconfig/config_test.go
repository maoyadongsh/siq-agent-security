package modelconfig

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func sourceFixture(t *testing.T, platform, raw string) Source {
	t.Helper()
	root := t.TempDir()
	name := "config.yaml"
	if platform == "openclaw" {
		name = "openclaw.json"
	}
	if os.WriteFile(filepath.Join(root, name), []byte(raw), 0600) != nil {
		t.Fatal("fixture")
	}
	return Source{ID: "hi-11111111111111111111111111111111", Platform: platform, Name: "work", Root: root}
}
func TestExplicitHermesProjectionAndCredentialDrift(t *testing.T) {
	t.Setenv("SIQ_TEST_MODEL_KEY", "")
	s := sourceFixture(t, "hermes", "model:\n  default: fixture-model\n  provider: custom:fixture\n  base_url: http://127.0.0.1:8000/v1\n  key_env: SIQ_TEST_MODEL_KEY\n  temperature: 0.7\nother:\n  default: WRONG\n")
	a := Discover(s)[0]
	if a.Item.Credential != "missing" || a.Item.CanCheck {
		t.Fatal("missing credential passed")
	}
	if os.WriteFile(filepath.Join(s.Root, ".env"), []byte("SIQ_TEST_MODEL_KEY='fixture-private-key'\n"), 0600) != nil {
		t.Fatal("fixture")
	}
	b := Discover(s)[0]
	if !b.Item.CanCheck || b.Key != "fixture-private-key" || b.Item.Model != "fixture-model" || b.Item.Fingerprint == a.Item.Fingerprint {
		t.Fatal("explicit configuration not bound")
	}
	raw, _ := json.Marshal(b.Item)
	if strings.Contains(string(raw), "fixture-private-key") || strings.Contains(string(raw), "SIQ_TEST_MODEL_KEY") {
		t.Fatal("credential escaped")
	}
	t.Setenv("SIQ_TEST_MODEL_KEY", "different-private-key")
	c := Discover(s)[0]
	if c.Item.Fingerprint == b.Item.Fingerprint || c.Key != "different-private-key" {
		t.Fatal("environment change not detected")
	}
	if _, err := hermesModel([]byte("model:\n  default: good\n  default: evil\n")); err == nil {
		t.Fatal("duplicate accepted")
	}
	for _, raw := range []string{"model: *inherited\n", "model:\n  default: *inherited\n", "model:\n  <<: *inherited\n", "model:\n  nested:\n    default: bad\n", "model:\n  default: good\nmodel:\n  default: bad\n"} {
		if _, err := hermesModel([]byte(raw)); err == nil {
			t.Fatal("ambiguous declaration accepted")
		}
	}
	projected, err := hermesModel([]byte("custom_providers:\n- name: one\n  api: https://one.example\n- name: two\n  api: https://two.example\nmodel:\n  default: selected\n"))
	if err != nil || str(projected, "default") != "selected" {
		t.Fatal("native indentless provider list hid model declaration")
	}
}

func TestCredentialReferencesAreExplicit(t *testing.T) {
	t.Setenv("SIQ_TEST_REF_KEY", "synthetic-ref-key")
	key, state := credential(t.TempDir(), map[string]any{"apiKey": map[string]any{"source": "env", "provider": "default", "id": "SIQ_TEST_REF_KEY"}}, false)
	if key != "synthetic-ref-key" || state != "present" {
		t.Fatal("explicit env reference unavailable")
	}
	for _, cfg := range []map[string]any{{"apiKey": map[string]any{"source": "exec", "provider": "default", "id": "command"}}, {"apiKey": "${SIQ_TEST_REF_KEY}"}} {
		if _, state := credential(t.TempDir(), cfg, false); state != "unsupported" {
			t.Fatal("dynamic credential resolved")
		}
	}
	if _, state := credential(t.TempDir(), map[string]any{"api_key": "inline", "key_env": "SIQ_TEST_REF_KEY"}, true); state != "unsupported" {
		t.Fatal("ambiguous credential precedence guessed")
	}
}
func TestOpenClawRolesAndPrivateFields(t *testing.T) {
	s := sourceFixture(t, "openclaw", `{"agents":{"defaults":{"model":{"primary":"local/model-a","fallbacks":["cloud/model-b","local/model-a"]}}},"models":{"providers":{"local":{"baseUrl":"http://127.0.0.1:8000/v1","api":"openai-completions","apiKey":"LOCAL-SECRET"},"cloud":{"baseUrl":"https://example.com/v1","api":"openai-completions","apiKey":"CLOUD-SECRET"}}}}`)
	rows := Discover(s)
	if len(rows) != 2 || rows[0].Item.Role != "primary" || rows[1].Item.Role != "fallback" || !rows[1].Item.CanCheck {
		t.Fatal("roles not preserved")
	}
	for _, row := range rows {
		raw, _ := json.Marshal(row.Item)
		if strings.Contains(string(raw), "SECRET") {
			t.Fatal("private fields escaped")
		}
	}
	if uniqueJSON([]byte(`{"agents":{},"agents":{}}`)) || uniqueJSON([]byte(`{} {}`)) {
		t.Fatal("ambiguous JSON accepted")
	}
	if os.WriteFile(filepath.Join(s.Root, "openclaw.json"), []byte(`{"$include":"elsewhere.json"}`), 0600) != nil {
		t.Fatal("fixture")
	}
	if Discover(s)[0].Item.CanCheck {
		t.Fatal("include guessed")
	}
}
func TestUnsafeSourcesAndEndpoints(t *testing.T) {
	for _, u := range []string{"http://example.com/v1", "http://169.254.169.254/v1", "https://[fe80::1]/v1", "http://100.100.100.200/v1", "https://user:secret@example.com/v1", "https://example.com/v1?api_key=PRIVATE", "file:///tmp/key"} {
		if _, err := endpoint(u); err == nil {
			t.Fatal("unsafe destination accepted")
		}
	}
	s := sourceFixture(t, "hermes", "model:\n  default: good\n")
	p := filepath.Join(s.Root, "config.yaml")
	if os.Rename(p, p+".bak") != nil {
		t.Fatal("fixture")
	}
	if err := os.Symlink(p+".bak", p); err != nil {
		t.Skip("symlinks unavailable")
	}
	if Discover(s)[0].Item.State != "unreadable_config" {
		t.Fatal("symlink followed")
	}
}
func TestCheckModelListingAndFailureCategories(t *testing.T) {
	status := 200
	body := `{"data":[{"id":"model-a"}]}`
	calls := 0
	wantURI := "/v1/models"
	service := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if r.Method != "GET" || r.URL.Path != "/v1/models" || r.RequestURI != wantURI || r.Header.Get("Authorization") != "Bearer synthetic-key" {
			t.Error("wrong probe request")
		}
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Location", "http://169.254.169.254/")
		w.WriteHeader(status)
		_, _ = w.Write([]byte(body))
	}))
	defer service.Close()
	target := Target{Item: Item{ID: "mc-" + strings.Repeat("a", 32), Fingerprint: strings.Repeat("b", 64), Model: "model-a", CanCheck: true}, URL: service.URL + "/v1", Key: "synthetic-key"}
	for _, tc := range []struct {
		code       int
		body, want string
	}{{200, body, "listed"}, {200, `{"data":[]}`, "not_listed"}, {200, `{"data":[{"id":"model-a"},{"id":"model-a"}]}`, "unsupported_response"}, {200, `{"data":null}`, "unsupported_response"}, {200, `{"data":[],"data":[{"id":"model-a"}]}`, "unsupported_response"}, {401, `PRIVATE`, "auth_failed"}, {403, `PRIVATE`, "auth_failed"}, {429, `PRIVATE`, "rate_limited"}, {404, `PRIVATE`, "unsupported_response"}, {302, `PRIVATE`, "unsupported_response"}, {503, `PRIVATE`, "service_error"}} {
		status, body = tc.code, tc.body
		before := calls
		r := Check(context.Background(), target)
		if r.Status != tc.want || r.Inference || calls != before+1 {
			t.Fatalf("probe category or redirect error: %s", r.Status)
		}
	}
	wantURI = "/%76%31/models"
	target.URL = service.URL + "/%76%31"
	status = 200
	body = `{"data":[{"id":"model-a"}]}`
	if Check(context.Background(), target).Status != "listed" {
		t.Fatal("encoded configured route changed")
	}
	service.Close()
	if Check(context.Background(), target).Status != "unreachable" {
		t.Fatal("closed service accepted")
	}
}
