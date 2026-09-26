// Native acceptance tests for the Hermes connector (CL-03-HERMES-NATIVE).
//
// Unlike the existing function-level unit tests (hermes_test.go,
// consent_scope_test.go, profile_identity_test.go), every test in this file
// builds the real connector binary from the CURRENT worktree sources into an
// isolated temp dir and drives it as a child process over the NDJSON
// connector-protocol.v1 wire (`<binary> --serve`). No mock dispatch, no
// canned responses, no direct calls into collectOp.
//
// Independence rules honored here:
//   - expected candidate IDs / evidence IDs / content hashes are computed
//     from the contract formulas in packages/contracts/hermes-profile-origin.v2.md
//     using only the standard library (crypto/sha256) — never via production
//     helpers such as protocol.ContentHash, computeCursor or collectOp;
//   - all profiles, configs, secrets and escape targets are synthetic fixtures
//     generated under the test temp dir; the child's HOME is redirected there;
//   - the child process gets a minimal environment whitelist (HOME +
//     SIQ_CONNECTOR_*), never the developer's real env, credentials or proxy
//     settings;
//   - every child is reaped by t.Cleanup (close stdin -> wait -> kill).
package main

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"
)

const nativeRPCTimeout = 30 * time.Second

// --- binary build (current worktree, isolated output) ----------------------

var (
	nativeBinaryOnce sync.Once
	nativeBinaryPath string
	nativeBinaryErr  error
)

// nativeBinary builds the connector from the current (possibly uncommitted)
// worktree sources into a fresh temp dir. The checked-in
// connectors/hermes/hermes binary is never touched or executed.
func nativeBinary(t *testing.T) string {
	t.Helper()
	nativeBinaryOnce.Do(func() {
		dir, err := os.MkdirTemp("", "hermes-native-bin-")
		if err != nil {
			nativeBinaryErr = err
			return
		}
		nativeBinaryPath = filepath.Join(dir, "hermes-connector-native")
		cmd := exec.Command("go", "build", "-o", nativeBinaryPath, ".")
		out, err := cmd.CombinedOutput()
		if err != nil {
			nativeBinaryErr = fmt.Errorf("native build failed: %v\n%s", err, out)
		}
	})
	if nativeBinaryErr != nil {
		t.Fatal(nativeBinaryErr)
	}
	return nativeBinaryPath
}

func TestMain(m *testing.M) {
	code := m.Run()
	if nativeBinaryPath != "" {
		os.RemoveAll(filepath.Dir(nativeBinaryPath))
	}
	os.Exit(code)
}

// --- child process session -------------------------------------------------

type cappedBuffer struct {
	mu       sync.Mutex
	buf      []byte
	max      int
	overflow bool
}

func (b *cappedBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if room := b.max - len(b.buf); room > 0 {
		b.buf = append(b.buf, p[:min(room, len(p))]...)
	} else {
		b.overflow = true
	}
	return len(p), nil
}

func (b *cappedBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return string(b.buf)
}

type nativeSession struct {
	cmd    *exec.Cmd
	stdin  io.WriteCloser
	stdout *bufio.Reader
	stderr *cappedBuffer
	lines  []string // every raw stdout line, for purity / leak assertions
}

// startNativeSession launches `<binary> --serve` with a minimal env
// whitelist (contract §1: SIQ_CONNECTOR_NAME/VERSION/TIMEOUT_MS; HOME points
// at the test temp dir). No real user config, credentials or proxy variables
// are inherited.
func startNativeSession(t *testing.T, home string) *nativeSession {
	t.Helper()
	cmd := exec.Command(nativeBinary(t), "--serve")
	cmd.Env = []string{
		"HOME=" + home,
		"SIQ_CONNECTOR_NAME=hermes",
		"SIQ_CONNECTOR_VERSION=native-acceptance",
		"SIQ_CONNECTOR_TIMEOUT_MS=30000",
	}
	stdin, err := cmd.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	stdoutPipe, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	s := &nativeSession{
		cmd:    cmd,
		stdin:  stdin,
		stdout: bufio.NewReader(stdoutPipe),
		stderr: &cappedBuffer{max: 1 << 20},
	}
	cmd.Stderr = s.stderr
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { s.shutdown() })
	return s
}

// shutdown closes stdin, gives the child a grace period to exit, then kills
// and reaps it. Runs on every test cleanup so failures/timeouts never leak
// processes.
func (s *nativeSession) shutdown() {
	_ = s.stdin.Close()
	done := make(chan error, 1)
	go func() { done <- s.cmd.Wait() }()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		_ = s.cmd.Process.Kill()
		<-done
	}
}

// rpc writes one NDJSON request and reads exactly one response line. It
// enforces protocol purity: the line must be a single valid JSON protocol
// message whose id matches the request (contract §1/§2).
func (s *nativeSession) rpc(t *testing.T, id, op string, params any) (map[string]any, string) {
	t.Helper()
	var rawParams json.RawMessage
	switch p := params.(type) {
	case nil:
		rawParams = json.RawMessage(`{}`)
	case json.RawMessage:
		rawParams = p
	default:
		b, err := json.Marshal(p)
		if err != nil {
			t.Fatal(err)
		}
		rawParams = b
	}
	reqLine, err := json.Marshal(map[string]any{"id": id, "op": op, "params": rawParams})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.stdin.Write(append(reqLine, '\n')); err != nil {
		t.Fatalf("request %s: write: %v", id, err)
	}
	type readResult struct {
		line string
		err  error
	}
	ch := make(chan readResult, 1)
	go func() {
		line, err := s.stdout.ReadString('\n')
		ch <- readResult{line, err}
	}()
	var line string
	select {
	case r := <-ch:
		if r.err != nil {
			t.Fatalf("request %s op=%s: read: %v (stderr: %s)", id, op, r.err, s.stderr.String())
		}
		line = strings.TrimSuffix(r.line, "\n")
	case <-time.After(nativeRPCTimeout):
		_ = s.cmd.Process.Kill()
		t.Fatalf("request %s op=%s: timeout after %s", id, op, nativeRPCTimeout)
	}
	if line == "" {
		t.Fatalf("request %s op=%s: empty stdout line violates NDJSON protocol", id, op)
	}
	var resp map[string]any
	if err := json.Unmarshal([]byte(line), &resp); err != nil {
		t.Fatalf("request %s op=%s: stdout line is not protocol JSON: %v", id, op, err)
	}
	if resp["id"] != id {
		t.Fatalf("response id %v does not match request id %q", resp["id"], id)
	}
	if _, ok := resp["ok"].(bool); !ok {
		t.Fatalf("response %s missing boolean ok field", id)
	}
	s.lines = append(s.lines, line)
	return resp, line
}

func (s *nativeSession) collect(t *testing.T, id string, roots, include []string, maxFiles, maxBytes int64) (map[string]any, string) {
	t.Helper()
	resp, raw := s.rpc(t, id, "collect", map[string]any{
		"plan": map[string]any{
			"scope":  map[string]any{"roots": roots, "include": include},
			"limits": map[string]any{"max_files": maxFiles, "max_bytes": maxBytes},
		},
	})
	return rpcOK(t, resp), raw
}

// allOutput returns everything the child ever printed (stdout protocol lines
// + captured stderr) for secret/marker leak assertions.
func (s *nativeSession) allOutput() string {
	return strings.Join(s.lines, "\n") + "\n--- stderr ---\n" + s.stderr.String()
}

// --- response helpers ------------------------------------------------------

