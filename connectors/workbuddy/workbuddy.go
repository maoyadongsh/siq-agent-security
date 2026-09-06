// Command workbuddy-connector is the WorkBuddy Install Connector
// (connector-protocol.v1.md). It discovers WorkBuddy agent installations at
// the application level: the conventional layout is ~/.workbuddy/ containing
// config.yaml + buddies.json ({"buddies": [{"id","name","role","skills"}]}).
// The default root is ~/.workbuddy; explicit scope roots override it (and are
// validated with protocol.ValidateScopeSafety).
//
// Security boundaries (task spec P1-4 / contract §4):
//   - buddies.json is decoded into a whitelist struct that has ONLY
//     id/name/role/skills fields: apiKey/token and any other key can never
//     reach the output (same pattern as the docker connector's Env-less
//     inspect struct).
//   - config.yaml is NEVER read (it may carry apiKey values): only its
//     existence is stat'ed into the has_config attribute.
//   - .env / secret files are NEVER read.
//   - paths and attribute values pass through protocol.Redactor and are
//     truncated; file content never leaves this process — only fact hashes.
//   - symlinks escaping the install dir are skipped with a stderr diagnostic.
//   - reads go through readFileLimited under a strict byte budget: budget
//     exhaustion is an explicit errBudgetExhausted + batch.Truncated, never a
//     silent fallback.
//   - WorkBuddy not installed (default root missing) yields an empty batch,
//     not an error; a malformed buddies.json is skipped with a stderr
//     diagnostic — never silently misreported as a valid install.
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

// defaultRoot 是默认安装根（任务规格：默认 ~/.workbuddy，scope 显式 roots 覆盖）。
const defaultRoot = "~/.workbuddy"

// buddiesFileName / configFileName 是约定布局下的固定文件名。
const (
	buddiesFileName = "buddies.json"
	configFileName  = "config.yaml"
)

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
			fmt.Fprintf(os.Stderr, "workbuddy-connector: %v\n", err)
			os.Exit(1)
		}
		return
	}
	fmt.Fprintln(os.Stderr, "usage: workbuddy-connector --serve")
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
			plan, err := planScanOp(p)
			if err != nil {
				perr = errToProtocol(err)
			} else {
				result = plan
			}
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
	if strings.Contains(err.Error(), "scope") {
		return &protocol.ProtocolError{Code: protocol.CodeScopeInvalid, Message: err.Error()}
	}
	return &protocol.ProtocolError{Code: "internal_error", Message: err.Error()}
}

func capabilities() protocol.ConnectorCapabilities {
	return protocol.ConnectorCapabilities{
		Version:             connectorVersion,
		Objects:             []string{"workbuddy_profile"},
		RequiredPermissions: []string{"read:" + protocol.ExpandHome(defaultRoot)},
		DataCategories:      []string{"config_names", "buddy_roles", "skill_names"},
		MaxOutputBytes:      protocol.DefaultOutputLimitBytes,
		NetworkAccess:       false,
	}
}

// validateScopeOp implements validate_scope. Contract §4: an empty scope must
// be rejected (plan/collect may substitute the default root, but an explicit
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

// planScanOp: 显式 roots 必须过 ValidateScopeSafety；空 scope 由默认根
// ~/.workbuddy 顶替（未安装时 collect 返回空批次而非报错）。
func planScanOp(p planScanParams) (protocol.ScanPlan, error) {
	if p.Scope != nil && len(p.Scope.Roots) > 0 {
		if errs := validateScope(p.Scope); len(errs) > 0 {
			return protocol.ScanPlan{}, fmt.Errorf("%s", strings.Join(errs, "; "))
		}
	}
	return protocol.ScanPlan{Scope: effectiveScope(p.Scope), Cursor: p.Cursor, Limits: defaultLimits()}, nil
}

func defaultLimits() protocol.CollectLimits {
	return protocol.CollectLimits{MaxFiles: 200, MaxBytes: 16 * 1024 * 1024}
}

// effectiveScope substitutes the default install root when none was provided.
func effectiveScope(s *protocol.Scope) *protocol.Scope {
	if s == nil || len(s.Roots) == 0 {
		return &protocol.Scope{Roots: []string{defaultRoot}}
	}
	out := *s
	return &out
}

