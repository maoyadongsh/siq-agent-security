// Command hermes-connector is the Hermes Profile Connector
// (connector-protocol.v1.md). It discovers Hermes agent profiles under
// ~/.hermes/profiles and emits deterministic candidates + evidence.
//
// Realistic boundaries (SIQ 勘察):
//   - config.yaml is parsed best-effort without a YAML dependency: only
//     model.default, provider and platform_toolsets keys are extracted.
//     Unknown structure is ignored and raw lines are never emitted.
//   - .env files are NEVER read: a secret_ref evidence records only the file
//     name and size.
//   - file content never leaves this process (payload_ref stays null); only
//     content hashes and redacted attributes are emitted.
package main

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"siq-agent-security/edge/agent/protocol"
)

const connectorVersion = "0.1.0"

// defaultProfilesGlob is the default scope (task spec: scope 默认
// ~/.hermes/profiles/*).
const defaultProfilesGlob = "~/.hermes/profiles/*"

var defaultIncludes = []string{"config.yaml", "SOUL.md"}

var (
	lastCursor string        // most recent collect cursor (checkpoint op)
	opTimeout  time.Duration // from SIQ_CONNECTOR_TIMEOUT_MS
)

func main() {
	if len(os.Args) == 2 && os.Args[1] == "--serve" {
		if ms := os.Getenv("SIQ_CONNECTOR_TIMEOUT_MS"); ms != "" {
			if v, err := strconv.Atoi(ms); err == nil && v > 0 {
				opTimeout = time.Duration(v) * time.Millisecond
			}
		}
		if opTimeout <= 0 {
			opTimeout = time.Duration(protocol.DefaultCollectTimeoutMS) * time.Millisecond
		}
		if err := serve(); err != nil {
			fmt.Fprintf(os.Stderr, "hermes-connector: %v\n", err)
			os.Exit(1)
		}
		return
	}
	fmt.Fprintln(os.Stderr, "usage: hermes-connector --serve")
	os.Exit(2)
}

// serve runs the NDJSON protocol loop. stdout carries ONLY protocol messages;
// diagnostics go to stderr (contract §1).
func serve() error {
	dec := json.NewDecoder(bufio.NewReader(os.Stdin))
	w := bufio.NewWriter(os.Stdout)
	for {
		var req protocol.Request
		if err := dec.Decode(&req); err != nil {
			if errors.Is(err, io.EOF) {
				return nil
			}
			return fmt.Errorf("read request: %w", err)
		}
		line, err := json.Marshal(dispatch(&req))
		if err != nil {
			return fmt.Errorf("encode response: %w", err)
		}
		if _, err := w.Write(append(line, '\n')); err != nil {
			return err
		}
		if err := w.Flush(); err != nil {
			return err
		}
	}
}

type validateScopeParams struct {
	Scope *protocol.Scope `json:"scope"`
}

type planScanParams struct {
	Scope  *protocol.Scope `json:"scope"`
	Cursor string          `json:"cursor,omitempty"`
}

type collectParams struct {
	Plan protocol.ScanPlan `json:"plan"`
}

func dispatch(req *protocol.Request) protocol.Response {
	resp := protocol.Response{ID: req.ID, OK: true}
	var result any
	var perr *protocol.ProtocolError
	switch req.Op {
	case protocol.OpDescribe:
		result = capabilities()
	case protocol.OpValidateScope:
		var p validateScopeParams
		if err := json.Unmarshal(req.Params, &p); err != nil {
			perr = badRequest(err)
		} else {
			result = validateScopeOp(p.Scope)
		}
	case protocol.OpPlanScan:
		var p planScanParams
		if err := json.Unmarshal(req.Params, &p); err != nil {
			perr = badRequest(err)
		} else {
			result = planScanOp(p)
		}
	case protocol.OpCollect:
		var p collectParams
		if err := json.Unmarshal(req.Params, &p); err != nil {
			perr = badRequest(err)
		} else {
			batch, err := collectOp(p.Plan)
			if err != nil {
				perr = errToProtocol(err)
			} else {
				result = batch
			}
		}
	case protocol.OpCheckpoint:
		result = protocol.CursorResult{Cursor: lastCursor}
	case protocol.OpHealth:
		result = healthOp()
	default:
		perr = &protocol.ProtocolError{Code: protocol.CodeUnsupported, Message: fmt.Sprintf("unknown op %q", req.Op)}
	}
	if perr != nil {
		resp.OK = false
		resp.Error = perr
		resp.Result = nil
	} else {
		resp.Result = result
	}
	return resp
}