func rpcOK(t *testing.T, resp map[string]any) map[string]any {
	t.Helper()
	if resp["ok"] != true {
		t.Fatalf("request failed: %v", resp["error"])
	}
	result, ok := resp["result"].(map[string]any)
	if !ok {
		t.Fatalf("response missing result object: %v", resp)
	}
	return result
}

func rpcError(t *testing.T, resp map[string]any) map[string]any {
	t.Helper()
	if resp["ok"] != false {
		t.Fatalf("expected failure response, got ok=true result=%v", resp["result"])
	}
	e, ok := resp["error"].(map[string]any)
	if !ok {
		t.Fatalf("failure response missing error object: %v", resp)
	}
	return e
}

func mapOf(t *testing.T, v any, what string) map[string]any {
	t.Helper()
	m, ok := v.(map[string]any)
	if !ok {
		t.Fatalf("%s: expected object, got %T", what, v)
	}
	return m
}

func listOf(t *testing.T, m map[string]any, key string) []any {
	t.Helper()
	v, ok := m[key]
	if !ok {
		t.Fatalf("result missing %q", key)
	}
	l, ok := v.([]any)
	if !ok {
		t.Fatalf("result.%s: expected list, got %T", key, v)
	}
	return l
}

func strOf(t *testing.T, m map[string]any, key string) string {
	t.Helper()
	v, ok := m[key]
	if !ok {
		t.Fatalf("object missing %q", key)
	}
	s, ok := v.(string)
	if !ok {
		t.Fatalf("%s: expected string, got %T", key, v)
	}
	return s
}

// --- independent expectation oracles (contract formulas, stdlib only) ------

func sha256Hex(b []byte) string {
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}

// canonicalFixtureDir enforces that the hashed lexical path (contract v2:
// digest input is the profile's cleaned absolute path) is not skewed by
// symlinked temp-dir components on this machine.
func canonicalFixtureDir(t *testing.T, dir string) string {
	t.Helper()
	abs, err := filepath.Abs(dir)
	if err != nil {
		t.Fatal(err)
	}
	clean := filepath.Clean(abs)
	resolved, err := filepath.EvalSymlinks(clean)
	if err != nil {
		t.Fatal(err)
	}
	if resolved != clean {
		t.Fatalf("fixture path %q not canonical (resolves to %q)", clean, resolved)
	}
	return clean
}

func wantCandidateID(profileDir string) string { return "hermes:v2:" + sha256Hex([]byte(profileDir)) }
func wantSourceLocator(profileDir string) string {
	return "hermes://profiles/v2/" + sha256Hex([]byte(profileDir))
}
func wantEvidenceID(profileDir, name string) string {
	return "ev:hermes:v2:" + sha256Hex([]byte(profileDir+"\x00"+name))
}
func wantEnvEvidenceHash(name string, size int64) string {
	return sha256Hex([]byte(fmt.Sprintf("env-file:%s:%d", name, size)))
}
func wantFileHash(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return sha256Hex(data)
}

func writeFixtureFile(t *testing.T, path, content string, perm os.FileMode) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), perm); err != nil {
		t.Fatal(err)
	}
}

// --- contract shape guards -------------------------------------------------

var candidateAllowedKeys = map[string]bool{
	"candidate_id": true, "source_type": true, "source_locator": true,
	"discovered_at": true, "name": true, "framework": true,
	"artifact_digest": true, "attributes": true, "evidence_ids": true,
	"confidence": true, "status": true,
}
var candidateRequiredKeys = []string{
	"candidate_id", "source_type", "source_locator", "discovered_at",
	"name", "framework", "evidence_ids",
}

var evidenceAllowedKeys = map[string]bool{
	"evidence_id": true, "tenant_id": true, "environment_id": true,
	"source_type": true, "source_locator": true, "subject_ref": true,
	"observed_at": true, "collected_at": true, "collector_id": true,
	"connector_version": true, "content_hash": true, "redaction_profile": true,
	"classification": true, "payload_ref": true, "signature": true,
	"signing_schema": true, "expires_at": true,
}
var evidenceRequiredKeys = []string{
	"evidence_id", "source_type", "source_locator", "observed_at",
	"collected_at", "collector_id", "connector_version", "content_hash",
	"redaction_profile", "classification", "signature",
}

func checkRFC3339(t *testing.T, what, value string) {
	t.Helper()
	if _, err := time.Parse(time.RFC3339, value); err != nil {
		t.Errorf("%s %q is not RFC3339: %v", what, value, err)
	}
}

// checkBatchShape validates the wire shape against candidate.schema.json /
// evidence.schema.json (additionalProperties:false contracts).
func checkBatchShape(t *testing.T, batch map[string]any) {
	t.Helper()
	for _, c := range listOf(t, batch, "candidates") {
		cm := mapOf(t, c, "candidate")
		for k := range cm {
			if !candidateAllowedKeys[k] {
				t.Errorf("candidate carries key %q outside candidate.schema.json", k)
			}
		}
		for _, k := range candidateRequiredKeys {
			if _, ok := cm[k]; !ok {
				t.Errorf("candidate missing required key %q", k)
			}
		}
		checkRFC3339(t, "candidate.discovered_at", strOf(t, cm, "discovered_at"))
	}
	for _, e := range listOf(t, batch, "evidence") {
		em := mapOf(t, e, "evidence")
		for k := range em {
			if !evidenceAllowedKeys[k] {
				t.Errorf("evidence carries key %q outside evidence.schema.json", k)
			}
		}
		for _, k := range evidenceRequiredKeys {
			if _, ok := em[k]; !ok {
				t.Errorf("evidence missing required key %q", k)
			}
		}
		if v, ok := em["payload_ref"]; ok && v != nil {
			t.Errorf("evidence %s: payload_ref must stay null/absent (content never leaves the connector)", strOf(t, em, "evidence_id"))
		}
		// Contract §5: collector_id/signature are filled by the Edge at
		// packaging time; the connector must emit them empty.
		if strOf(t, em, "collector_id") != "" || strOf(t, em, "signature") != "" {
			t.Errorf("evidence %s: collector_id/signature must be empty on the wire", strOf(t, em, "evidence_id"))
		}
		checkRFC3339(t, "evidence.observed_at", strOf(t, em, "observed_at"))
		checkRFC3339(t, "evidence.collected_at", strOf(t, em, "collected_at"))
	}
}

// indexCandidates maps candidate_id -> candidate object.
func indexCandidates(t *testing.T, batch map[string]any) map[string]map[string]any {
	t.Helper()
	out := map[string]map[string]any{}
	for _, c := range listOf(t, batch, "candidates") {
		cm := mapOf(t, c, "candidate")
		id := strOf(t, cm, "candidate_id")
		if _, dup := out[id]; dup {
			t.Fatalf("duplicate candidate_id %s", id)
		}
		out[id] = cm
	}
	return out
}

func indexEvidence(t *testing.T, batch map[string]any) map[string]map[string]any {
	t.Helper()
	out := map[string]map[string]any{}
	for _, e := range listOf(t, batch, "evidence") {
		em := mapOf(t, e, "evidence")
		id := strOf(t, em, "evidence_id")
		if _, dup := out[id]; dup {
			t.Fatalf("duplicate evidence_id %s", id)
		}
		out[id] = em
	}
	return out
}

func factsOf(batch map[string]any) []any {
	if v, ok := batch["permission_facts"]; ok {
		if l, ok := v.([]any); ok {
			return l
		}
	}
	return nil
}

// batchFingerprint captures identity-relevant fields while ignoring
// wall-clock timestamps (discovered_at/observed_at/collected_at).
type batchFingerprint struct {
	candidates map[string]string // candidate_id -> source_locator
	evidence   map[string]string // evidence_id -> content_hash
	facts      []string          // subject|resource|state|effect|evidence_ids
	cursor     string
}

