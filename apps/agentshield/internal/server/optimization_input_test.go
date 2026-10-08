package server

import (
	"io"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestAssetActionRejectsIncompleteOrOversizedDocument(t *testing.T) {
	for _, tc := range []struct {
		name, body string
		code       int
	}{
		{"partial", "{\"actor_id\":\"u\",", 400},
		{"trailing", "{\"actor_id\":\"u\"} {\"actor_id\":\"other\"}", 400},
		{"null", "null", 400},
		{"empty", "", 400},
		{"oversized", "{\"actor_id\":\"u\",\"reason\":\"" + strings.Repeat("x", 70<<10) + "\"}", 413},
	} {
		t.Run(tc.name, func(t *testing.T) {
			s, _ := newServer(t, "block")
			demo := filepath.Join(s.d.Home, ".hermes", "skills", "input-fixture")
			if err := os.MkdirAll(demo, 0700); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(demo, "SKILL.md"), []byte("---\nname: input-fixture\n---\n# Fixture\n"), 0600); err != nil {
				t.Fatal(err)
			}
			_, before := call(t, s, "GET", "/v1/assets", token, nil)
			id := ""
			for _, v := range before["assets"].([]any) {
				row := v.(map[string]any)
				if row["name"] == "input-fixture" {
					id = row["id"].(string)
				}
			}
			if id == "" {
				t.Fatal("fixture missing")
			}
			req := loopbackRequest("POST", "/v1/assets/"+id+"/confirm", nil)
			req.Body = io.NopCloser(strings.NewReader(tc.body))
			req.ContentLength = int64(len(tc.body))
			req.Header.Set("Authorization", "Bearer "+s.bootAdmin)
			response := httptest.NewRecorder()
			s.Handler().ServeHTTP(response, req)
			if response.Code != tc.code {
				t.Fatalf("status=%d body=%s", response.Code, response.Body.String())
			}
			_, after := call(t, s, "GET", "/v1/assets", token, nil)
			for _, v := range after["assets"].([]any) {
				row := v.(map[string]any)
				if row["id"] == id && row["status"] == "confirmed" {
					t.Fatal("invalid input mutated asset")
				}
			}
		})
	}
}

func TestInventoryAdmissionFailureIsNotEmptySuccess(t *testing.T) {
	s, store := newServer(t, "block")
	path := filepath.Join(store.Dir, "admissions", "broken.json")
	if err := os.WriteFile(path, []byte("{broken private-fixture"), 0600); err != nil {
		t.Fatal(err)
	}
	report, err := s.runInventory("")
	if err == nil || report != nil {
		t.Fatal("corrupt admissions were treated as empty inventory")
	}
	if strings.Contains(err.Error(), "private-fixture") || strings.Contains(err.Error(), store.Dir) {
		t.Fatal("raw failure exposed")
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if _, err := s.runInventory(""); err != nil {
		t.Fatalf("recovery failed: %v", err)
	}
}