// badRequest covers malformed params (an edge-case extension outside the
// contract's five codes; the Edge treats unknown codes as generic errors).
func badRequest(err error) *protocol.ProtocolError {
	return &protocol.ProtocolError{Code: "bad_request", Message: err.Error()}
}

func errToProtocol(err error) *protocol.ProtocolError {
	switch {
	case errors.Is(err, protocol.ErrEnvFileRefused):
		return &protocol.ProtocolError{Code: protocol.CodeRedactionFailure, Message: err.Error()}
	default:
		return &protocol.ProtocolError{Code: "internal_error", Message: err.Error()}
	}
}

func capabilities() protocol.ConnectorCapabilities {
	return protocol.ConnectorCapabilities{
		Version:             connectorVersion,
		Objects:             []string{"hermes_profile"},
		RequiredPermissions: []string{"read:" + protocol.ExpandHome("~/.hermes/profiles")},
		DataCategories:      []string{"config_names", "tool_names"},
		MaxOutputBytes:      protocol.DefaultOutputLimitBytes,
		NetworkAccess:       false,
	}
}

// validateScopeOp implements validate_scope. Contract §4: an empty scope must
// be rejected (plan/collect may substitute the default scope, but an explicit
// validation of nothing is invalid).
func validateScopeOp(scope *protocol.Scope) protocol.ValidationResult {
	errs := validateScope(scope)
	return protocol.ValidationResult{Valid: len(errs) == 0, Errors: errs}
}

func validateScope(scope *protocol.Scope) []string {
	if scope == nil || len(scope.Roots) == 0 {
		return []string{"empty scope: no roots"}
	}
	if err := protocol.ValidateScopeSafety(scope); err != nil {
		return []string{err.Error()}
	}
	return nil
}

func planScanOp(p planScanParams) protocol.ScanPlan {
	return protocol.ScanPlan{Scope: effectiveScope(p.Scope), Cursor: p.Cursor, Limits: defaultLimits()}
}

func defaultLimits() protocol.CollectLimits {
	return protocol.CollectLimits{MaxFiles: 200, MaxBytes: 16 * 1024 * 1024}
}

// effectiveScope substitutes the default scope when none was provided.
func effectiveScope(s *protocol.Scope) *protocol.Scope {
	if s == nil || len(s.Roots) == 0 {
		return &protocol.Scope{Roots: []string{defaultProfilesGlob}, Include: defaultIncludes}
	}
	out := *s
	if len(out.Include) == 0 {
		out.Include = defaultIncludes
	}
	return &out
}