func fingerprintBatch(t *testing.T, batch map[string]any) batchFingerprint {
	t.Helper()
	fp := batchFingerprint{candidates: map[string]string{}, evidence: map[string]string{}}
	for _, c := range listOf(t, batch, "candidates") {
		cm := mapOf(t, c, "candidate")
		fp.candidates[strOf(t, cm, "candidate_id")] = strOf(t, cm, "source_locator")
	}
	for _, e := range listOf(t, batch, "evidence") {
		em := mapOf(t, e, "evidence")
		fp.evidence[strOf(t, em, "evidence_id")] = strOf(t, em, "content_hash")
	}
	for _, f := range factsOf(batch) {
		fm := mapOf(t, f, "permission_fact")
		sub := mapOf(t, fm["subject"], "permission_fact.subject")
		res := mapOf(t, fm["resource"], "permission_fact.resource")
		fp.facts = append(fp.facts, fmt.Sprintf("%s|%s|%s|%s|%v",
			strOf(t, sub, "id"), strOf(t, res, "value"),
			strOf(t, fm, "state"), strOf(t, fm, "effect"), fm["evidence_ids"]))
	}
	sort.Strings(fp.facts)
	if c, ok := batch["cursor"]; ok {
		fp.cursor, _ = c.(string)
	}
	return fp
}

// checkReferenceIntegrity enforces the batch rule: every evidence must be
// referenced by at least one candidate of the same batch, and every candidate
// reference must resolve.
func checkReferenceIntegrity(t *testing.T, batch map[string]any) {
	t.Helper()
	evs := indexEvidence(t, batch)
	referenced := map[string]bool{}
	for _, c := range listOf(t, batch, "candidates") {
		cm := mapOf(t, c, "candidate")
		for _, id := range listOf(t, cm, "evidence_ids") {
			s, ok := id.(string)
			if !ok {
				t.Fatalf("candidate evidence_ids must be strings")
			}
			referenced[s] = true
			if _, ok := evs[s]; !ok {
				t.Errorf("candidate %s references missing evidence %s", strOf(t, cm, "candidate_id"), s)
			}
		}
	}
	for id := range evs {
		if !referenced[id] {
			t.Errorf("orphan evidence %s not referenced by any candidate", id)
		}
	}
}

func attributesOf(t *testing.T, cand map[string]any) map[string]any {
	t.Helper()
	v, ok := cand["attributes"]
	if !ok || v == nil {
		return map[string]any{}
	}
	return mapOf(t, v, "candidate.attributes")
}

// --- A. protocol & capabilities ---------------------------------------------

func TestNativeDescribeSequentialAndProtocolPurity(t *testing.T) {
	home := t.TempDir()
	// A default-location profile exists but is never in scope for this test.
	writeFixtureFile(t, filepath.Join(home, ".hermes", "profiles", "decoy", "config.yaml"),
		"model:\n  default: decoy-model\n", 0o600)
	s := startNativeSession(t, home)

	resp, _ := s.rpc(t, "a-01", "describe", nil)
	caps := rpcOK(t, resp)
	if strOf(t, caps, "version") == "" {
		t.Error("describe: version must be non-empty")
	}
	objects := listOf(t, caps, "objects")
	if len(objects) != 1 || objects[0] != "hermes_profile" {
		t.Errorf("describe: objects=%v, want [hermes_profile]", objects)
	}
	perms := listOf(t, caps, "required_permissions")
	wantPerm := "read:" + filepath.Join(home, ".hermes", "profiles")
	if len(perms) != 1 || perms[0] != wantPerm {
		t.Errorf("describe: required_permissions=%v, want [%q]", perms, wantPerm)
	}
	cats := listOf(t, caps, "data_categories")
	if len(cats) != 2 || cats[0] != "config_names" || cats[1] != "tool_names" {
		t.Errorf("describe: data_categories=%v", cats)
	}
	if caps["max_output_bytes"] != float64(8*1024*1024) {
		t.Errorf("describe: max_output_bytes=%v, want 8388608", caps["max_output_bytes"])
	}
	if caps["network_access"] != false {
		t.Errorf("describe: network_access=%v, want false", caps["network_access"])
	}

	// One process keeps serving a sequence of requests.
	resp, _ = s.rpc(t, "a-02", "health", nil)
	health := rpcOK(t, resp)
	if strOf(t, health, "version") == "" {
		t.Error("health: version must be non-empty")
	}
	if deps := listOf(t, health, "dependencies"); len(deps) == 0 {
		t.Error("health: dependencies must be non-empty")
	}
	resp, _ = s.rpc(t, "a-03", "checkpoint", nil)
	pre := rpcOK(t, resp)
	if c, ok := pre["cursor"]; ok && c != "" {
		t.Errorf("checkpoint before any collect must be empty, got %v", c)
	}

	// Unsupported ops and malformed params fail per existing error semantics:
	// ok=false, no crash, no fabricated empty success.
	resp, _ = s.rpc(t, "a-04", "obliterate", nil)
	if e := rpcError(t, resp); e["code"] != "unsupported" {
		t.Errorf("unknown op: code=%v, want unsupported", e["code"])
	}
	resp, _ = s.rpc(t, "a-05", "collect", json.RawMessage(`"a-string"`))
	if e := rpcError(t, resp); e["code"] != "bad_request" {
		t.Errorf("malformed collect params: code=%v, want bad_request", e["code"])
	}

	// The process survived the failures and still answers.
	resp, _ = s.rpc(t, "a-06", "describe", nil)
	rpcOK(t, resp)

	// A clean session writes nothing to stderr; stdout carried only protocol
	// JSON (enforced per-line inside rpc).
	if got := s.stderr.String(); got != "" {
		t.Errorf("clean session must not write to stderr, got %q", got)
	}
}

func TestNativeValidateScopeRejections(t *testing.T) {
	home := t.TempDir()
	base := canonicalFixtureDir(t, t.TempDir())
	profileDir := filepath.Join(base, "profiles", "p1")
	writeFixtureFile(t, filepath.Join(profileDir, "config.yaml"), "model:\n  default: m\n", 0o600)

	s := startNativeSession(t, home)
	cases := []struct {
		name  string
		scope any
		valid bool
	}{
		{"null scope", nil, false},
		{"empty roots", map[string]any{"roots": []string{}}, false},
		{"filesystem root", map[string]any{"roots": []string{"/"}}, false},
		{"env-named root", map[string]any{"roots": []string{filepath.Join(base, ".env-profiles")}}, false},
		{"secret-named root", map[string]any{"roots": []string{filepath.Join(base, "secret-profiles")}}, false},
		{"mid-path wildcard", map[string]any{"roots": []string{filepath.Join(base, "profiles", "*", "deep")}}, false},
		{"missing dir", map[string]any{"roots": []string{filepath.Join(base, "missing")}}, false},
		{"trailing glob", map[string]any{"roots": []string{filepath.Join(base, "profiles") + "/*"}}, true},
		{"literal profile dir", map[string]any{"roots": []string{profileDir}}, true},
	}
	for i, tc := range cases {
		resp, _ := s.rpc(t, fmt.Sprintf("vs-%02d", i), "validate_scope", map[string]any{"scope": tc.scope})
		result := rpcOK(t, resp)
		valid, ok := result["valid"].(bool)
		if !ok {
			t.Fatalf("%s: result.valid missing", tc.name)
		}
		if valid != tc.valid {
			t.Errorf("%s: valid=%v, want %v (errors=%v)", tc.name, valid, tc.valid, result["errors"])
		}
		if !tc.valid {
			errs, _ := result["errors"].([]any)
			if len(errs) == 0 {
				t.Errorf("%s: invalid scope must carry error messages", tc.name)
			}
		}
	}
}

