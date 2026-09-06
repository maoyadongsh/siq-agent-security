package ui

import (
	"net/http"
	"net/http/httptest"
	"regexp"
	"strings"
	"testing"
)

func TestHandlerServesIndexAndRejectsMissingAssets(t *testing.T) {
	h := Handler()
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, httptest.NewRequest("GET", "/", nil))
	if rr.Code != 200 || !strings.Contains(rr.Body.String(), "siq-agent-security") {
		t.Fatalf("%d %s", rr.Code, rr.Body.String())
	}
	script := regexp.MustCompile(`/assets/index\.local-[^"]+\.js`).FindString(rr.Body.String())
	if script == "" {
		t.Fatal("index.html missing local console bundle")
	}
	js := httptest.NewRecorder()
	h.ServeHTTP(js, httptest.NewRequest("GET", script, nil))
	if js.Code != 200 || !strings.Contains(js.Body.String(), "建立管理会话") {
		t.Fatalf("embedded bundle must include pairing UI: %d", js.Code)
	}
	rr = httptest.NewRecorder()
	h.ServeHTTP(rr, httptest.NewRequest("GET", "/inventory", nil))
	if rr.Code != 200 || !strings.Contains(rr.Body.String(), "siq-agent-security") {
		t.Fatalf("SPA: %d %s", rr.Code, rr.Body.String())
	}
	rr = httptest.NewRecorder()
	h.ServeHTTP(rr, httptest.NewRequest("GET", "/nope.wasm", nil))
	if rr.Code != 404 {
		t.Fatalf("missing asset: %d", rr.Code)
	}
	rr = httptest.NewRecorder()
	h.ServeHTTP(rr, httptest.NewRequest("POST", "/", nil))
	if rr.Code != http.StatusMethodNotAllowed {
		t.Fatalf("POST: %d", rr.Code)
	}
}