// collectOp implements collect: profile discovery + evidence generation.
func collectOp(plan protocol.ScanPlan) (protocol.EvidenceBatch, error) {
	sc := effectiveScope(plan.Scope)
	limits := plan.Limits
	if limits.MaxFiles <= 0 {
		limits.MaxFiles = defaultLimits().MaxFiles
	}
	if limits.MaxBytes <= 0 {
		limits.MaxBytes = defaultLimits().MaxBytes
	}
	start := time.Now()

	var dirs []string
	for _, raw := range sc.Roots {
		root := strings.TrimSpace(protocol.ExpandHome(raw))
		matches, err := globDirs(root)
		if err != nil {
			return protocol.EvidenceBatch{}, fmt.Errorf("root %q: %w", raw, err)
		}
		dirs = append(dirs, matches...)
	}
	dirs = dedupeStrings(dirs)
	sort.Strings(dirs)

	batch := protocol.EvidenceBatch{
		Candidates:      []*protocol.Candidate{},
		Evidence:        []*protocol.Evidence{},
		PermissionFacts: []*protocol.PermissionFact{},
	}
	now := time.Now().UTC().Format(time.RFC3339)
	red := protocol.NewRedactor()
	var scannedDirs []string
	var readBytes int64
	profiles := 0
	// Base of the first root, used for the symlink-escape boundary check.
	rootBase := strings.TrimSuffix(strings.TrimSpace(protocol.ExpandHome(sc.Roots[0])), "/*")

	for _, dir := range dirs {
		if int64(profiles) >= limits.MaxFiles {
			batch.Truncated = true
			break
		}
		if opTimeout > 0 && time.Since(start) > opTimeout {
			batch.Truncated = true
			break
		}
		base := filepath.Base(dir)
		if base == "." || base == string(filepath.Separator) {
			continue
		}
		// Contract §4 negative test: symlinks inside the scope pointing
		// outside it are rejected (skipped + stderr diagnostic).
		if escaped, _ := symlinkEscapes(rootBase, dir); escaped {
			fmt.Fprintf(os.Stderr, "hermes: skipping %s: symlink escapes scope\n", dir)
			continue
		}
		entries, err := os.ReadDir(dir)
		if err != nil {
			fmt.Fprintf(os.Stderr, "hermes: readdir %s: %v\n", dir, err)
			continue
		}
		profileFiles := make(map[string]bool)
		for _, e := range entries {
			if !e.IsDir() {
				profileFiles[e.Name()] = true
			}
		}
		// A profile directory must contain config.yaml or SOUL.md (task spec).
		hasConfig := false
		for _, inc := range sc.Include {
			if profileFiles[inc] {
				hasConfig = true
				break
			}
		}
		if !hasConfig {
			continue
		}

		cand := &protocol.Candidate{
			CandidateID:   "hermes:" + base,
			SourceType:    "hermes_profile",
			SourceLocator: red.RedactString("hermes://profiles/" + base),
			DiscoveredAt:  now,
			Name:          truncate(base, 256),
			Framework:     "hermes",
			Confidence:    1.0,
			Attributes:    map[string]string{},
			EvidenceIDs:   []string{},
		}
		model, provider, toolsets := "", "", []string{}
		if data, err := readFileLimited(filepath.Join(dir, "config.yaml"), limits.MaxBytes); err == nil {
			model, provider, toolsets = extractConfigFacts(data)
		}
		cand.Attributes["model"] = red.RedactString(model)
		cand.Attributes["provider"] = red.RedactString(provider)
		if len(toolsets) > 0 {
			cand.Attributes["toolsets"] = red.RedactString(strings.Join(toolsets, ","))
			// declared 工具权限事实（绝不 effective；权威源解析另行完成）
			for _, toolset := range toolsets {
				batch.PermissionFacts = append(batch.PermissionFacts, &protocol.PermissionFact{
					Subject:    &protocol.Subject{Type: "agent_asset", ID: cand.CandidateID},
					Domain:     "tool",
					Action:     "tool.use",
					Resource:   &protocol.Resource{Type: "toolset", Value: red.RedactString(toolset)},
					Effect:     "allow",
					State:      "declared",
					Authority:  "hermes-profile",
					EvidenceIDs: []string{},
				})
			}
		}

		// 把候选的证据引用回填到其 declared 权限事实（contract §4）
		for _, pf := range batch.PermissionFacts {
			if pf.Subject != nil && pf.Subject.ID == cand.CandidateID && len(pf.EvidenceIDs) == 0 {
				pf.EvidenceIDs = cand.EvidenceIDs
			}
		}
		for _, inc := range sc.Include {
			if protocol.IsEnvFile(inc) {
				continue // .env handled by the secret_ref pass below
			}
			full := filepath.Join(dir, inc)
			if !profileFiles[inc] {
				continue
			}
			if escaped, _ := symlinkEscapes(dir, full); escaped {
				fmt.Fprintf(os.Stderr, "hermes: skipping %s: symlink escapes profile dir\n", full)
				continue
			}
			ev := &protocol.Evidence{
				EvidenceID:       "ev:hermes:" + base + ":" + inc,
				SourceType:       "manifest",
				SourceLocator:    red.RedactString(base + "/" + inc), // 脱敏相对路径
				SubjectRef:       strptr(cand.CandidateID),
				ObservedAt:       now,
				CollectedAt:      now,
				ConnectorVersion: connectorVersion,
				RedactionProfile: protocol.RedactionProfile,
				Classification:   classifyManifest(inc),
			}
			data, err := readFileLimited(full, limits.MaxBytes)
			if err != nil {
				fmt.Fprintf(os.Stderr, "hermes: read %s: %v\n", full, err)
				continue
			}
			// Redaction gate: the content must be redactable before we carry
			// any derived field (content_hash is not reversible, but the gate
			// protects future payload uploads).
			if _, err := red.RedactFileContent(inc, data); err != nil {
				return protocol.EvidenceBatch{}, err
			}
			if remaining := limits.MaxBytes - readBytes; int64(len(data)) > remaining {
				// Contract §4: oversized files are truncated within limits and
				// flagged, never read fully.
				fmt.Fprintf(os.Stderr, "hermes: %s exceeds remaining byte budget; truncating scan\n", full)
				batch.Truncated = true
				if remaining > 0 {
					ev.ContentHash = protocol.ContentHash(data[:remaining])
					cand.EvidenceIDs = append(cand.EvidenceIDs, ev.EvidenceID)
					batch.Evidence = append(batch.Evidence, ev)
				}
				break
			}
			ev.ContentHash = protocol.ContentHash(data)
			readBytes += int64(len(data))
			cand.EvidenceIDs = append(cand.EvidenceIDs, ev.EvidenceID)
			batch.Evidence = append(batch.Evidence, ev)
		}

		// .env / .env.*: NEVER read. A secret_ref evidence records only the
		// file name and size (task spec; contract §4).
		var envNames []string
		for name := range profileFiles {
			if protocol.IsEnvFile(name) {
				envNames = append(envNames, name)
			}
		}
		sort.Strings(envNames)
		for _, name := range envNames {
			full := filepath.Join(dir, name)
			fi, err := os.Stat(full)
			if err != nil {
				fmt.Fprintf(os.Stderr, "hermes: stat %s: %v\n", full, err)
				continue
			}
			ev := &protocol.Evidence{
				EvidenceID:       "ev:hermes:" + base + ":" + name,
				SourceType:       "manifest",
				SourceLocator:    red.RedactString(base + "/" + name),
				SubjectRef:       strptr(cand.CandidateID),
				ObservedAt:       now,
				CollectedAt:      now,
				ConnectorVersion: connectorVersion,
				RedactionProfile: protocol.RedactionProfile,
				Classification:   "secret_ref",
				// content = 文件名 + size 的唯一可哈希表示，绝不包含正文
				ContentHash: protocol.ContentHash([]byte(fmt.Sprintf("env-file:%s:%d", name, fi.Size()))),
			}
			cand.EvidenceIDs = append(cand.EvidenceIDs, ev.EvidenceID)
			batch.Evidence = append(batch.Evidence, ev)
		}

		if len(cand.EvidenceIDs) == 0 {
			continue // no readable evidence: no candidate (keeps batches reference-valid)
		}
		batch.Candidates = append(batch.Candidates, cand)
		scannedDirs = append(scannedDirs, dir)
		profiles++
	}

	batch.Cursor = computeCursor(scannedDirs)
	lastCursor = batch.Cursor
	return batch, nil
}