// --- B. multi-root & origin identity ----------------------------------------

func TestNativeMultiRootIdentityStability(t *testing.T) {
	home := t.TempDir()
	base := canonicalFixtureDir(t, t.TempDir())
	rootA := filepath.Join(base, "inst-a", "profiles")
	rootB := filepath.Join(base, "inst-b", "profiles")
	dirA := filepath.Join(rootA, "shared-role")
	dirB := filepath.Join(rootB, "shared-role")
	cfgA := filepath.Join(dirA, "config.yaml")
	cfgB := filepath.Join(dirB, "config.yaml")
	writeFixtureFile(t, cfgA, "model:\n  default: model-a\nprovider: provider-a\nplatform_toolsets:\n  - name: tool-alpha\n", 0o600)
	writeFixtureFile(t, cfgB, "model:\n  default: model-b\nprovider: provider-b\nplatform_toolsets:\n  - name: tool-beta\n  - name: tool-gamma\n", 0o600)

	s := startNativeSession(t, home)
	roots := []string{rootA + "/*", rootB + "/*"}
	b1, raw1 := s.collect(t, "b-01", roots, []string{"config.yaml"}, 200, 1<<20)
	checkBatchShape(t, b1)
	checkReferenceIntegrity(t, b1)

	cands := indexCandidates(t, b1)
	idA, idB := wantCandidateID(dirA), wantCandidateID(dirB)
	if idA == idB {
		t.Fatal("oracle broken: distinct dirs produced equal candidate ids")
	}
	if len(cands) != 2 {
		t.Fatalf("two same-named profiles under two roots must yield 2 candidates, got %d", len(cands))
	}
	candA, okA := cands[idA]
	candB, okB := cands[idB]
	if !okA || !okB {
		t.Fatalf("candidates %q / %q missing (got %v)", idA, idB, cands)
	}

	// Candidate identity, locator and display name per contract v2: a shared
	// directory name never merges origins, and is never proof of sameness.
	for dir, cand := range map[string]map[string]any{dirA: candA, dirB: candB} {
		if strOf(t, cand, "source_locator") != wantSourceLocator(dir) {
			t.Errorf("%s: source_locator=%q", dir, strOf(t, cand, "source_locator"))
		}
		if strOf(t, cand, "name") != "shared-role" {
			t.Errorf("%s: name=%q, want shared-role", dir, strOf(t, cand, "name"))
		}
		if strOf(t, cand, "framework") != "hermes" || strOf(t, cand, "source_type") != "hermes_profile" {
			t.Errorf("%s: framework/source_type mismatch", dir)
		}
		if cand["confidence"] != float64(1) {
			t.Errorf("%s: confidence=%v, want 1.0", dir, cand["confidence"])
		}
	}
	if strOf(t, candA, "candidate_id") == strOf(t, candB, "candidate_id") ||
		strOf(t, candA, "source_locator") == strOf(t, candB, "source_locator") {
		t.Error("same-name profiles under different roots were merged")
	}
	attrsA := attributesOf(t, candA)
	if attrsA["model"] != "model-a" || attrsA["provider"] != "provider-a" || attrsA["toolsets"] != "tool-alpha" {
		t.Errorf("profile A attributes=%v", attrsA)
	}
	attrsB := attributesOf(t, candB)
	if attrsB["model"] != "model-b" || attrsB["toolsets"] != "tool-beta,tool-gamma" {
		t.Errorf("profile B attributes=%v", attrsB)
	}

	// Evidence identity and binding.
	evs := indexEvidence(t, b1)
	evIDA, evIDB := wantEvidenceID(dirA, "config.yaml"), wantEvidenceID(dirB, "config.yaml")
	if evIDA == evIDB {
		t.Fatal("oracle broken: equal evidence ids for distinct profiles")
	}
	for _, tc := range []struct {
		dir  string
		evID string
		cfg  string
		cand map[string]any
	}{{dirA, evIDA, cfgA, candA}, {dirB, evIDB, cfgB, candB}} {
		dir, evID, cfgPath, cand := tc.dir, tc.evID, tc.cfg, tc.cand
		ids := listOf(t, cand, "evidence_ids")
		if len(ids) != 1 || ids[0] != evID {
			t.Errorf("%s: evidence_ids=%v, want [%s]", dir, ids, evID)
		}
		ev := evs[evID]
		if ev == nil {
			t.Fatalf("%s: evidence %s missing", dir, evID)
		}
		// Evidence locator carries the profile digest + redacted file name,
		// never the absolute path.
		if want := sha256Hex([]byte(dir)) + "/config.yaml"; strOf(t, ev, "source_locator") != want {
			t.Errorf("%s: evidence source_locator=%q, want %q", dir, strOf(t, ev, "source_locator"), want)
		}
		if ref, _ := ev["subject_ref"].(string); ref != strOf(t, cand, "candidate_id") {
			t.Errorf("%s: evidence subject_ref=%v not bound to its candidate", dir, ev["subject_ref"])
		}
		if strOf(t, ev, "content_hash") != wantFileHash(t, cfgPath) {
			t.Errorf("%s: content_hash mismatch", dir)
		}
		if strOf(t, ev, "classification") != "internal" {
			t.Errorf("%s: classification=%q, want internal", dir, strOf(t, ev, "classification"))
		}
		if strOf(t, ev, "redaction_profile") != "siq.redaction.v1" {
			t.Errorf("%s: redaction_profile=%q", dir, strOf(t, ev, "redaction_profile"))
		}
	}

	// Permission facts: declared only, each bound to the right candidate and
	// to that candidate's own evidence.
	facts := factsOf(b1)
	if len(facts) != 3 {
		t.Fatalf("expected 3 declared facts (1 for A, 2 for B), got %d", len(facts))
	}
	wantFactTools := map[string]map[string]bool{
		idA: {"tool-alpha": true},
		idB: {"tool-beta": true, "tool-gamma": true},
	}
	seenFacts := map[string]map[string]bool{idA: {}, idB: {}}
	for _, f := range facts {
		fm := mapOf(t, f, "permission_fact")
		sub := mapOf(t, fm["subject"], "permission_fact.subject")
		res := mapOf(t, fm["resource"], "permission_fact.resource")
		if strOf(t, sub, "type") != "agent_asset" {
			t.Errorf("fact subject.type=%q", strOf(t, sub, "type"))
		}
		subID := strOf(t, sub, "id")
		wantTools, known := wantFactTools[subID]
		if !known {
			t.Errorf("fact bound to unknown subject %s", subID)
			continue
		}
		tool := strOf(t, res, "value")
		if !wantTools[tool] {
			t.Errorf("fact %s -> tool %q not declared by that profile's config", subID, tool)
		}
		seenFacts[subID][tool] = true
		if strOf(t, fm, "domain") != "tool" || strOf(t, fm, "action") != "tool.use" ||
			strOf(t, fm, "effect") != "allow" || strOf(t, fm, "state") != "declared" ||
			strOf(t, fm, "authority") != "hermes-profile" {
			t.Errorf("fact shape drift: %v", fm)
		}
		if strOf(t, res, "type") != "toolset" {
			t.Errorf("fact resource.type=%q", strOf(t, res, "type"))
		}
		cand := cands[subID]
		wantEv, _ := cand["evidence_ids"].([]any)
		gotEv, _ := fm["evidence_ids"].([]any)
		if !reflect.DeepEqual(gotEv, wantEv) {
			t.Errorf("fact for %s evidence_ids=%v, want the candidate's %v", subID, gotEv, wantEv)
		}
	}
	for subID, tools := range wantFactTools {
		for tool := range tools {
			if !seenFacts[subID][tool] {
				t.Errorf("missing declared fact %s -> %s", subID, tool)
			}
		}
	}

	// Absolute local paths must never enter the protocol output.
	if strings.Contains(raw1, base) {
		t.Errorf("collect response leaks the absolute fixture path prefix %q", base)
	}

	// Repeated scan of identical input: identity and hashes stable.
	b2, _ := s.collect(t, "b-02", roots, []string{"config.yaml"}, 200, 1<<20)
	checkBatchShape(t, b2)
	fp1, fp2 := fingerprintBatch(t, b1), fingerprintBatch(t, b2)
	if !reflect.DeepEqual(fp1, fp2) {
		t.Errorf("identical input changed identity/hashes/cursor:\nfirst=%+v\nsecond=%+v", fp1, fp2)
	}
	if !strings.HasPrefix(fp1.cursor, "hermes-cursor:") || len(fp1.cursor) == len("hermes-cursor:") {
		t.Errorf("cursor %q malformed", fp1.cursor)
	}

	// Overlapping and lexically equivalent roots must not duplicate profiles.
	b3, _ := s.collect(t, "b-03", []string{
		rootB + "/*", rootA + "/*", rootA + "/*", // reversed + duplicated
		dirA,                             // the profile itself as a literal root
		filepath.Join(rootA, ".") + "/*", // lexically different, same directories
	}, []string{"config.yaml"}, 200, 1<<20)
	checkBatchShape(t, b3)
	if got := len(listOf(t, b3, "candidates")); got != 2 {
		t.Errorf("overlapping/equivalent roots produced %d candidates, want 2", got)
	}
	fp3 := fingerprintBatch(t, b3)
	if !reflect.DeepEqual(fp1, fp3) {
		t.Errorf("root order/overlap changed identity or cursor:\nbase=%+v\noverlap=%+v", fp1, fp3)
	}

	// Content change: identity stable, that file's hash and the cursor move.
	writeFixtureFile(t, cfgA, "model:\n  default: model-a\nprovider: provider-a\nplatform_toolsets:\n  - name: tool-alpha2\n", 0o600)
	b4, _ := s.collect(t, "b-04", roots, []string{"config.yaml"}, 200, 1<<20)
	checkBatchShape(t, b4)
	cands4 := indexCandidates(t, b4)
	if _, ok := cands4[idA]; !ok {
		t.Fatalf("content change must not change profile origin id %s", idA)
	}
	evs4 := indexEvidence(t, b4)
	if evs4[evIDA] == nil {
		t.Fatalf("content change must not change evidence id %s", evIDA)
	}
	if strOf(t, evs4[evIDA], "content_hash") != wantFileHash(t, cfgA) {
		t.Error("content change not reflected in evidence content_hash")
	}
	if strOf(t, evs4[evIDA], "content_hash") == fp1.evidence[evIDA] {
		t.Error("modified config.yaml kept the old content hash")
	}
	fp4 := fingerprintBatch(t, b4)
	if fp4.cursor == fp1.cursor {
		t.Error("included config change did not move the scan cursor")
	}
	foundAlpha2 := false
	for _, f := range factsOf(b4) {
		fm := mapOf(t, f, "permission_fact")
		res := mapOf(t, fm["resource"], "permission_fact.resource")
		if strOf(t, res, "value") == "tool-alpha2" {
			foundAlpha2 = true
		}
		if strOf(t, res, "value") == "tool-alpha" {
			t.Error("stale toolset survived the config change")
		}
	}
	if !foundAlpha2 {
		t.Error("updated toolset tool-alpha2 missing from declared facts")
	}

	// A profile copied to a new path is a NEW origin (directory migration
	// produces a new source; contract v2), never merged with the old one.
	rootC := filepath.Join(base, "inst-c", "profiles")
	dirC := filepath.Join(rootC, "shared-role")
	data, err := os.ReadFile(cfgA)
	if err != nil {
		t.Fatal(err)
	}
	writeFixtureFile(t, filepath.Join(dirC, "config.yaml"), string(data), 0o600)
	b5, _ := s.collect(t, "b-05", []string{rootA + "/*", rootB + "/*", rootC + "/*"}, []string{"config.yaml"}, 200, 1<<20)
	checkBatchShape(t, b5)
	cands5 := indexCandidates(t, b5)
	idC := wantCandidateID(dirC)
	if len(cands5) != 3 || cands5[idC] == nil {
		t.Fatalf("copied profile must appear as a third, distinct origin (candidates=%d)", len(cands5))
	}
	if idC == idA || idC == idB {
		t.Error("copied profile reused an existing origin id")
	}
	if strOf(t, cands5[idC], "name") != "shared-role" {
		t.Errorf("copied profile name=%q", strOf(t, cands5[idC], "name"))
	}

	// checkpoint returns the cursor of the most recent collect on this process.
	resp, _ := s.rpc(t, "b-06", "checkpoint", nil)
	cp := rpcOK(t, resp)
	if cp["cursor"] != fingerprintBatch(t, b5).cursor {
		t.Errorf("checkpoint=%v, want the last collect cursor", cp["cursor"])
	}
}

