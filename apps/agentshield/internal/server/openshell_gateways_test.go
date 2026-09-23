package server

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/openshell"
)

func TestOpenShellGatewaysManagementBoundary(t *testing.T) {
	s, _ := newServer(t, "block")
	s.d.Openshell = openshell.New(openshell.Options{LookupEnv: func(string) (string, bool) { return "", false }, LookPath: func(string) (string, error) { return "", errors.New("not installed") }})
	service := httptest.NewServer(s.Handler())
	defer service.Close()
	call := func(method, path, credential, body string, want int) map[string]any {
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
			t.Fatalf("%s got %d want %d", path, response.StatusCode, want)
		}
		var out map[string]any
		_ = json.NewDecoder(response.Body).Decode(&out)
		return out
	}
	root := "/v1/openshell/gateways"
	call("GET", root, "", "", 401)
	call("GET", root, token, "", 403)
	cat := call("GET", root, s.bootAdmin, "", 200)
	if cat["schema_version"] != "local-openshell-gateways/v1" || cat["state"] != "unconfigured" || cat["changed_native_selection"] != false || cat["started_gateway"] != false {
		t.Fatal("invalid catalog")
	}
	call("GET", root+"?endpoint=external", s.bootAdmin, "", 400)
	call("POST", root, s.bootAdmin, "{}", 405)
	for _, endpoint := range []string{root + "/targets", root + "/inspect"} {
		call("POST", endpoint, "", "{}", 401)
		call("POST", endpoint, token, "{}", 403)
		call("GET", endpoint, s.bootAdmin, "", 405)
		for _, body := range []string{`{}`, `{} {}`, `{"schema_version":"wrong","url":"https://external"}`, strings.Repeat(" ", 8193) + `{}`} {
			call("POST", endpoint, s.bootAdmin, body, 400)
		}
	}
	selection := `{"schema_version":"local-openshell-gateway-select/v1","gateway_id":"og-` + strings.Repeat("a", 32) + `","configuration_fingerprint":"` + strings.Repeat("b", 64) + `"}`
	call("POST", root+"/targets", s.bootAdmin, selection, 409)
	call("POST", root+"/targets?name=external", s.bootAdmin, selection, 400)
	call("POST", root+"/targets", s.bootAdmin, strings.Replace(selection, `"gateway_id":`, `"gateway_id":"other","gateway_id":`, 1), 400)
	call("POST", root+"/targets", s.bootAdmin, strings.Replace(selection, `"gateway_id":`, `"Gateway_id":`, 1), 400)
	grants, err := s.d.Store.ListGrants()
	if err != nil || len(grants) != 0 {
		t.Fatal("discovery created authority")
	}
}
