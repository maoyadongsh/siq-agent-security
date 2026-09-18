package server

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime/pprof"
	"runtime/trace"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
)

// Opt-in attribution only: the fixture setup is excluded from the profile.
// This does not replace or relax TestWorkBuddyWindowsFreshSessionHTTPBudget.
func TestWorkBuddyWindowsFreshEnrollmentProfile(t *testing.T) {
	dir := os.Getenv("AGENTSHIELD_ENROLLMENT_PROFILE_DIR")
	if dir == "" {
		t.Skip("explicit local diagnostic output directory required")
	}
	f := newWindowsAuthorityHTTPFixtureForPlatform(t, "block", false, "workbuddy")
	server := httptest.NewServer(f.s.Handler())
	defer server.Close()
	create := func(name string) *os.File {
		t.Helper()
		file, err := os.OpenFile(filepath.Join(dir, name), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = file.Close() })
		return file
	}
	cpu, execution := create("enrollment.cpu.pprof"), create("enrollment.trace")
	session, _ := runtimeidentity.WorkBuddySessionID("fresh-profile-session")
	raw, _ := json.Marshal(map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": session})
	req, err := http.NewRequest("POST", server.URL+"/v1/runtime-sessions", bytes.NewReader(raw))
	if err != nil {
		t.Fatal(err)
	}
	req.Host = "127.0.0.1:47611"
	req.Header.Set("Authorization", "Bearer "+f.credential)
	req.Header.Set("Content-Type", "application/json")
	if err := pprof.StartCPUProfile(cpu); err != nil {
		t.Fatal(err)
	}
	defer pprof.StopCPUProfile()
	if err := trace.Start(execution); err != nil {
		t.Fatal(err)
	}
	defer trace.Stop()
	started := time.Now()
	resp, err := server.Client().Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil || resp.StatusCode != 200 {
		t.Fatalf("profile enrollment: status=%d error=%v", resp.StatusCode, err)
	}
	t.Logf("diagnostic enrollment elapsed=%s (profile overhead included; not a budget acceptance)", time.Since(started).Round(time.Millisecond))
}