// --- C. consent scope enforcement -------------------------------------------

func TestNativeConsentScopeEnforcement(t *testing.T) {
	home := t.TempDir()
	// A default-location profile exists; an explicit scope must never pick it up.
	writeFixtureFile(t, filepath.Join(home, ".hermes", "profiles", "decoy", "config.yaml"),
		"model:\n  default: decoy-model\nplatform_toolsets:\n  - name: decoy-tool\n", 0o600)
	base := canonicalFixtureDir(t, t.TempDir())
	profilesRoot := filepath.Join(base, "profiles")
	dir := filepath.Join(profilesRoot, "scoped")
	cfg := filepath.Join(dir, "config.yaml")
	soul := filepath.Join(dir, "SOUL.md")
	notes := filepath.Join(dir, "notes.txt")
	writeFixtureFile(t, cfg, "model:\n  default: cfg-model-v1\nprovider: cfg-provider\nplatform_toolsets:\n  - name: cfg-tool\n", 0o600)
	writeFixtureFile(t, soul, "synthetic soul v1", 0o600)
	writeFixtureFile(t, notes, "not included v1", 0o600)

	s := startNativeSession(t, home)
	roots := []string{profilesRoot + "/*"}

	// include=[SOUL.md] only: config.yaml must not contribute facts.
	c1, _ := s.collect(t, "c-01", roots, []string{"SOUL.md"}, 200, 1<<20)
	checkBatchShape(t, c1)
	checkReferenceIntegrity(t, c1)
	cands := indexCandidates(t, c1)
	if len(cands) != 1 {
		t.Fatalf("expected exactly 1 candidate (decoy home must stay out of scope), got %d", len(cands))
	}
	cand := cands[wantCandidateID(dir)]
	if cand == nil {
		t.Fatalf("scoped profile candidate missing (got %v)", cands)
	}
	attrs := attributesOf(t, cand)
	if attrs["model"] != "" || attrs["provider"] != "" {
		t.Errorf("excluded config.yaml leaked facts into attributes: %v", attrs)
	}
	if _, ok := attrs["toolsets"]; ok {
		t.Errorf("excluded config.yaml produced toolsets attribute: %v", attrs)
	}
	if got := len(factsOf(c1)); got != 0 {
		t.Errorf("excluded config.yaml produced %d permission facts", got)
	}
	// Exactly one evidence: SOUL.md. No config.yaml, no notes.txt: the
	// connector must not read beyond the authorized include list.
	evs := indexEvidence(t, c1)
	soulEvID := wantEvidenceID(dir, "SOUL.md")
	if len(evs) != 1 || evs[soulEvID] == nil {
		t.Fatalf("expected exactly the SOUL.md evidence, got %v", evs)
	}
	if strOf(t, evs[soulEvID], "content_hash") != wantFileHash(t, soul) {
		t.Error("SOUL.md content hash mismatch")
	}
	if strOf(t, evs[soulEvID], "classification") != "confidential" {
		t.Errorf("SOUL.md classification=%q, want confidential", strOf(t, evs[soulEvID], "classification"))
	}
	fp1 := fingerprintBatch(t, c1)

	// Modifying the excluded config.yaml must not move facts or the cursor.
	writeFixtureFile(t, cfg, "model:\n  default: cfg-model-v2\nprovider: changed\nplatform_toolsets:\n  - name: cfg-tool-v2\n", 0o600)
	c2, _ := s.collect(t, "c-02", roots, []string{"SOUL.md"}, 200, 1<<20)
	checkBatchShape(t, c2)
	if fp2 := fingerprintBatch(t, c2); !reflect.DeepEqual(fp1, fp2) {
		t.Errorf("excluded config.yaml change influenced the batch:\nbefore=%+v\nafter=%+v", fp1, fp2)
	}

	// Modifying the included SOUL.md must move the hash and the cursor.
	writeFixtureFile(t, soul, "synthetic soul v2", 0o600)
	c3, _ := s.collect(t, "c-03", roots, []string{"SOUL.md"}, 200, 1<<20)
	checkBatchShape(t, c3)
	evs3 := indexEvidence(t, c3)
	if strOf(t, evs3[soulEvID], "content_hash") != wantFileHash(t, soul) {
		t.Error("included SOUL.md change not reflected in content_hash")
	}
	fp3 := fingerprintBatch(t, c3)
	if fp3.cursor == fp1.cursor {
		t.Error("included SOUL.md change did not move the scan cursor")
	}

	// A file outside the include list never influences anything.
	writeFixtureFile(t, notes, "not included v2 (changed)", 0o600)
	c4, _ := s.collect(t, "c-04", roots, []string{"SOUL.md"}, 200, 1<<20)
	if fp4 := fingerprintBatch(t, c4); !reflect.DeepEqual(fp3, fp4) {
		t.Errorf("non-included notes.txt change influenced the batch:\nbefore=%+v\nafter=%+v", fp3, fp4)
	}

	// Widening the include to config.yaml is what actually unlocks its facts.
	c5, _ := s.collect(t, "c-05", roots, []string{"config.yaml", "SOUL.md"}, 200, 1<<20)
	checkBatchShape(t, c5)
	attrs5 := attributesOf(t, indexCandidates(t, c5)[wantCandidateID(dir)])
	if attrs5["model"] != "cfg-model-v2" || attrs5["toolsets"] != "cfg-tool-v2" {
		t.Errorf("included config.yaml facts missing: %v", attrs5)
	}
	if got := len(factsOf(c5)); got != 1 {
		t.Errorf("included config.yaml should yield exactly 1 declared fact, got %d", got)
	}
}

