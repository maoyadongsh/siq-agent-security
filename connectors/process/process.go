// process Connector（connector-protocol.v1.md）：主机进程列表发现源（运行级发现）。
//
// 发现策略（P1-4 发现源扩展）：枚举 `ps -eo pid,ppid,comm,args --no-headers`，
// 按 comm/args 中的已知框架关键词（hermes/openclaw/piagent→pi/workbuddy/dify，
// 置信度 0.8）与通用智能体信号（ollama/langchain/mcp-server/uvicorn/agent 等，
// 置信度 0.6，framework "unknown"）分类候选；无信号进程跳过，不产生候选噪音。
// 与 docker 一样不需要 scope：空 scope 合法。
//
// 安全边界（安全红线）：
//   - args 可能携带 token/密钥：任何输出字段都不得包含完整 args；
//     关键词匹配只在本进程内完成，attributes 只保留 comm、匹配到的关键词与
//     args 的 sha256 截断摘要（前 16 hex）；
//   - PID 不稳定，不作为身份：CandidateID 用 comm + args 哈希前 8 位；
//   - 路径与属性经 protocol.Redactor 脱敏并截断；
//   - 不使用网络（network_access: false）；
//   - ps 二进制缺失或执行失败时显式报错（unsupported/internal_error），
//     形成显式覆盖缺口而非静默漏报；ps 输出超过字节预算时显式截断
//     （batch.Truncated），不回退到默认大小继续处理。
package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"sort"
	"strconv"
	"strings"
	"time"

	"siq-agent-security/edge/agent/protocol"
)

const connectorVersion = "0.1.0"

// 单批默认限额：候选进程数与 ps 原始输出字节数（严格预算，耗尽显式截断）。
const (
	defaultMaxProcesses = 500
	defaultMaxPSBytes   = 4 * 1024 * 1024
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
			fmt.Fprintf(os.Stderr, "process-connector: %v\n", err)
			os.Exit(1)
		}
		return
	}
	fmt.Fprintln(os.Stderr, "usage: process-connector --serve")
	os.Exit(2)
}

// serve runs the NDJSON protocol loop. stdout carries ONLY protocol messages.
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
			batch, err := collectOp(p.Plan, defaultPSRunner)
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

func badRequest(err error) *protocol.ProtocolError {
	return &protocol.ProtocolError{Code: "bad_request", Message: err.Error()}
}

func errToProtocol(err error) *protocol.ProtocolError {
	switch {
	case errors.Is(err, errPSMissing):
		return &protocol.ProtocolError{Code: protocol.CodeUnsupported, Message: err.Error()}
	default:
		return &protocol.ProtocolError{Code: "internal_error", Message: err.Error()}
	}
}

var errPSMissing = errors.New("ps binary not found")

func capabilities() protocol.ConnectorCapabilities {
	return protocol.ConnectorCapabilities{
		Version:             connectorVersion,
		Objects:             []string{"process_list"},
		RequiredPermissions: []string{"exec:ps"},
		DataCategories:      []string{"process_names", "command_digests"},
		MaxOutputBytes:      protocol.DefaultOutputLimitBytes,
		NetworkAccess:       false,
	}
}

// validateScopeOp: 进程发现无文件系统 scope（同 docker）；空 scope 合法，
// 显式给出的 roots 仍走共享安全规则校验。
func validateScopeOp(scope *protocol.Scope) protocol.ValidationResult {
	if scope == nil || len(scope.Roots) == 0 {
		return protocol.ValidationResult{Valid: true}
	}
	if err := protocol.ValidateScopeSafety(scope); err != nil {
		return protocol.ValidationResult{Valid: false, Errors: []string{err.Error()}}
	}
	return protocol.ValidationResult{Valid: true}
}

func planScanOp(p planScanParams) protocol.ScanPlan {
	return protocol.ScanPlan{
		Scope:  p.Scope,
		Cursor: p.Cursor,
		Limits: protocol.CollectLimits{MaxFiles: defaultMaxProcesses, MaxBytes: defaultMaxPSBytes},
	}
}

// psRunner 抽象 ps 调用，便于测试注入 fixture（不依赖真实系统进程）。
type psRunner func(ctx context.Context) ([]byte, error)

