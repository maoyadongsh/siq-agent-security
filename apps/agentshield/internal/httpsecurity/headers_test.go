package httpsecurity

import (
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)

func TestLocalAndEnterpriseBrowserPoliciesAgree(t *testing.T) {
	data, err := os.ReadFile("../../../web/security-headers.inc")
	if err != nil {
		t.Fatal(err)
	}
	w := httptest.NewRecorder()
	Apply(w)
	for _, name := range []string{"Content-Security-Policy", "X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Permissions-Policy"} {
		value := w.Header().Get(name)
		if value == "" || !strings.Contains(string(data), "add_header "+name+" \""+value+"\" always;") {
			t.Fatalf("browser policy differs between local and enterprise: %s", name)
		}
	}
	if w.Header().Get("Cache-Control") != "no-store" || w.Header().Get("Strict-Transport-Security") != "" {
		t.Fatal("HTTP defaults must not cache private state or enable HSTS")
	}
}