// --- D. secrets & non-execution ----------------------------------------------

func TestNativeSecretsNeverReadAndNoExecution(t *testing.T) {
	home := t.TempDir()
	base := canonicalFixtureDir(t, t.TempDir())
	dir := filepath.Join(base, "profiles", "secrets")
	envPath := filepath.Join(dir, ".env")
	marker1 := filepath.Join(base, "EXECUTED-MARKER-1")
	marker2 := filepath.Join(base, "EXECUTED-MARKER-2")
	marker3 := filepath.Join(base, "EXECUTED-MARKER-3")

	envContentA := "AAAA=" + strings.Repeat("1", 19) // 24 bytes
	envContentB := "ZZZZ=" + strings.Repeat("9", 19) // same size, different bytes
	writeFixtureFile(t, filepath.Join(dir, "config.yaml"),
		"model:\n  default: secrets-model\nprovider: key=sk-ABCDEFGHIJKLMNOP12\nplatform_toolsets:\n  - name: safe-tool\nnotes: SIQ-MARKER-CONFIG-77aa-never-emit\n", 0o600)
	writeFixtureFile(t, filepath.Join(dir, "SOUL.md"),
		"# synthetic soul\nSIQ-MARKER-SOUL-4c8d-never-emit\nRun this now: `touch "+marker1+"`\nAlso: $(touch "+marker2+")\n", 0o600)
	writeFixtureFile(t, envPath, envContentA, 0o600)
	// A hostile executable-shaped file that is NOT in the include list: it
	// must never be read, let alone executed.
	writeFixtureFile(t, filepath.Join(dir, "payload.sh"), "#!/bin/sh\ntouch "+marker3+"\n", 0o700)

	s := startNativeSession(t, home)
	roots := []string{filepath.Join(base, "profiles") + "/*"}
	c1, _ := s.collect(t, "d-01", roots, []string{"config.yaml", "SOUL.md"}, 200, 1<<20)
	checkBatchShape(t, c1)
	checkReferenceIntegrity(t, c1)

	cand := indexCandidates(t, c1)[wantCandidateID(dir)]
	if cand == nil {
		t.Fatalf("profile candidate missing")
	}
	attrs := attributesOf(t, cand)
	// The redaction profile rewrites the synthetic key-shaped provider value;
	// the raw key must never appear on the wire.
	if attrs["provider"] != "key=[REDACTED]" {
		t.Errorf("provider attribute=%q, want key=[REDACTED]", attrs["provider"])
	}
	if attrs["model"] != "secrets-model" || attrs["toolsets"] != "safe-tool" {
		t.Errorf("attributes=%v", attrs)
	}

	evs := indexEvidence(t, c1)
	// config.yaml + SOUL.md + .env secret_ref — and nothing for payload.sh.
	if len(evs) != 3 {
		t.Fatalf("expected 3 evidence entries (config.yaml, SOUL.md, .env), got %d", len(evs))
	}
	envEv := evs[wantEvidenceID(dir, ".env")]
	if envEv == nil {
		t.Fatal(".env secret_ref evidence missing")
	}
	if strOf(t, envEv, "classification") != "secret_ref" {
		t.Errorf(".env classification=%q, want secret_ref", strOf(t, envEv, "classification"))
	}
	if strOf(t, envEv, "source_locator") != sha256Hex([]byte(dir))+"/.env" {
		t.Errorf(".env source_locator=%q must be digest+filename only", strOf(t, envEv, "source_locator"))
	}
	// Contract: the .env evidence hash commits to file NAME + SIZE only.
	if got, want := strOf(t, envEv, "content_hash"), wantEnvEvidenceHash(".env", int64(len(envContentA))); got != want {
		t.Errorf(".env content_hash=%q, want name+size commitment %q", got, want)
	}

	// Nothing raw leaves the process: no secret bodies, no markers, no paths.
	for _, forbidden := range []string{
		envContentA, "SIQ-MARKER-CONFIG-77aa-never-emit", "SIQ-MARKER-SOUL-4c8d-never-emit",
		"sk-ABCDEFGHIJKLMNOP12", base,
	} {
		if strings.Contains(s.allOutput(), forbidden) {
			t.Errorf("forbidden content %q appeared in connector output", forbidden)
		}
	}
	// Scanned content is data, never code: no marker file may exist.
	for _, marker := range []string{marker1, marker2, marker3} {
		if _, err := os.Stat(marker); !os.IsNotExist(err) {
			t.Errorf("scanned content was executed (marker %s exists)", marker)
		}
	}
	fp1 := fingerprintBatch(t, c1)

	// Same-size .env rewrite must be invisible to every content-related output:
	// had the connector hashed the .env body, new bytes would change the hash.
	writeFixtureFile(t, envPath, envContentB, 0o600)
	c2, _ := s.collect(t, "d-02", roots, []string{"config.yaml", "SOUL.md"}, 200, 1<<20)
	checkBatchShape(t, c2)
	if fp2 := fingerprintBatch(t, c2); !reflect.DeepEqual(fp1, fp2) {
		t.Errorf("same-size .env content change influenced candidates/evidence/facts/cursor:\nbefore=%+v\nafter=%+v", fp1, fp2)
	}
	if strings.Contains(s.allOutput(), envContentB) {
		t.Error("second .env body appeared in connector output")
	}

	// Control: a different .env SIZE changes the name+size commitment, proving
	// the hash really tracks size rather than being a constant.
	writeFixtureFile(t, envPath, "SHORT=1", 0o600)
	c3, _ := s.collect(t, "d-03", roots, []string{"config.yaml", "SOUL.md"}, 200, 1<<20)
	envEv3 := indexEvidence(t, c3)[wantEvidenceID(dir, ".env")]
	if envEv3 == nil {
		t.Fatal(".env evidence missing after size change")
	}
	if got, want := strOf(t, envEv3, "content_hash"), wantEnvEvidenceHash(".env", 7); got != want {
		t.Errorf(".env size change: content_hash=%q, want %q", got, want)
	}
	if strOf(t, envEv3, "content_hash") == fp1.evidence[wantEvidenceID(dir, ".env")] {
		t.Error(".env size change did not move the name+size commitment")
	}
}