// buddiesFile is the whitelist projection of buddies.json. Security
// invariant: apiKey/token and any other keys are deliberately NOT declared —
// their values can never leave this process.
type buddiesFile struct {
	Buddies []buddy `json:"buddies"`
}

type buddy struct {
	ID     string   `json:"id"`
	Name   string   `json:"name"`
	Role   string   `json:"role"`
	Skills []string `json:"skills"`
}

// collectOp implements collect: WorkBuddy install discovery + evidence.
// Each buddy yields one candidate ("workbuddy:<id>") and one manifest
// evidence whose content hash covers only the whitelisted facts.
func collectOp(plan protocol.ScanPlan) (protocol.EvidenceBatch, error) {
	sc := effectiveScope(plan.Scope)
	// 显式 roots 在 collect 侧再校验一次（纵深防御；Edge 也会校验）。
	if plan.Scope != nil && len(plan.Scope.Roots) > 0 {
		if err := protocol.ValidateScopeSafety(sc); err != nil {
			return protocol.EvidenceBatch{}, err
		}
	}
	limits := plan.Limits
	if limits.MaxFiles <= 0 {
		limits.MaxFiles = defaultLimits().MaxFiles
	}
	if limits.MaxBytes <= 0 {
		limits.MaxBytes = defaultLimits().MaxBytes
	}
	start := time.Now()
	now := time.Now().UTC().Format(time.RFC3339)
	red := protocol.NewRedactor()

	batch := protocol.EvidenceBatch{
		Candidates: []*protocol.Candidate{},
		Evidence:   []*protocol.Evidence{},
	}
	var readBytes int64
	seen := make(map[string]bool) // candidate_id 去重（多 root 可能重复）

roots:
	for _, raw := range sc.Roots {
		dir := strings.TrimSuffix(strings.TrimSpace(protocol.ExpandHome(raw)), "/*")
		fi, err := os.Stat(dir)
		if err != nil || !fi.IsDir() {
			continue // 未安装：空结果，不报错（任务规格）
		}
		base := filepath.Base(dir)

		// has_config 只 stat 不读：config.yaml 可能含 apiKey，内容绝不进输出。
		hasConfig := false
		if cfi, err := os.Stat(filepath.Join(dir, configFileName)); err == nil && !cfi.IsDir() {
			hasConfig = true
		}

		buddiesPath := filepath.Join(dir, buddiesFileName)
		if _, err := os.Stat(buddiesPath); err != nil {
			continue // 无 buddies.json：无可发现 buddy
		}
		// Contract §4 negative test: scope 内符号链接指向 scope 外 —— 跳过并诊断。
		if escaped, _ := symlinkEscapes(dir, buddiesPath); escaped {
			fmt.Fprintf(os.Stderr, "workbuddy: skipping %s: symlink escapes scope\n", buddiesPath)
			continue
		}

		remaining := limits.MaxBytes - readBytes
		data, err := readFileLimited(buddiesPath, remaining)
		if errors.Is(err, errBudgetExhausted) {
			// 预算耗尽：显式截断，不回退默认大小继续读（P1-6 语义）
			batch.Truncated = true
			break
		}
		if err != nil {
			fmt.Fprintf(os.Stderr, "workbuddy: read %s: %v\n", buddiesPath, err)
			continue
		}
		readBytes += int64(len(data))
		// 文件被预算截断：证据不完整必须显式标注，不得误当完整清单解析。
		if fi, statErr := os.Stat(buddiesPath); statErr == nil && fi.Size() > int64(len(data)) {
			fmt.Fprintf(os.Stderr, "workbuddy: %s exceeds byte budget; marking batch truncated\n", buddiesPath)
			batch.Truncated = true
		}

		var parsed buddiesFile
		if err := json.Unmarshal(data, &parsed); err != nil {
			// 畸形 JSON（含预算截断导致的不完整）：显式诊断后跳过，不静默漏报。
			fmt.Fprintf(os.Stderr, "workbuddy: %s: malformed buddies.json: %v\n", buddiesPath, err)
			continue
		}

		for _, b := range parsed.Buddies {
			if b.ID == "" {
				fmt.Fprintf(os.Stderr, "workbuddy: %s: buddy without id skipped\n", buddiesPath)
				continue
			}
			candidateID := "workbuddy:" + b.ID
			if seen[candidateID] {
				continue
			}
			if int64(len(batch.Candidates)) >= limits.MaxFiles {
				batch.Truncated = true
				break roots
			}
			if opTimeout > 0 && time.Since(start) > opTimeout {
				batch.Truncated = true
				break roots
			}
			seen[candidateID] = true

			name := b.Name
			if name == "" {
				name = b.ID
			}
			skills := append([]string(nil), b.Skills...)
			sort.Strings(skills)
			evidenceID := "ev:workbuddy:" + b.ID
			cand := &protocol.Candidate{
				CandidateID:   candidateID,
				SourceType:    "workbuddy_profile",
				SourceLocator: truncate(red.RedactString("workbuddy://"+base+"/"+buddiesFileName+"#"+b.ID), 256),
				DiscoveredAt:  now,
				Name:          truncate(red.RedactString(name), 256),
				Framework:     "workbuddy",
				Confidence:    1.0,
				Attributes: map[string]string{
					"role":       truncate(red.RedactString(b.Role), 256),
					"skills":     truncate(red.RedactString(strings.Join(skills, ",")), 1024),
					"has_config": strconv.FormatBool(hasConfig),
				},
				EvidenceIDs: []string{evidenceID},
			}
			// 清单事实哈希只覆盖白名单字段（apiKey/token 从未进入 parsed）。
			facts, _ := json.Marshal(map[string]any{
				"id":     b.ID,
				"name":   b.Name,
				"role":   b.Role,
				"skills": skills,
			})
			batch.Candidates = append(batch.Candidates, cand)
			batch.Evidence = append(batch.Evidence, &protocol.Evidence{
				EvidenceID:       evidenceID,
				SourceType:       "manifest",
				SourceLocator:    truncate(red.RedactString(base+"/"+buddiesFileName), 256),
				SubjectRef:       strptr(cand.CandidateID),
				ObservedAt:       now,
				CollectedAt:      now,
				CollectorID:      "", // Edge 收包后补齐（合同 §4）
				ConnectorVersion: connectorVersion,
				ContentHash:      protocol.ContentHash(facts),
				RedactionProfile: protocol.RedactionProfile,
				Classification:   "internal",
			})
		}
	}

	batch.Cursor = computeCursor(batch.Candidates, batch.Evidence)
	lastCursor = batch.Cursor
	return batch, nil
}

