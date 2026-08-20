// Command directory-connector is the Controlled Directory Connector
// (connector-protocol.v1.md). It discovers agent manifests (SOUL.md /
// agent.yaml / agent.json / profile.yaml) under explicitly authorized
// directory roots.
//
// Security boundaries (design doc §10.1 / contract §4):
//   - NO default scope: directory scanning requires an explicit
//     administrator-authorized root; empty scope is rejected.
//   - .env / secrets are NEVER read: secret_ref evidence records only name+size.
//   - symlinks escaping the scope are skipped with a stderr warning.
//   - file content never leaves this process; only hashes and redacted
//     attributes are emitted.
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

var defaultIncludes = []string{"SOUL.md", "agent.yaml", "agent.yml", "agent.json", "profile.yaml"}

var (
	lastCursor string
	opTimeout  time.Duration
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
			fmt.Fprintf(os.Stderr, "directory-connector: %v\n", err)
			os.Exit(1)
		}
		return
	}
	fmt.Fprintln(os.Stderr, "usage: directory-connector --serve")
	os.Exit(2)
}

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

type found struct {
	path string
	rel  string
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
				perr = toProtocolError(err)
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
				perr = toProtocolError(err)
			} else {
				result = batch
			}
		}
	case protocol.OpCheckpoint:
		result = map[string]string{"cursor": lastCursor}
	case protocol.OpHealth:
		result = healthOp()
	default:
		perr = &protocol.ProtocolError{Code: protocol.CodeUnsupported, Message: fmt.Sprintf("unknown op: %s", req.Op)}
	}
	if perr != nil {
		resp.OK = false
		resp.Error = perr
	} else {
		resp.Result = result
	}
	return resp
}

func capabilities() protocol.ConnectorCapabilities {
	return protocol.ConnectorCapabilities{
		Version:             connectorVersion,
		Objects:             []string{"agent_manifest"},
		RequiredPermissions: []string{"read:<explicit scope required>"},
		DataCategories:      []string{"manifest_names", "file_hashes"},
		MaxOutputBytes:      protocol.DefaultOutputLimitBytes,
		NetworkAccess:       false,
	}
}

func validateScopeOp(scope *protocol.Scope) protocol.ValidationResult {
	return protocol.ValidationResult{Valid: true, Errors: validateScope(scope)}
}

func validateScope(scope *protocol.Scope) []string {
	if scope == nil || len(scope.Roots) == 0 {
		return []string{"empty scope: no roots（受控目录必须显式授权，本 Connector 无默认范围）"}
	}
	if err := protocol.ValidateScopeSafety(scope); err != nil {
		return []string{err.Error()}
	}
	return nil
}

// planScanOp: 受控目录无默认范围——空范围是错误而非静默替换。
func planScanOp(p planScanParams) (protocol.ScanPlan, error) {
	if errs := validateScope(p.Scope); len(errs) > 0 {
		return protocol.ScanPlan{}, fmt.Errorf("%s", strings.Join(errs, "; "))
	}
	scope := *p.Scope
	if len(scope.Include) == 0 {
		scope.Include = defaultIncludes
	}
	return protocol.ScanPlan{Scope: &scope, Cursor: p.Cursor, Limits: defaultLimits()}, nil
}

func defaultLimits() protocol.CollectLimits {
	return protocol.CollectLimits{MaxFiles: 200, MaxBytes: 16 * 1024 * 1024}
}