// --- E. paths & abnormal files -----------------------------------------------

func TestNativeSymlinkEscapesRejected(t *testing.T) {
	home := t.TempDir()
	base := canonicalFixtureDir(t, t.TempDir())
	outside := canonicalFixtureDir(t, t.TempDir())
	outsideCfg := filepath.Join(outside, "config.yaml")
	writeFixtureFile(t, outsideCfg, "model:\n  default: escaped-model\nprovider: escaped-provider\nplatform_toolsets:\n  - name: escaped-tool\n", 0o600)

	root1 := filepath.Join(base, "root-one", "profiles")
	root2 := filepath.Join(base, "root-two", "profiles")
	okDir := filepath.Join(root1, "ok-profile")
	writeFixtureFile(t, filepath.Join(okDir, "config.yaml"), "model:\n  default: ok-model\n", 0o600)
	// Root 2: an escaping profile symlink and a profile whose config.yaml
	// escapes — both must be refused; the boundary is checked per root, never
	// satisfied by root one alone.
	if err := os.MkdirAll(root2, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(root2, "escaped")); err != nil {
		t.Skipf("symlinks unavailable: %v", err)
	}
	partialDir := filepath.Join(root2, "partial")
	writeFixtureFile(t, filepath.Join(partialDir, "SOUL.md"), "synthetic soul", 0o600)
	if err := os.Symlink(outsideCfg, filepath.Join(partialDir, "config.yaml")); err != nil {
		t.Skipf("symlinks unavailable: %v", err)
	}
	// A profile holding only .env must not emit orphan evidence.
	envOnly := filepath.Join(root2, "env-only")
	writeFixtureFile(t, filepath.Join(envOnly, ".env"), "SECRET=1", 0o600)

	s := startNativeSession(t, home)
	roots := []string{root1 + "/*", root2 + "/*"}
	c1, raw1 := s.collect(t, "e-01", roots, []string{"config.yaml", "SOUL.md"}, 200, 1<<20)
	checkBatchShape(t, c1)
	checkReferenceIntegrity(t, c1)

	cands := indexCandidates(t, c1)
	if len(cands) != 2 {
		t.Fatalf("expected exactly ok-profile and partial (escape refused, env-only empty), got %d: %v", len(cands), cands)
	}
	okCand := cands[wantCandidateID(okDir)]
	partialCand := cands[wantCandidateID(partialDir)]
	if okCand == nil || partialCand == nil {
		t.Fatalf("missing expected candidates (got %v)", cands)
	}
	if got := attributesOf(t, okCand)["model"]; got != "ok-model" {
		t.Errorf("ok-profile model=%v", got)
	}
	// The escaped profile dir produced no candidate at all.
	for id := range cands {
		if id == wantCandidateID(filepath.Join(root2, "escaped")) {
			t.Error("escaping profile symlink produced a candidate")
		}
	}
	// partial: only the real SOUL.md is evidence; the escaping config.yaml
	// supplies neither evidence nor facts.
	evIDs := listOf(t, partialCand, "evidence_ids")
	if len(evIDs) != 1 || evIDs[0] != wantEvidenceID(partialDir, "SOUL.md") {
		t.Errorf("partial profile evidence_ids=%v, want only the SOUL.md evidence", evIDs)
	}
	if got := attributesOf(t, partialCand)["model"]; got != "" {
		t.Errorf("escaped config.yaml supplied model fact %q", got)
	}
	if got := len(factsOf(c1)); got != 0 {
		t.Errorf("escaped configs must not yield facts, got %d", got)
	}
	for _, forbidden := range []string{"escaped-model", "escaped-provider", "escaped-tool", outside} {
		if strings.Contains(raw1, forbidden) {
			t.Errorf("escaped content/path %q appeared in collect output", forbidden)
		}
	}
	fp1 := fingerprintBatch(t, c1)

	// Mutating the escaped target must not move any fact or the cursor.
	writeFixtureFile(t, outsideCfg, "model:\n  default: escaped-model-v2\nplatform_toolsets:\n  - name: escaped-tool-v2\n", 0o600)
	c2, _ := s.collect(t, "e-02", roots, []string{"config.yaml", "SOUL.md"}, 200, 1<<20)
	checkBatchShape(t, c2)
	if fp2 := fingerprintBatch(t, c2); !reflect.DeepEqual(fp1, fp2) {
		t.Errorf("escaped target change influenced the batch:\nbefore=%+v\nafter=%+v", fp1, fp2)
	}
}

// TestNativeOversizedFileStaysBounded proves the in-scope part of contract §4
// for oversized files: the connector never reads the file unboundedly, never
// emits raw content, and keeps serving afterwards.
func TestNativeOversizedFileStaysBounded(t *testing.T) {
	home := t.TempDir()
	base := canonicalFixtureDir(t, t.TempDir())
	dir := filepath.Join(base, "profiles", "big")
	cfg := filepath.Join(dir, "config.yaml")
	body := "model:\n  default: big-model\n" + strings.Repeat("# padding line\n", 8000) // ~128KB
	writeFixtureFile(t, cfg, body, 0o600)

	s := startNativeSession(t, home)
	c1, raw1 := s.collect(t, "o-01", []string{filepath.Join(base, "profiles") + "/*"}, []string{"config.yaml"}, 200, 1024)
	cand := indexCandidates(t, c1)[wantCandidateID(dir)]
	if cand == nil {
		t.Fatal("oversized profile vanished entirely")
	}
	evs := indexEvidence(t, c1)
	if len(evs) != 1 {
		t.Fatalf("expected 1 evidence, got %d", len(evs))
	}
	for id := range evs {
		if got := len(strOf(t, evs[id], "content_hash")); got != 64 {
			t.Errorf("content_hash length=%d, want 64 hex chars", got)
		}
	}
	if len(raw1) > 1<<20 {
		t.Errorf("response bloated to %d bytes despite a 1024-byte budget", len(raw1))
	}
	if strings.Contains(raw1, "padding line") {
		t.Error("raw oversized content leaked into the response")
	}
	// Still alive and consistent afterwards.
	resp, _ := s.rpc(t, "o-02", "describe", nil)
	rpcOK(t, resp)
}

