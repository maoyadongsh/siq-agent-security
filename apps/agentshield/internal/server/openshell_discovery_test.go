package server

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestOpenShellDiscoveryHTTPAuthorizationAndInput(t *testing.T) {
	s, _ := newServer(t, "block")
	service := httptest.NewServer(s.Handler())
	defer service.Close()
	call := func(method, path, credential, body string, want int) {
		t.Helper()
		req, _ := http.NewRequest(method, service.URL+path, strings.NewReader(body))
		req.Host = "127.0.0.1:47611"
		if credential != "" {
			req.Header.Set("Authorization", "Bearer "+credential)
		}
		req.Header.Set("Content-Type", "application/json")
		response, err := service.Client().Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer response.Body.Close()
		if response.StatusCode != want {
			t.Fatalf("%s %s got %d want %d", method, path, response.StatusCode, want)
		}
		if want == 200 {
			var catalog map[string]any
			if json.NewDecoder(response.Body).Decode(&catalog) != nil || catalog["schema_version"] != "local-openshell-targets/v1" || catalog["started_gateway"] != false {
				t.Fatal("invalid discovery contract")
			}
		}
	}
	call("GET", "/v1/openshell/targets", "", "", 401)
	call("GET", "/v1/openshell/targets", token, "", 403)
	call("GET", "/v1/openshell/targets", s.bootAdmin, "", 200)
	call("GET", "/v1/openshell/targets?unknown=1", s.bootAdmin, "", 400)
	call("POST", "/v1/openshell/targets", s.bootAdmin, "", 405)
	call("POST", "/v1/openshell/targets/inspect", token, "{}", 403)
	for _, body := range []string{`{} {}`, `{"schema_version":"local-openshell-target-inspect/v1","command":"exec"}`, `{"schema_version":"unknown"}`} {
		call("POST", "/v1/openshell/targets/inspect", s.bootAdmin, body, 400)
	}
	call("POST", "/v1/openshell/targets/inspect", s.bootAdmin, `{"schema_version":"local-openshell-target-inspect/v1","name":"--help","sandbox_id":"bad","endpoint_fingerprint":"bad"}`, 409)
	grants, err := s.d.Store.ListGrants()
	if err != nil || len(grants) != 0 {
		t.Fatal("discovery created authority", err)
	}
}
