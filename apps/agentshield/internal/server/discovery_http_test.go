package server

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestDiscoveryContractFixtures(t *testing.T) {
	s, _ := newServer(t, "block")
	for _, tc := range []struct {
		name, method, path string
		body               any
	}{
		{"status", "GET", "/v1/discovery", nil},
		{"preview", "POST", "/v1/discovery/preview", map[string]any{}},
	} {
		response := sessionRequest(t, s, tc.method, tc.path, tc.body, s.bootAdmin, nil, nil)
		if response.Code != 200 {
			t.Fatalf("%s: %d", tc.name, response.Code)
		}
		var body any
		if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil {
			t.Fatal(err)
		}
		got, _ := json.MarshalIndent(body, "", "  ")
		path := filepath.Join("..", "..", "testdata", "contracts", "discovery-"+tc.name+".json")
		if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
			if err := os.WriteFile(path, append(got, '\n'), 0o644); err != nil {
				t.Fatal(err)
			}
		}
		expected, err := os.ReadFile(path)
		if err != nil || !bytes.Equal(bytes.TrimSpace(expected), got) {
			t.Fatalf("%s discovery contract changed", tc.name)
		}
	}
}

func waitDiscovery(t *testing.T, s *Server) map[string]any {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		response := sessionRequest(t, s, "GET", "/v1/discovery", nil, s.bootAdmin, nil, nil)
		if response.Code != 200 {
			t.Fatalf("discovery status: %d", response.Code)
		}
		body := sessionBody(t, response)
		job := body["run"].(map[string]any)
		if job["state"] != "running" {
			return job
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("discovery did not finish")
	return nil
}

func TestExplicitDiscoveryRefreshesCacheAndPersistsScope(t *testing.T) {
	s, st := newServer(t, "block")
	if err := s.Refresh(""); err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "SKILL.md"), []byte("---\nname: added-after-cache\n---\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	input := map[string]any{"skill_dir": root}
	preview := sessionRequest(t, s, "POST", "/v1/discovery/preview", input, s.bootAdmin, nil, nil)
	if preview.Code != 200 {
		t.Fatalf("preview: %d", preview.Code)
	}
	before, revision, err := st.LoadDiscoveryRoots()
	if err != nil || revision != -1 || len(before.SkillDirs) != 0 {
		t.Fatal("preview persisted scope")
	}
	for i := 0; i < 2; i++ {
		response := sessionRequest(t, s, "POST", "/v1/discovery/scan", input, s.bootAdmin, nil, nil)
		if response.Code != 202 {
			t.Fatalf("start: %d", response.Code)
		}
		job := waitDiscovery(t, s)
		if job["state"] != "succeeded" || job["skill_count"] != float64(1) {
			t.Fatalf("scan outcome: %v", job)
		}
		code, assets := call(t, s, "GET", "/v1/assets", s.bootAdmin, nil)
		if code != 200 || len(assets["assets"].([]any)) != 1 {
			t.Fatal("scan did not refresh cached assets or created duplicates")
		}
	}
	roots, revision, err := st.LoadDiscoveryRoots()
	if err != nil || len(roots.SkillDirs) != 1 || roots.SkillDirs[0] != root || revision != 0 {
		t.Fatal("manual scope was lost or unnecessarily versioned")
	}
	restarted, err := New(s.d)
	if err != nil {
		t.Fatal(err)
	}
	if err := restarted.Refresh(""); err != nil {
		t.Fatal(err)
	}
	if got := len(restarted.proj.snap.Report.Candidates); got != 1 {
		t.Fatalf("restart lost scope: %d", got)
	}
}

func TestDiscoveryRejectsDecisionCredentialAndInvalidScope(t *testing.T) {
	s, _ := newServer(t, "block")
	for _, path := range []string{"/v1/discovery", "/v1/discovery/preview", "/v1/discovery/scan"} {
		response := sessionRequest(t, s, "POST", path, map[string]any{}, token, nil, nil)
		if response.Code != 403 {
			t.Fatalf("decision credential reached %s", path)
		}
	}
	for _, input := range []map[string]any{{"skill_dir": "relative/path"}, {"project_dir": "https://example.com/project"}, {"skill_dir": filepath.Join(t.TempDir(), "missing")}} {
		response := sessionRequest(t, s, "POST", "/v1/discovery/scan", input, s.bootAdmin, nil, nil)
		if response.Code != 400 {
			t.Fatalf("invalid scope accepted: %d", response.Code)
		}
	}
}

func TestDiscoveryReportsPartialAndRejectsConcurrentScan(t *testing.T) {
	s, _ := newServer(t, "block")
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "SKILL.md"), []byte("---\nname: good\n---\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	badConfig := filepath.Join(s.d.Home, ".openclaw", "openclaw.json")
	if err := os.MkdirAll(badConfig, 0o700); err != nil {
		t.Fatal(err)
	} // directory cannot be read as platform config
	s.refreshMu.Lock()
	response := sessionRequest(t, s, "POST", "/v1/discovery/scan", map[string]any{"skill_dir": root}, s.bootAdmin, nil, nil)
	if response.Code != 202 {
		s.refreshMu.Unlock()
		t.Fatalf("start: %d", response.Code)
	}
	conflict := sessionRequest(t, s, "POST", "/v1/discovery/scan", map[string]any{}, s.bootAdmin, nil, nil)
	s.refreshMu.Unlock()
	if conflict.Code != 409 {
		t.Fatal("concurrent discovery accepted")
	}
	job := waitDiscovery(t, s)
	if job["state"] != "partial" || job["issue_count"].(float64) < 1 || job["skill_count"] != float64(1) {
		t.Fatalf("partial run hidden: %v", job)
	}
}
