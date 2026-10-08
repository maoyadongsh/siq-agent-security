package server

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/httpsecurity"
)

func TestBrowserHeadersCoverResponsesAndEarlyRejections(t *testing.T) {
	s, _ := newServer(t, "block")
	for _, tc := range []struct {
		name, method, path, host, origin, remote, fetchSite string
		code                                                int
	}{
		{name: "html", path: "/", code: 200},
		{name: "spa", path: "/inventory", code: 200},
		{name: "configuration", path: "/ui-config.json", code: 200},
		{name: "health", path: "/healthz", code: 200},
		{name: "unauthorized", path: "/v1/status", code: 401},
		{name: "missing_asset", path: "/assets/not-found.js", code: 404},
		{name: "extensionless_asset", path: "/assets/not-found", code: 404},
		{name: "asset_directory", path: "/assets/", code: 404},
		{name: "method", method: "POST", path: "/", code: 405},
		{name: "bad_host", path: "/", host: "attacker.invalid:47611", code: 403},
		{name: "bad_origin", path: "/ui-config.json", origin: "https://attacker.invalid", code: 403},
		{name: "null_origin", path: "/v1/status", origin: "null", code: 403},
		{name: "wrong_port_origin", path: "/", origin: "http://127.0.0.1:47612", code: 403},
		{name: "cross_site_write", method: "POST", path: "/v1/session/connect/request", fetchSite: "cross-site", code: 403},
		{name: "non_loopback", path: "/", remote: "192.0.2.1:5555", code: 403},
	} {
		t.Run(tc.name, func(t *testing.T) {
			method := tc.method
			if method == "" {
				method = http.MethodGet
			}
			r := loopbackRequest(method, tc.path, nil)
			if tc.host != "" {
				r.Host = tc.host
			}
			if tc.remote != "" {
				r.RemoteAddr = tc.remote
			}
			r.Header.Set("Origin", tc.origin)
			r.Header.Set("Sec-Fetch-Site", tc.fetchSite)
			w := httptest.NewRecorder()
			s.Handler().ServeHTTP(w, r)
			if w.Code != tc.code {
				t.Fatalf("status %d, want %d", w.Code, tc.code)
			}
			if w.Header().Get("Content-Security-Policy") != httpsecurity.CSP ||
				w.Header().Get("X-Frame-Options") != "DENY" || w.Header().Get("X-Content-Type-Options") != "nosniff" ||
				w.Header().Get("Cache-Control") != "no-store" {
				t.Fatalf("missing response protection: %v", w.Header())
			}
			if w.Header().Get("Access-Control-Allow-Origin") != "" || w.Header().Get("Strict-Transport-Security") != "" {
				t.Fatal("local HTTP must not broaden CORS or enable HSTS")
			}
		})
	}
	// A same-origin browser request with an actual paired administrator still works.
	r := loopbackRequest("GET", "/v1/status", nil)
	r.Header.Set("Origin", "http://127.0.0.1:47611")
	r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r)
	if w.Code != 200 || !strings.HasPrefix(w.Header().Get("Content-Type"), "application/json") {
		t.Fatal("same-origin paired management failed")
	}
}