// computeCursor builds a deterministic cursor from candidate IDs + fact
// hashes (stable per content, not per wall-clock — contract: 增量依据必须稳定).
func computeCursor(cands []*protocol.Candidate, evs []*protocol.Evidence) string {
	h := sha256.New()
	byID := make(map[string]string, len(evs))
	for _, ev := range evs {
		if ev.SubjectRef != nil {
			byID[*ev.SubjectRef] = ev.ContentHash
		}
	}
	ids := make([]string, 0, len(cands))
	for _, c := range cands {
		ids = append(ids, c.CandidateID)
	}
	sort.Strings(ids)
	for _, id := range ids {
		h.Write([]byte(id))
		h.Write([]byte{0})
		h.Write([]byte(byID[id]))
		h.Write([]byte{0})
	}
	return "workbuddy-cursor:" + hex.EncodeToString(h.Sum(nil))
}

// healthOp reports whether the default install root exists.
func healthOp() protocol.HealthReport {
	dir := protocol.ExpandHome(defaultRoot)
	_, err := os.Stat(dir)
	dep := protocol.DependencyHealth{Name: "workbuddy_home", OK: err == nil}
	if err != nil {
		dep.Message = fmt.Sprintf("default install root %s not found", dir)
	}
	return protocol.HealthReport{Version: connectorVersion, Dependencies: []protocol.DependencyHealth{dep}}
}

// errBudgetExhausted: 剩余字节预算为 0 时的显式结果。
// 预算耗尽必须表现为 truncated/skipped，禁止回退到默认大小继续读取。
var errBudgetExhausted = errors.New("byte budget exhausted")

// readFileLimited reads at most maxBytes (contract §4: oversized files are
// truncated within the limit and flagged, never read fully).
func readFileLimited(path string, maxBytes int64) ([]byte, error) {
	if maxBytes <= 0 {
		return nil, errBudgetExhausted
	}
	f, err := openRegular(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return nil, err
	}
	if !st.Mode().IsRegular() {
		return nil, errors.New("non-regular file refused after open")
	}
	return io.ReadAll(io.LimitReader(f, maxBytes))
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

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

func strptr(s string) *string { return &s }