// defaultPSRunner 执行 `ps -eo pid,ppid,comm,args --no-headers`。
// ps 缺失 → 显式 errPSMissing；执行失败 → 错误如实上抛，不静默漏报。
func defaultPSRunner(ctx context.Context) ([]byte, error) {
	if _, err := exec.LookPath("ps"); err != nil {
		return nil, errPSMissing
	}
	cmd := exec.CommandContext(ctx, "ps", "-eo", "pid,ppid,comm,args", "--no-headers")
	out, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("ps -eo pid,ppid,comm,args: %w", err)
	}
	return out, nil
}

// processRow 是 ps 输出的一行（args 只在进程内用于匹配，绝不外发）。
type processRow struct {
	pid  string
	ppid string
	comm string
	args string
}

func parsePS(out []byte) []processRow {
	var rows []processRow
	for _, line := range strings.Split(string(out), "\n") {
		fields := strings.Fields(line)
		if len(fields) < 3 {
			continue
		}
		args := fields[2]
		if len(fields) > 3 {
			args = strings.Join(fields[3:], " ")
		}
		rows = append(rows, processRow{pid: fields[0], ppid: fields[1], comm: fields[2], args: args})
	}
	return rows
}

// 已知智能体框架关键词 → framework（高置信启发式，顺序匹配保证确定性）。
var knownFrameworks = []struct {
	keyword   string
	framework string
}{
	{"hermes", "hermes"},
	{"openclaw", "openclaw"},
	{"piagent", "pi"},
	{"workbuddy", "workbuddy"},
	{"dify", "dify"},
}

// 通用智能体运行时信号词（只提示候选，不猜测 framework）。
var agentSignals = []string{
	"ollama", "langchain", "mcp-server", "uvicorn", "agent",
	"llamaindex", "autogen", "crewai",
}

// processClassification 是单个进程的发现分类结果。
type processClassification struct {
	candidate  bool    // 是否进入候选
	framework  string  // 识别出的框架，未知为 "unknown"
	confidence float64 // 发现置信度
	keyword    string  // 匹配到的关键词（可审计，不含 args 原文）
}

// classifyProcess 按 框架关键词 → 通用信号 的顺序分类；匹配只在本进程内完成。
// 无任何信号的进程不是智能体候选（跳过，不产生噪音）。
func classifyProcess(comm, args string) processClassification {
	haystack := strings.ToLower(comm + " " + args)
	for _, kf := range knownFrameworks {
		if strings.Contains(haystack, kf.keyword) {
			return processClassification{candidate: true, framework: kf.framework, confidence: 0.8, keyword: kf.keyword}
		}
	}
	for _, signal := range agentSignals {
		if strings.Contains(haystack, signal) {
			return processClassification{candidate: true, framework: "unknown", confidence: 0.6, keyword: signal}
		}
	}
	return processClassification{}
}