// classifyManifest maps a manifest file to an evidence classification.
func classifyManifest(name string) string {
	switch name {
	case "SOUL.md":
		return "confidential"
	default:
		return "internal"
	}
}

// healthOp reports whether the default profiles root exists.
func healthOp() protocol.HealthReport {
	dir := protocol.ExpandHome("~/.hermes/profiles")
	_, err := os.Stat(dir)
	dep := protocol.DependencyHealth{Name: "hermes_profiles", OK: err == nil}
	if err != nil {
		dep.Message = fmt.Sprintf("default profiles dir %s not found", dir)
	}
	return protocol.HealthReport{Version: connectorVersion, Dependencies: []protocol.DependencyHealth{dep}}
}

// extractConfigFacts extracts model.default, provider and platform_toolsets
// keys from config.yaml WITHOUT a YAML parser (stdlib only). Best-effort and
// conservative: anything it cannot parse confidently is ignored, and raw
// lines are never emitted. Known limitation: inline comments and multi-line
// scalars are not fully supported.
func extractConfigFacts(data []byte) (model, provider string, toolsets []string) {
	lines := strings.Split(string(data), "\n")
	inModel := false
	inToolsets := false
	seenToolsets := make(map[string]bool)
	for _, raw := range lines {
		line := strings.TrimRight(raw, "\r")
		trimmed := strings.TrimSpace(line)
		if trimmed == "" || strings.HasPrefix(trimmed, "#") {
			continue
		}
		indent := len(line) - len(strings.TrimLeft(line, " "))
		if indent == 0 {
			inModel = false
			inToolsets = false
		}
		switch {
		case trimmed == "model:":
			inModel = true
			inToolsets = false
		case inModel && strings.HasPrefix(trimmed, "default:"):
			model = yamlScalar(strings.TrimPrefix(trimmed, "default:"))
		case indent == 0 && strings.HasPrefix(trimmed, "provider:"):
			provider = yamlScalar(strings.TrimPrefix(trimmed, "provider:"))
		case indent == 0 && trimmed == "platform_toolsets:":
			inToolsets = true
			inModel = false
		case inToolsets && indent > 0 && strings.HasPrefix(trimmed, "-"):
			key := yamlScalar(strings.TrimPrefix(trimmed, "-"))
			if i := strings.Index(key, ":"); i >= 0 {
				key = strings.TrimSpace(key[i+1:]) // "- name: foo" → "foo"
			}
			if key != "" {
				seenToolsets[key] = true
			}
		}
	}
	for k := range seenToolsets {
		toolsets = append(toolsets, k)
	}
	sort.Strings(toolsets)
	return model, provider, toolsets
}

