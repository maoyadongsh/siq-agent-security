package server

// UP07 state-compatibility write-entrypoint proofs. Each failure class (future
// format, corrupt marker, broken stored signature, stale revision) is exercised
// through real HTTP write entrypoints against a fixture server whose state dir
// is tampered in place; the tamper happens only inside t.TempDir-owned state.
// The invariant under test: the gate refuses the write AND mutates nothing —
// no directory creation, no migration, no quarantine lock, no history rewrite,
// and no "repair" of the marker back to the current version.

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/skillimport"
	"siq-agent-security/apps/agentshield/internal/state"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

// up07Snapshot hashes every file in the state dir so any write — even one byte
// anywhere — is detected between phases.
func up07Snapshot(t *testing.T, dir string) map[string]string {
	t.Helper()
	snap := map[string]string{}
	err := filepath.WalkDir(dir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(dir, path)
		if err != nil {
			return err
		}
		if d.IsDir() {
			snap[rel+"/"] = ""
			return nil
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		sum := sha256.Sum256(raw)
		snap[rel] = hex.EncodeToString(sum[:])
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return snap
}

func up07AssertUnchanged(t *testing.T, dir string, before map[string]string) {
	t.Helper()
	after := up07Snapshot(t, dir)
	if len(after) != len(before) {
		for k := range before {
			if _, ok := after[k]; !ok {
				t.Fatalf("state entry disappeared during refused write: %s", k)
			}
		}
		for k := range after {
			if _, ok := before[k]; !ok {
				t.Fatalf("refused write created state entry: %s", k)
			}
		}
		t.Fatalf("state entry count changed: %d -> %d", len(before), len(after))
	}
	for k, want := range before {
		if after[k] != want {
			t.Fatalf("refused write mutated state entry %s", k)
		}
	}
}

// up07MarkerPath returns the format marker and asserts it exists.
func up07MarkerPath(t *testing.T, dir string) string {
	t.Helper()
	p := filepath.Join(dir, state.StateFormatMarkerName)
	if _, err := os.Lstat(p); err != nil {
		t.Fatal(err)
	}
	return p
}

// up07EnsureMarker writes a valid v1 format marker (the shape
// publishInitialStateFormat emits for an already-initialized store) if Open's
// legacy unversioned state has none yet, so the tamper helpers below always
// operate on a marker the real gate would read and accept.
func up07EnsureMarker(t *testing.T, dir string) {
	t.Helper()
	p := filepath.Join(dir, state.StateFormatMarkerName)
	if _, err := os.Lstat(p); err == nil {
		return
	}
	marker := state.StateFormatMarker{Schema: state.StateFormatSchema, ProgramVersion: "up07-fixture", FormatVersion: 1, PublishedAt: "2026-09-16T00:00:00Z"}
	raw, err := json.Marshal(marker)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, append(raw, '\n'), 0o600); err != nil {
		t.Fatal(err)
	}
}

// up07FutureMarker rewrites the marker to a version beyond MaxSupportedFormat.
func up07FutureMarker(t *testing.T, dir string) []byte {
	t.Helper()
	p := up07MarkerPath(t, dir)
	raw, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	var m state.StateFormatMarker
	if err := json.Unmarshal(raw, &m); err != nil {
		t.Fatal(err)
	}
	m.FormatVersion = state.MaxSupportedFormat + 997
	future, err := json.Marshal(m)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, append(future, '\n'), 0o600); err != nil {
		t.Fatal(err)
	}
	return append(future, '\n')
}