func collectOp(plan protocol.ScanPlan) (protocol.EvidenceBatch, error) {
	sc := plan.Scope
	if sc == nil || len(sc.Roots) == 0 {
		return protocol.EvidenceBatch{}, fmt.Errorf("empty scope: no roots")
	}
	if len(sc.Include) == 0 {
		sc.Include = defaultIncludes
	}
	limits := plan.Limits
	if limits.MaxFiles <= 0 {
		limits.MaxFiles = defaultLimits().MaxFiles
	}
	if limits.MaxBytes <= 0 {
		limits.MaxBytes = defaultLimits().MaxBytes
	}
	start := time.Now()
	red := protocol.NewRedactor()
	now := time.Now().UTC().Format(time.RFC3339)

	// 收集候选清单（先走查，后读取，保证限额可控）
	var foundFiles []found
	var skippedDirs int
	for _, raw := range sc.Roots {
		root := strings.TrimSpace(protocol.ExpandHome(raw))
		rootBase := strings.TrimSuffix(root, "/*")
		err := filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
			if err != nil {
				fmt.Fprintf(os.Stderr, "directory-connector: walk %s: %v\n", path, err)
				return nil
			}
			if d.IsDir() {
				name := d.Name()
				if path != root && (strings.HasPrefix(name, ".") || name == "node_modules" || name == ".venv" || name == "vendor") {
					skippedDirs++
					return filepath.SkipDir
				}
				return nil
			}
			base := d.Name()
			for _, inc := range sc.Include {
				if base == inc {
					if escaped, _ := symlinkEscapes(rootBase, path); escaped {
						fmt.Fprintf(os.Stderr, "directory-connector: skipping %s: symlink escapes scope\n", path)
						continue
					}
					rel, _ := filepath.Rel(rootBase, path)
					foundFiles = append(foundFiles, found{path: path, rel: rel})
					break
				}
			}
			return nil
		})
		if err != nil {
			return protocol.EvidenceBatch{}, fmt.Errorf("walk %s: %w", root, err)
		}
	}
	sort.Slice(foundFiles, func(i, j int) bool { return foundFiles[i].rel < foundFiles[j].rel })

	batch := protocol.EvidenceBatch{
		Candidates: []*protocol.Candidate{},
		Evidence:   []*protocol.Evidence{},
	}
	var readBytes int64
	profiles := 0
	for _, f := range foundFiles {
		if int64(profiles) >= limits.MaxFiles {
			batch.Truncated = true
			break
		}
		if opTimeout > 0 && time.Since(start) > opTimeout {
			batch.Truncated = true
			break
		}
		remaining := limits.MaxBytes - readBytes
		if remaining <= 0 {
			// 预算耗尽：显式截断，不读下一文件（P1-6）
			batch.Truncated = true
			break
		}
		data, err := readFileLimited(f.path, remaining)
		if errors.Is(err, errBudgetExhausted) {
			batch.Truncated = true
			break
		}
		if err != nil {
			fmt.Fprintf(os.Stderr, "directory-connector: read %s: %v\n", f.path, err)
			continue
		}
		readBytes += int64(len(data))
		if readBytes > limits.MaxBytes {
			batch.Truncated = true
			break
		}
		// 文件内容被预算截断：证据不完整必须显式标注，不得误当完整内容分析（P1-6）
		contentTruncated := false
		if fi, statErr := os.Stat(f.path); statErr == nil && fi.Size() > int64(len(data)) {
			contentTruncated = true
			batch.Truncated = true
		}

		parentName := filepath.Base(filepath.Dir(f.path))
		if parentName == "." || parentName == string(filepath.Separator) || parentName == "" {
			parentName = "root"
		}
		relHash := sha256.Sum256([]byte(f.rel))
		evidenceID := "ev:directory:" + hex.EncodeToString(relHash[:])[:16]
		cand := &protocol.Candidate{
			CandidateID:   "directory:" + f.rel,
			SourceType:    "directory_manifest",
			SourceLocator: red.RedactString("directory://" + f.rel),
			DiscoveredAt:  now,
			Name:          truncate(red.RedactString(parentName), 256),
			Framework:     "unknown",
			Confidence:    1.0,
			Attributes: map[string]string{
				"manifest":      f.rel,
				"manifest_size": strconv.FormatInt(int64(len(data)), 10),
				// P1-6：证据字节预算语义显式化（bytes_read/bytes_limit/truncated）
				"bytes_read":        strconv.FormatInt(int64(len(data)), 10),
				"bytes_limit":       strconv.FormatInt(remaining, 10),
				"content_truncated": strconv.FormatBool(contentTruncated),
			},
			EvidenceIDs: []string{evidenceID},
		}
		if strings.EqualFold(filepath.Base(f.path), "SOUL.md") {
			cand.Framework = "hermes"
		}
		batch.Candidates = append(batch.Candidates, cand)
		batch.Evidence = append(batch.Evidence, &protocol.Evidence{
			EvidenceID:       evidenceID,
			SourceType:       "manifest",
			SourceLocator:    red.RedactString(f.rel),
			ObservedAt:       now,
			CollectedAt:      now,
			CollectorID:      "", // Edge 收包后补齐（合同 §4）
			ConnectorVersion: connectorVersion,
			ContentHash:      protocol.ContentHash(data),
			RedactionProfile: "siq.redaction.v1",
			Classification:   "internal",
			SubjectRef:       strPtr(cand.CandidateID),
		})
		profiles++
	}
	if len(foundFiles) > 0 {
		lastCursor = "directory-cursor:" + computeCursor(foundFiles, batch.Evidence)
	}
	return batch, nil
}

// computeCursor: 稳定增量游标（相对路径 + 内容哈希，不以墙钟时间为依据）。
func computeCursor(files []found, evidence []*protocol.Evidence) string {
	h := sha256.New()
	byID := map[string]string{}
	for _, ev := range evidence {
		if ev.SubjectRef != nil {
			byID[*ev.SubjectRef] = ev.ContentHash
		}
	}
	for _, f := range files {
		h.Write([]byte(f.rel))
		h.Write([]byte{0})
		h.Write([]byte(byID["directory:"+f.rel]))
		h.Write([]byte{0})
	}
	return hex.EncodeToString(h.Sum(nil))
}

func healthOp() protocol.HealthReport {
	return protocol.HealthReport{Version: connectorVersion, Dependencies: []protocol.DependencyHealth{}}
}

// errBudgetExhausted: 剩余字节预算为 0 时的显式结果（P1-6）。
// 预算耗尽必须表现为 truncated/skipped，禁止回退到默认大小继续读取。
var errBudgetExhausted = errors.New("byte budget exhausted")

func readFileLimited(path string, maxBytes int64) ([]byte, error) {
	if maxBytes <= 0 {
		return nil, errBudgetExhausted
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	data, err := io.ReadAll(io.LimitReader(f, maxBytes))
	if err != nil {
		return nil, err
	}
	return data, nil
}

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

func strPtr(s string) *string {
	return &s
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

func badRequest(err error) *protocol.ProtocolError {
	return &protocol.ProtocolError{Code: protocol.CodeScopeInvalid, Message: err.Error()}
}

func toProtocolError(err error) *protocol.ProtocolError {
	msg := err.Error()
	code := protocol.CodeUnsupported
	switch {
	case strings.Contains(msg, "empty scope"):
		code = protocol.CodeScopeInvalid
	case strings.Contains(msg, "symlink"):
		code = protocol.CodeScopeInvalid
	}
	return &protocol.ProtocolError{Code: code, Message: msg}
}