// yamlScalar trims a YAML scalar: surrounding quotes and a trailing
// " #comment" (approximation; noted limitation above).
func yamlScalar(v string) string {
	v = strings.TrimSpace(v)
	if i := strings.Index(v, " #"); i >= 0 {
		v = strings.TrimSpace(v[:i])
	}
	if len(v) >= 2 && ((v[0] == '"' && v[len(v)-1] == '"') || (v[0] == '\'' && v[len(v)-1] == '\'')) {
		v = v[1 : len(v)-1]
	}
	return v
}

// readFileLimited reads at most maxBytes (contract §4: oversized files are
// truncated within the limit).
func readFileLimited(path string, maxBytes int64) ([]byte, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	return io.ReadAll(io.LimitReader(f, maxBytes))
}

// globDirs returns the existing directories matched by pattern (or the plain
// path itself when it has no glob characters). Missing paths yield no dirs.
func globDirs(pattern string) ([]string, error) {
	if strings.ContainsAny(pattern, "*?[{") {
		matches, err := filepath.Glob(pattern)
		if err != nil {
			return nil, err
		}
		var out []string
		for _, m := range matches {
			if fi, err := os.Stat(m); err == nil && fi.IsDir() {
				out = append(out, m)
			}
		}
		return out, nil
	}
	if fi, err := os.Stat(pattern); err == nil && fi.IsDir() {
		return []string{pattern}, nil
	}
	return nil, nil
}

// symlinkEscapes reports whether p resolves (through symlinks) outside root.
// Contract §4 negative test: symlinks inside the scope pointing outside it
// must be rejected or flagged — we reject (skip) and log to stderr.
func symlinkEscapes(root, p string) (bool, error) {
	rp, err := filepath.EvalSymlinks(p)
	if err != nil {
		return false, err
	}
	rr, err := filepath.EvalSymlinks(root)
	if err != nil {
		return false, err
	}
	rel, err := filepath.Rel(rr, rp)
	if err != nil {
		return false, err
	}
	return rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)), nil
}

// computeCursor builds a deterministic cursor from the scanned profiles
// (stable per content, not per wall-clock — contract: 增量依据必须稳定).
func computeCursor(dirs []string) string {
	h := sha256.New()
	for _, d := range dirs {
		h.Write([]byte(d))
		h.Write([]byte{0})
		if data, err := readFileLimited(filepath.Join(d, "config.yaml"), 16*1024*1024); err == nil {
			h.Write([]byte(protocol.ContentHash(data)))
		}
		h.Write([]byte{0})
	}
	return "hermes-cursor:" + hex.EncodeToString(h.Sum(nil))
}

func dedupeStrings(in []string) []string {
	seen := make(map[string]bool, len(in))
	out := make([]string, 0, len(in))
	for _, s := range in {
		if !seen[s] {
			seen[s] = true
			out = append(out, s)
		}
	}
	return out
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

func strptr(s string) *string { return &s }
