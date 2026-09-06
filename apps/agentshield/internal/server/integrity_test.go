package server

import (
	"os"
	"path/filepath"
	"testing"
)

func TestCorruptStateCannotBecomeSuccessfulEmptyViews(t *testing.T) {
	for _, kind := range []string{"grants", "assets", "findings", "admissions"} {
		t.Run(kind+"/stale_after_ok", func(t *testing.T) {
			s, st := newServer(t, "block")
			code, body := call(t, s, "GET", "/v1/assets", token, nil)
			if code != 200 {
				t.Fatalf("legitimate empty state: %d %v", code, body)
			}
			proj, _ := body["projection"].(map[string]any)
			if proj["health"] != "ok" {
				t.Fatalf("want health ok, got %v", proj)
			}
			rev := proj["revision"]
			if err := os.WriteFile(filepath.Join(st.Dir, kind, "broken.0.json"), []byte("null"), 0o600); err != nil {
				t.Fatal(err)
			}
			if err := s.Refresh(""); err == nil {
				t.Fatal("refresh must fail on corrupt latest record")
			}
			for _, endpoint := range []string{"/v1/assets", "/v1/permissions", "/v1/findings", "/v1/export"} {
				code, body := call(t, s, "GET", endpoint, token, nil)
				if code != 200 {
					t.Errorf("%s: prior projection must remain readable as stale, got %d %v", endpoint, code, body)
					continue
				}
				if endpoint == "/v1/export" {
					continue // export body is the bundle, not envelope
				}
				p, _ := body["projection"].(map[string]any)
				if p["health"] != "stale" {
					t.Errorf("%s: want health=stale after failed refresh, got %v", endpoint, p)
				}
				if p["revision"] != rev {
					t.Errorf("%s: revision must not advance on failed refresh: %v vs %v", endpoint, p["revision"], rev)
				}
				if p["last_error"] == nil || p["last_error"] == "" {
					t.Errorf("%s: last_error must surface (not conceal corruption)", endpoint)
				}
			}
		})
		t.Run(kind+"/unavailable_without_prior", func(t *testing.T) {
			s, st := newServer(t, "block")
			if err := os.WriteFile(filepath.Join(st.Dir, kind, "broken.0.json"), []byte("null"), 0o600); err != nil {
				t.Fatal(err)
			}
			for _, endpoint := range []string{"/v1/assets", "/v1/permissions", "/v1/findings", "/v1/export"} {
				if code, body := call(t, s, "GET", endpoint, token, nil); code != 500 {
					t.Errorf("%s concealed corrupt %s as status %d: %v", endpoint, kind, code, body)
				}
			}
		})
	}
}