// up07HealthyFixture builds a server and proves, on the pristine state, that
// every request later fired under the broken gate actually writes (2xx). The
// snapshot returned is taken AFTER those healthy writes so the comparison below
// isolates the refused attempts.
func up07HealthyFixture(t *testing.T) (*Server, *state.Store, map[string]skillimport.CreateRequest) {
	t.Helper()
	s, st := newServer(t, "block")
	up07EnsureMarker(t, st.Dir)

	source := t.TempDir()
	if err := os.WriteFile(filepath.Join(source, "SKILL.md"), []byte("---\nname: up07-gate\ndescription: Gate probe.\n---\nRead a report.\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	imports := map[string]skillimport.CreateRequest{
		"gate": {SchemaVersion: "local-skill-import-create/v1", ImportID: "si-" + strings.Repeat("7", 32), SourceKind: "local_dir", Path: source, ActorID: "fixture-human"},
	}
	code, out := call(t, s, "POST", "/v1/skill-imports", token, imports["gate"])
	if code != 201 {
		t.Fatalf("healthy skill-import must write: %d %v", code, out)
	}
	code, issued := call(t, s, "POST", "/v1/intents", s.bootAdmin, apiIntent())
	if code != 201 {
		t.Fatalf("healthy intent issue must write: %d %v", code, issued)
	}
	code, admitted := call(t, s, "POST", "/v1/admit", token, map[string]any{"path": filepath.Join("..", "admission", "testdata", "skills", "benign", "pure-doc")})
	if code != 200 {
		t.Fatalf("healthy admit must write: %d %v", code, admitted)
	}
	admID := admitted["admission"].(map[string]any)["admission_id"].(string)
	code, g := call(t, s, "POST", "/v1/grants", token, map[string]any{"admission_id": admID, "platform": "hermes", "subject_id": "up07-gate"})
	if code != 200 {
		t.Fatalf("healthy grant must write: %d %v", code, g)
	}
	return s, st, imports
}

// up07FireRefusedGateWrites replays the same write entrypoints once the marker
// is broken; the request-time gate must refuse every one of them.
func up07FireRefusedGateWrites(t *testing.T, s *Server, imports map[string]skillimport.CreateRequest, phase string) {
	t.Helper()
	flights := []struct {
		name string
		run  func() (int, map[string]any)
	}{
		{"POST /v1/skill-imports", func() (int, map[string]any) { return call(t, s, "POST", "/v1/skill-imports", token, imports["gate"]) }},
		{"POST /v1/intents", func() (int, map[string]any) { return call(t, s, "POST", "/v1/intents", s.bootAdmin, apiIntent()) }},
		{"POST /v1/admit", func() (int, map[string]any) {
			return call(t, s, "POST", "/v1/admit", token, map[string]any{"path": filepath.Join("..", "admission", "testdata", "skills", "benign", "pure-doc")})
		}},
		{"POST /v1/intent-bindings", func() (int, map[string]any) {
			return call(t, s, "POST", "/v1/intent-bindings", s.bootAdmin, map[string]any{"platform": "hermes", "session_id": "up07", "agent_id": "a-up07", "intent_id": "int-up07"})
		}},
		{"POST /v1/raw-task-content/activation", func() (int, map[string]any) {
			return call(t, s, "POST", "/v1/raw-task-content/activation", token, map[string]any{"enabled": true})
		}},
	}
	for _, f := range flights {
		code, out := f.run()
		if code/100 == 2 {
			t.Fatalf("%s: write accepted while state gate broken (%s): %d %v", f.name, phase, code, out)
		}
		if code != 503 {
			t.Fatalf("%s: expected the state gate's 503 state_incompatible (%s), got %d %v", f.name, phase, code, out)
		}
		if out["error"] != "state_incompatible" {
			t.Fatalf("%s: unexpected gate error body (%s): %v", f.name, phase, out)
		}
	}
}

func TestUP07FutureFormatBlocksWriteEntrypointsAndMutatesNothing(t *testing.T) {
	s, st, imports := up07HealthyFixture(t)
	future := up07FutureMarker(t, st.Dir)

	// Baseline is taken AFTER the tamper: everything the refused writes do (or
	// fail to do) is measured against the deliberately-broken state itself.
	snap := up07Snapshot(t, st.Dir)
	up07FireRefusedGateWrites(t, s, imports, "future")

	// No quarantine lock, no backup/migration dirs, no history rewrite: the
	// state dir is byte-identical to the healthy snapshot.
	up07AssertUnchanged(t, st.Dir, snap)

	// The marker must still say "future": the gate refuses, it never "repairs"
	// the state to the current version behind the operator's back.
	repaired, err := os.ReadFile(up07MarkerPath(t, st.Dir))
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(repaired, future) {
		t.Fatal("state format marker was rewritten during refused writes (repair-on-refuse is forbidden)")
	}
}

func TestUP07CorruptMarkerBlocksWriteEntrypointsAndMutatesNothing(t *testing.T) {
	s, st, imports := up07HealthyFixture(t)

	if err := os.WriteFile(up07MarkerPath(t, st.Dir), []byte("{not-json"), 0o600); err != nil {
		t.Fatal(err)
	}
	snap := up07Snapshot(t, st.Dir)
	up07FireRefusedGateWrites(t, s, imports, "corrupt")
	up07AssertUnchanged(t, st.Dir, snap)
}

// TestUP07BrokenStoredSignatureRefusedWithoutRewrite covers the second UP07
// failure class at entrypoint level: a stored signed document whose signature
// no longer verifies must make every operation on it refuse, and the stored
// (broken) document must be left untouched — no rewrite, no re-sign, no repair.
func TestUP07BrokenStoredSignatureRefusedWithoutRewrite(t *testing.T) {
	s, _ := newServer(t, "block")
	source := t.TempDir()
	if err := os.WriteFile(filepath.Join(source, "SKILL.md"), []byte("---\nname: up07-sig\ndescription: Signature probe.\n---\nRead a report.\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	req := skillimport.CreateRequest{SchemaVersion: "local-skill-import-create/v1", ImportID: "si-" + strings.Repeat("9", 32), SourceKind: "local_dir", Path: source, ActorID: "fixture-human"}
	code, first := call(t, s, "POST", "/v1/skill-imports", token, req)
	if code != 201 {
		t.Fatalf("setup import: %d %v", code, first)
	}

	recordPath := filepath.Join(s.d.Store.Dir, "skill-imports", "records", req.ImportID+".json")
	raw, err := os.ReadFile(recordPath)
	if err != nil {
		t.Fatal(err)
	}
	sigField := []byte(`"signature":"`)
	idx := bytes.Index(raw, sigField)
	if idx < 0 {
		t.Fatal("stored import record has no signature field")
	}
	tampered := append([]byte(nil), raw...)
	// Keep valid JSON and hex so rejection exercises signature verification,
	// not malformed JSON or an outer analysis digest mismatch.
	pos := idx + len(sigField)
	if tampered[pos] == '0' {
		tampered[pos] = '1'
	} else {
		tampered[pos] = '0'
	}
	if err := os.WriteFile(recordPath, tampered, 0o600); err != nil {
		t.Fatal(err)
	}

	snapshot := up07Snapshot(t, s.d.Store.Dir)
	for _, attempt := range []struct {
		name string
		run  func() (int, map[string]any)
	}{
		{"GET /v1/skill-imports/<id>", func() (int, map[string]any) { return call(t, s, "GET", "/v1/skill-imports/"+req.ImportID, token, nil) }},
		{"POST /v1/skill-imports (reuse)", func() (int, map[string]any) { return call(t, s, "POST", "/v1/skill-imports", token, req) }},
	} {
		code, out := attempt.run()
		if code != 409 || out["error"] != "skill_import_changed" {
			t.Fatalf("%s: accepted while stored signature broken: %d %v", attempt.name, code, out)
		}
	}

	up07AssertUnchanged(t, s.d.Store.Dir, snapshot)
	now, err := os.ReadFile(recordPath)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(now, tampered) {
		t.Fatal("refused operation rewrote the stored document (signature repair is forbidden)")
	}
}

// TestUP07StaleRevisionWriteRefusedLeavesGrantUntouched covers the third UP07
// failure class: a write carrying a stale/wrong revision must be refused with
// the contract conflict and must not advance or rewrite the guarded state.
func TestUP07StaleRevisionWriteRefusedLeavesGrantUntouched(t *testing.T) {
	s, _ := newServer(t, "block")
	code, admitted := call(t, s, "POST", "/v1/admit", token, map[string]any{"path": filepath.Join("..", "admission", "testdata", "skills", "benign", "pure-doc")})
	if code != 200 {
		t.Fatalf("admit: %d %v", code, admitted)
	}
	admID := admitted["admission"].(map[string]any)["admission_id"].(string)
	code, g := call(t, s, "POST", "/v1/grants", token, map[string]any{"admission_id": admID, "platform": "hermes", "subject_id": "up07-rev"})
	if code != 200 {
		t.Fatalf("grant: %d %v", code, g)
	}
	gid := g["grant"].(map[string]any)["grant_id"].(string)
	rev := stateRevision(t, g)

	// A fresh grant's revision may start at 0; any value different from the
	// current one exercises the same stale-revision guard.
	stale := rev + 1000
	code, out := call(t, s, "POST", "/v1/grants/"+gid+"/challenge", token, withRevision(nil, stale))
	if code != 409 {
		t.Fatalf("stale revision must be a 409 revision conflict, got %d %v", code, out)
	}

	// The refused attempt consumed nothing: a correctly-revisioned request must
	// still match — if the refusal had advanced the revision, this would 409.
	code, ch := call(t, s, "POST", "/v1/grants/"+gid+"/challenge", token, withRevision(nil, rev))
	if code != 200 {
		t.Fatalf("correct-revision challenge after refused stale write: %d %v", code, ch)
	}
}

// TestUP07RealBinaryRefusesFutureStateBeforeSideEffects is the real-binary leg
// (marked separately from component fault injection): the compiled agentshield
// command gates ALL non-diagnostic commands on state compatibility before any
// side effect, including commands that would create keys or touch services.
func TestUP07RealBinaryRefusesFutureStateBeforeSideEffects(t *testing.T) {
	if testing.Short() {
		t.Skip("real-binary leg skipped in -short")
	}
	bin := filepath.Join(t.TempDir(), "agentshield")
	build := exec.Command("go", "build", "-o", bin, "./cmd/agentshield")
	build.Dir = filepath.Join("..", "..")
	if out, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build cmd/agentshield: %v\n%s", err, out)
	}

	stateDir := t.TempDir()
	if _, err := state.Open(stateDir); err != nil {
		t.Fatal(err)
	}
	up07EnsureMarker(t, stateDir)
	future := up07FutureMarker(t, stateDir)
	snap := up07Snapshot(t, stateDir)

	run := func(name string, args ...string) (int, string) {
		cmd := exec.Command(bin, append([]string{name}, args...)...)
		// Isolated environment: the state dir env pins DefaultDir away from the
		// operator's real state; HOME is a throwaway so no user file is touched.
		cmd.Env = append(os.Environ(),
			"SIQ_AGENT_SECURITY_STATE_DIR="+stateDir,
			"HOME="+t.TempDir(),
		)
		out, err := cmd.CombinedOutput()
		code := 0
		if err != nil {
			code = 1
			if ee, ok := err.(*exec.ExitError); ok {
				code = ee.ExitCode()
			}
		}
		return code, string(out)
	}

	// Gated write command: refused before any side effect.
	code, out := run("admit")
	if code == 0 {
		t.Fatalf("gated command accepted future state:\n%s", out)
	}
	t.Logf("admit exit=%d output=%q", code, out)
	if !strings.Contains(out, stateformat.RecoveryMessage()) {
		t.Fatalf("gated command error lacks recovery guidance:\n%s", out)
	}
	up07AssertUnchanged(t, stateDir, snap)
	repaired, rerr := os.ReadFile(up07MarkerPath(t, stateDir))
	if rerr != nil {
		t.Fatal(rerr)
	}
	if !bytes.Equal(repaired, future) {
		t.Fatal("real binary rewrote the marker during the refused command")
	}

	// Diagnostic exemption: state-status is read-only by contract and must run
	// so the operator can diagnose; it must still not mutate the state.
	code, out = run("state-status")
	if code != 0 {
		t.Fatalf("state-status (read-only diagnostic) must run on future state: %d\n%s", code, out)
	}
	up07AssertUnchanged(t, stateDir, snap)
}