// collectOp 枚举主机进程，分类智能体候选并输出候选 + 证据（每候选一条证据）。
func collectOp(plan protocol.ScanPlan, runner psRunner) (protocol.EvidenceBatch, error) {
	limits := plan.Limits
	if limits.MaxFiles <= 0 {
		limits.MaxFiles = defaultMaxProcesses
	}
	if limits.MaxBytes <= 0 {
		limits.MaxBytes = defaultMaxPSBytes
	}
	timeout := opTimeout
	if timeout <= 0 {
		timeout = time.Duration(protocol.DefaultCollectTimeoutMS) * time.Millisecond
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	out, err := runner(ctx)
	if err != nil {
		return protocol.EvidenceBatch{}, err
	}
	// 严格字节预算：ps 输出超限显式截断到行边界（P1-6 语义），不回退默认大小。
	truncated := false
	if int64(len(out)) > limits.MaxBytes {
		out = out[:limits.MaxBytes]
		if i := bytes.LastIndexByte(out, '\n'); i >= 0 {
			out = out[:i]
		}
		truncated = true
	}

	rows := parsePS(out)
	// ppid → comm 快照内解析，用于 ppid_comm 属性（父进程不在快照则省略）。
	commByPID := make(map[string]string, len(rows))
	for _, row := range rows {
		commByPID[row.pid] = row.comm
	}

	batch := protocol.EvidenceBatch{
		Candidates: []*protocol.Candidate{},
		Evidence:   []*protocol.Evidence{},
		Truncated:  truncated,
	}
	now := time.Now().UTC().Format(time.RFC3339)
	red := protocol.NewRedactor()
	var ids []string

	for _, row := range rows {
		cls := classifyProcess(row.comm, row.args)
		if !cls.candidate {
			continue // 无智能体信号的进程不产生候选噪音
		}
		if int64(len(ids)) >= limits.MaxFiles {
			batch.Truncated = true
			break
		}
		cand, ev := buildObjects(row, commByPID[row.ppid], cls, now, red)
		batch.Candidates = append(batch.Candidates, cand)
		batch.Evidence = append(batch.Evidence, ev)
		ids = append(ids, cand.CandidateID)
	}
	sort.Strings(ids)
	batch.Cursor = "process-cursor:" + hashIDs(ids)
	lastCursor = batch.Cursor
	return batch, nil
}

// buildObjects 输出单个进程候选与其证据。
// 安全红线：args 原文不进入任何字段——attributes 只有 comm、匹配关键词、
// args 的 sha256 截断摘要；evidence 的 ContentHash 是进程事实哈希（同样无 args 原文）。
func buildObjects(row processRow, ppidComm string, cls processClassification, now string, red *protocol.Redactor) (*protocol.Candidate, *protocol.Evidence) {
	argsSum := sha256.Sum256([]byte(row.args))
	argsHash := hex.EncodeToString(argsSum[:])
	// PID 不稳定，不作为身份：候选身份 = comm + args 哈希前 8 位。
	candidateID := "process_list:" + row.comm + ":" + argsHash[:8]
	evidenceID := "ev:process:" + row.comm + ":" + argsHash[:8]

	attrs := map[string]string{
		"match_keyword":   cls.keyword,
		"args_sha256":     argsHash[:16],
		"discovery_basis": "process_scan",
	}
	if ppidComm != "" {
		attrs["ppid_comm"] = truncate(red.RedactString(ppidComm), 128)
	}
	cand := &protocol.Candidate{
		CandidateID:   candidateID,
		SourceType:    "process_list",
		SourceLocator: "process://" + row.comm + ":" + argsHash[:8],
		DiscoveredAt:  now,
		Name:          truncate(red.RedactString(row.comm), 256),
		Framework:     cls.framework,
		Attributes:    attrs,
		EvidenceIDs:   []string{evidenceID},
		Confidence:    cls.confidence,
	}
	// 进程事实哈希：pid/ppid/comm/摘要/匹配关键词/框架，绝不含 args 原文。
	facts, _ := json.Marshal(map[string]any{
		"pid":           row.pid,
		"ppid":          row.ppid,
		"comm":          row.comm,
		"args_sha256":   argsHash[:16],
		"match_keyword": cls.keyword,
		"framework":     cls.framework,
	})
	ev := &protocol.Evidence{
		EvidenceID:       evidenceID,
		SourceType:       "process",
		SourceLocator:    "process://" + row.comm + ":" + argsHash[:8],
		SubjectRef:       strptr(candidateID),
		ObservedAt:       now,
		CollectedAt:      now,
		CollectorID:      "", // Edge 收包后补齐（合同 §4）
		ConnectorVersion: connectorVersion,
		ContentHash:      protocol.ContentHash(facts),
		RedactionProfile: protocol.RedactionProfile,
		Classification:   "internal",
	}
	return cand, ev
}

// healthOp 报告 ps 二进制可用性（缺失时 dependency 显式 unavailable）。
func healthOp() protocol.HealthReport {
	dep := protocol.DependencyHealth{Name: "ps_binary", OK: true}
	if _, err := exec.LookPath("ps"); err != nil {
		dep.OK = false
		dep.Message = "ps binary not found in PATH"
	}
	return protocol.HealthReport{Version: connectorVersion, Dependencies: []protocol.DependencyHealth{dep}}
}

func hashIDs(ids []string) string {
	h := sha256.New()
	for _, id := range ids {
		h.Write([]byte(id))
		h.Write([]byte{0})
	}
	return hex.EncodeToString(h.Sum(nil))
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

func strptr(s string) *string { return &s }
