package ui

import (
	"net/http"
	"net/http/httptest"
	"regexp"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/httpsecurity"
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

func TestStaticAssetHeadersAndCaching(t *testing.T) {
	h := Handler()
	index := httptest.NewRecorder()
	h.ServeHTTP(index, httptest.NewRequest("GET", "/", nil))
	script := regexp.MustCompile(`/assets/index\.local-[^"]+\.js`).FindString(index.Body.String())
	style := regexp.MustCompile(`/assets/index-[^"]+\.css`).FindString(index.Body.String())
	if script == "" || style == "" {
		t.Fatal("embedded entry must reference real JS and CSS")
	}
	for _, tc := range []struct {
		method, path, rangeHeader, contentType string
		code                                   int
	}{
		{"GET", script, "", "javascript", 200},
		{"HEAD", script, "", "javascript", 200},
		{"GET", script, "bytes=0-15", "javascript", 206},
		{"GET", style, "", "text/css", 200},
	} {
		r := httptest.NewRequest(tc.method, tc.path, nil)
		r.Header.Set("Range", tc.rangeHeader)
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != tc.code || !strings.Contains(w.Header().Get("Content-Type"), tc.contentType) ||
			w.Header().Get("Content-Security-Policy") != httpsecurity.CSP ||
			w.Header().Get("Cache-Control") != "public, max-age=31536000, immutable" {
			t.Fatalf("%s %s: %d %v", tc.method, tc.path, w.Code, w.Header())
		}
		if tc.method == "HEAD" && w.Body.Len() != 0 {
			t.Fatal("HEAD returned a body")
		}
	}
	for _, path := range []string{"/assets", "/assets/", "/assets/absent", "/assets/absent.html", "/assets/absent.js"} {
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest("GET", path, nil))
		if w.Code != 404 || w.Header().Get("Cache-Control") != "no-store" || w.Header().Get("X-Content-Type-Options") != "nosniff" {
			t.Fatalf("missing assets must not return/cache HTML: %s %d %v", path, w.Code, w.Header())
		}
	}
}