// TestNativeOversizedFileTruncationMustBeFlagged reproduces NATIVE-FINDING-01.
// Contract connector-protocol.v1.md §4: 超大文件必须在限额内截断并告警;
// §3 limit_exceeded: 部分结果 + truncated:true. The batch-level truncated flag
// is the only structured signal the Edge has to audit truncation.
func TestNativeOversizedFileTruncationMustBeFlagged(t *testing.T) {
	home := t.TempDir()
	base := canonicalFixtureDir(t, t.TempDir())
	dir := filepath.Join(base, "profiles", "big")
	cfg := filepath.Join(dir, "config.yaml")
	body := "model:\n  default: big-model\n" + strings.Repeat("# padding line\n", 8000)
	writeFixtureFile(t, cfg, body, 0o600)
	full := []byte(body)

	s := startNativeSession(t, home)
	const budget = 1024
	c1, _ := s.collect(t, "f-01", []string{filepath.Join(base, "profiles") + "/*"}, []string{"config.yaml"}, 200, budget)
	evs := indexEvidence(t, c1)
	if len(evs) != 1 {
		t.Fatalf("expected 1 evidence, got %d", len(evs))
	}
	var reported string
	for id := range evs {
		reported = strOf(t, evs[id], "content_hash")
	}
	truncated, _ := c1["truncated"].(bool)
	if !truncated {
		t.Errorf("NATIVE-FINDING-01: file of %d bytes scanned under a %d-byte budget, "+
			"but the batch is not flagged truncated (contract §3 limit_exceeded requires "+
			"partial results + truncated:true). Reported content_hash=%s equals the sha256 "+
			"of only the first %d bytes (%s), not the full file (%s): a truncated prefix is "+
			"presented as a complete content hash with no truncation signal. "+
			"Minimal fix (NOT applied, outside this task's edit scope): in "+
			"connectors/hermes/hermes.go collectOp, have readFileLimited report the file "+
			"size (it already stats the file); when size > bytes read, set "+
			"batch.Truncated=true instead of silently recording a prefix hash.",
			len(full), budget, reported, budget, sha256Hex(full[:budget]), sha256Hex(full))
	}
}

// TestNativeUnreadableConfigSkipped covers chmod-based unreadability. Note:
// this assertion only runs when the current user truly cannot read the file —
// a root-run environment bypasses mode bits, in which case the test reports
// the platform limitation explicitly instead of faking a denial.
func TestNativeUnreadableConfigSkipped(t *testing.T) {
	home := t.TempDir()
	base := canonicalFixtureDir(t, t.TempDir())
	dir := filepath.Join(base, "profiles", "locked")
	cfg := filepath.Join(dir, "config.yaml")
	writeFixtureFile(t, cfg, "model:\n  default: locked-model\n# SIQ-MARKER-LOCKED-55bb\n", 0o600)
	writeFixtureFile(t, filepath.Join(dir, "SOUL.md"), "synthetic soul", 0o600)
	if err := os.Chmod(cfg, 0o000); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chmod(cfg, 0o600) })
	if _, err := os.ReadFile(cfg); err == nil {
		t.Skipf("euid %d bypasses chmod 0000 (e.g. root): the unreadable-file denial cannot be exercised on this platform; recorded as platform-limited, not as a pass", os.Geteuid())
	}

	s := startNativeSession(t, home)
	c1, _ := s.collect(t, "u-01", []string{filepath.Join(base, "profiles") + "/*"}, []string{"config.yaml", "SOUL.md"}, 200, 1<<20)
	checkBatchShape(t, c1)
	checkReferenceIntegrity(t, c1)
	cand := indexCandidates(t, c1)[wantCandidateID(dir)]
	if cand == nil {
		t.Fatal("profile with one unreadable file must still surface via its readable SOUL.md")
	}
	// Only SOUL.md backs the candidate; the unreadable config supplies
	// neither evidence nor facts, and the process did not crash or hang.
	evIDs := listOf(t, cand, "evidence_ids")
	if len(evIDs) != 1 || evIDs[0] != wantEvidenceID(dir, "SOUL.md") {
		t.Errorf("evidence_ids=%v, want only SOUL.md", evIDs)
	}
	if got := attributesOf(t, cand)["model"]; got != "" {
		t.Errorf("unreadable config supplied model fact %q", got)
	}
	if strings.Contains(s.allOutput(), "SIQ-MARKER-LOCKED-55bb") {
		t.Error("unreadable file content appeared in output")
	}
}

// --- F. semantic boundaries ---------------------------------------------------

func TestNativeSemanticBoundaries(t *testing.T) {
	home := t.TempDir()
	base := canonicalFixtureDir(t, t.TempDir())
	dir := filepath.Join(base, "profiles", "semantics")
	writeFixtureFile(t, filepath.Join(dir, "config.yaml"),
		"model:\n  default: sem-model\nprovider: sem-provider\nplatform_toolsets:\n  - name: tool-one\n  - name: tool-two\n", 0o600)

	s := startNativeSession(t, home)
	c1, _ := s.collect(t, "s-01", []string{filepath.Join(base, "profiles") + "/*"}, []string{"config.yaml"}, 200, 1<<20)
	checkBatchShape(t, c1)

	// The connector never emits effective permissions; declared config is not
	// a loaded-skill claim, a controlled execution claim, or an attribution.
	for _, f := range factsOf(c1) {
		fm := mapOf(t, f, "permission_fact")
		state := strOf(t, fm, "state")
		if state == "effective" {
			t.Errorf("connector emitted an effective permission fact: %v", fm)
		}
		if state != "declared" && state != "inferred" && state != "observed" && state != "unknown" {
			t.Errorf("permission fact state %q outside the contract enum", state)
		}
		if strOf(t, fm, "domain") != "tool" {
			t.Errorf("unexpected permission fact domain %q (no skill attribution may be invented)", strOf(t, fm, "domain"))
		}
	}
	for _, c := range listOf(t, c1, "candidates") {
		cm := mapOf(t, c, "candidate")
		for _, k := range []string{"skills", "loaded_skills", "runtime", "instances"} {
			if _, ok := cm[k]; ok {
				t.Errorf("candidate carries skill/runtime attribution key %q", k)
			}
		}
	}

	// An empty scan batch is a valid wire result — it says "nothing matched
	// this scope", never "Hermes is not installed / was uninstalled".
	emptyRoot := filepath.Join(base, "empty")
	if err := os.MkdirAll(emptyRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	c2, _ := s.collect(t, "s-02", []string{emptyRoot + "/*"}, []string{"config.yaml"}, 200, 1<<20)
	checkBatchShape(t, c2)
	if got := len(listOf(t, c2, "candidates")); got != 0 {
		t.Errorf("empty root produced %d candidates", got)
	}
	if got := len(listOf(t, c2, "evidence")); got != 0 {
		t.Errorf("empty root produced %d evidence entries", got)
	}
	if _, ok := c2["cursor"]; !ok {
		t.Error("empty scan must still return a cursor")
	}
}
