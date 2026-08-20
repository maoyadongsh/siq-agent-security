// Command systemd-connector is the systemd Connector（connector-protocol.v1.md）。
// 它通过 systemctl CLI（os/exec，无 dbus 依赖）枚举主机上的 service unit，
// 以「unit 名称关键词初筛 + ExecStart 可执行路径再确认」的方式发现智能体
// 运行时服务，输出 candidates + evidence。属于运行级发现源（host 级），
// 不需要文件 scope：空 scope 合法，显式 roots 走共享安全规则校验。
//
// 安全边界：
//   - 绝不采集 secret 值：不读 unit 的环境变量/凭据，只取
//     Id/Description/ActiveState/ExecStart 四个属性；
//   - ExecStart 可能携带敏感参数（token/apiKey 等）：仅「可执行文件路径到首个
//     参数之前」的部分参与关键词再确认；完整命令行必须经 protocol.Redactor
//     脱敏并截断 256 后才允许进入 attributes（exec_summary）；
//   - unit 名与描述同样经 Redactor 脱敏并截断；
//   - systemctl 缺失或执行失败时显式报错（unsupported），形成覆盖缺口而非
//     静默漏报；
//   - 不使用网络（network_access: false）。
package main

import (
	"bufio"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"siq-agent-security/edge/agent/protocol"
)

const connectorVersion = "0.1.0"

var (
	lastCursor string        // most recent collect cursor (checkpoint op)
	opTimeout  time.Duration // from SIQ_CONNECTOR_TIMEOUT_MS
)

// 可注入的 systemctl 调用抽象：测试用 fake runner 替换，不依赖真实 systemd。
var (
	lookPath     = exec.LookPath
	runSystemctl = func(ctx context.Context, args ...string) ([]byte, error) {
		return exec.CommandContext(ctx, "systemctl", args...).Output()
	}
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
			fmt.Fprintf(os.Stderr, "systemd-connector: %v\n", err)
			os.Exit(1)
		}
		return
	}
	fmt.Fprintln(os.Stderr, "usage: systemd-connector --serve")
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

func badRequest(err error) *protocol.ProtocolError {
	return &protocol.ProtocolError{Code: "bad_request", Message: err.Error()}
}

func errToProtocol(err error) *protocol.ProtocolError {
	switch {
	case errors.Is(err, errSystemctlMissing):
		return &protocol.ProtocolError{Code: protocol.CodeUnsupported, Message: err.Error()}
	default:
		return &protocol.ProtocolError{Code: "internal_error", Message: err.Error()}
	}
}

var errSystemctlMissing = errors.New("systemctl binary not found")

func capabilities() protocol.ConnectorCapabilities {
	return protocol.ConnectorCapabilities{
		Version:             connectorVersion,
		Objects:             []string{"systemd"},
		RequiredPermissions: []string{"exec:systemctl"},
		DataCategories:      []string{"unit_names", "unit_states", "exec_summaries"},
		MaxOutputBytes:      protocol.DefaultOutputLimitBytes,
		NetworkAccess:       false,
	}
}

// validateScopeOp: systemd 是 host 级运行发现源，无文件 scope；空 scope 合法，
// 显式 roots 走共享安全规则（如根路径 "/" 必须拒绝）。
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
	return protocol.ScanPlan{Scope: p.Scope, Cursor: p.Cursor, Limits: protocol.CollectLimits{MaxFiles: 100}}
}

// collectOp 枚举全部 service unit，按名称关键词初筛后对命中 unit 取详情并
// 用 exec 路径再确认，每个存活候选产出一个 candidate + 一条 evidence。
func collectOp(plan protocol.ScanPlan) (protocol.EvidenceBatch, error) {
	if _, err := lookPath("systemctl"); err != nil {
		return protocol.EvidenceBatch{}, errSystemctlMissing
	}
	limits := plan.Limits
	if limits.MaxFiles <= 0 {
		limits.MaxFiles = 100
	}
	ctx, cancel := context.WithTimeout(context.Background(), opTimeout)
	defer cancel()

	units, err := listUnits(ctx)
	if err != nil {
		return protocol.EvidenceBatch{}, err
	}
	batch := protocol.EvidenceBatch{
		Candidates: []*protocol.Candidate{},
		Evidence:   []*protocol.Evidence{},
	}
	now := time.Now().UTC().Format(time.RFC3339)
	red := protocol.NewRedactor()
	var ids []string

	for _, unit := range units {
		cls := classifyName(unit)
		if !cls.candidate {
			continue // 无智能体信号的 unit 不产生候选噪音
		}
		if int64(len(ids)) >= limits.MaxFiles {
			batch.Truncated = true
			break
		}
		props, err := showUnit(ctx, unit)
		if err != nil {
			fmt.Fprintf(os.Stderr, "systemd: show %s: %v\n", unit, err)
			continue
		}
		cls = reconfirm(cls, execHead(props.ExecStart))
		if !cls.candidate {
			continue // 再确认失败：名称泛信号但 exec 路径无任何智能体信号
		}
		cand, ev := buildObjects(unit, props, cls, now, red)
		batch.Candidates = append(batch.Candidates, cand)
		batch.Evidence = append(batch.Evidence, ev)
		ids = append(ids, unit)
	}
	sort.Strings(ids)
	batch.Cursor = "systemd-cursor:" + hashIDs(ids)
	lastCursor = batch.Cursor
	return batch, nil
}

// unitProps 是 `systemctl show` 中我们消费的属性投影。
// 安全不变量：刻意不取 Environment 等属性——unit 环境值绝不离开主机。
type unitProps struct {
	ID          string
	Description string
	ActiveState string
	ExecStart   string
}

// listUnits 解析 `systemctl list-unit-files --type=service --no-legend --no-pager`。
// systemctl 执行失败时错误如实上抛（协议错误响应），形成显式覆盖缺口而非静默漏报。
func listUnits(ctx context.Context) ([]string, error) {
	out, err := runSystemctl(ctx, "list-unit-files", "--type=service", "--no-legend", "--no-pager")
	if err != nil {
		return nil, fmt.Errorf("systemctl list-unit-files: %w", err)
	}
	var units []string
	for _, line := range strings.Split(string(out), "\n") {
		fields := strings.Fields(line)
		if len(fields) == 0 {
			continue
		}
		if name := fields[0]; strings.HasSuffix(name, ".service") {
			units = append(units, name)
		}
	}
	return units, nil
}

// showUnit 取单个 unit 的 Id/Description/ActiveState/ExecStart 属性。
func showUnit(ctx context.Context, unit string) (unitProps, error) {
	out, err := runSystemctl(ctx, "show", unit, "-p", "Id,Description,ActiveState,ExecStart", "--no-pager")
	if err != nil {
		return unitProps{}, fmt.Errorf("systemctl show %s: %w", unit, err)
	}
	var props unitProps
	for _, line := range strings.Split(string(out), "\n") {
		k, v, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		switch k {
		case "Id":
			props.ID = v
		case "Description":
			props.Description = v
		case "ActiveState":
			props.ActiveState = v
		case "ExecStart":
			props.ExecStart = v
		}
	}
	return props, nil
}

// 已知智能体框架 unit 名称关键词 → framework（高置信启发式，有序切片防迭代随机）
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

// 通用智能体运行时信号词（只提示候选，不猜测 framework）
var agentSignals = []string{"agent", "ollama", "langchain", "mcp"}

// unitClassification 是单个 unit 的发现分类结果。
type unitClassification struct {
	candidate  bool    // 是否进入候选
	framework  string  // 识别出的框架，未知为 "unknown"
	confidence float64 // 发现置信度
	basis      string  // unit_keyword：发现依据（可审计）
}

// classifyName 按 unit 名称初筛：框架关键词 → 通用信号；无信号不是候选。
func classifyName(name string) unitClassification {
	h := strings.ToLower(name)
	for _, kf := range knownFrameworks {
		if strings.Contains(h, kf.keyword) {
			return unitClassification{candidate: true, framework: kf.framework, confidence: 0.8, basis: "unit_keyword"}
		}
	}
	for _, signal := range agentSignals {
		if strings.Contains(h, signal) {
			return unitClassification{candidate: true, framework: "unknown", confidence: 0.6, basis: "unit_keyword"}
		}
	}
	return unitClassification{candidate: false}
}

// reconfirm 用 ExecStart 的可执行路径（首个参数之前的部分）再确认初筛结果：
// exec 路径命中框架关键词可升级/补足框架识别；名称仅命中通用信号且 exec
// 路径无任何智能体信号时判定为误报，剔除候选。
func reconfirm(cls unitClassification, head string) unitClassification {
	h := strings.ToLower(head)
	for _, kf := range knownFrameworks {
		if strings.Contains(h, kf.keyword) {
			cls.candidate = true
			cls.framework = kf.framework
			cls.confidence = 0.8
			return cls
		}
	}
	if cls.framework != "unknown" {
		return cls // 名称框架命中已足够强
	}
	for _, signal := range agentSignals {
		if strings.Contains(h, signal) {
			return cls // 通用信号再确认通过
		}
	}
	return unitClassification{candidate: false}
}

var execPathRe = regexp.MustCompile(`path=([^ ;]+)`)

// execHead 提取 ExecStart 中「可执行文件路径、首个参数之前」的部分：
// 新版 systemd 为 `{ path=/usr/bin/foo ; argv[]=... }`，退化格式取首个 token。
func execHead(execStart string) string {
	if m := execPathRe.FindStringSubmatch(execStart); m != nil {
		return m[1]
	}
	if f := strings.Fields(execStart); len(f) > 0 {
		return f[0]
	}
	return ""
}

// buildObjects 为一个 unit 产出 candidate 及其 evidence。
// exec 完整命令行先脱敏再截断 256 入 exec_summary；哈希也只覆盖脱敏后事实。
func buildObjects(unit string, props unitProps, cls unitClassification, now string, red *protocol.Redactor) (*protocol.Candidate, *protocol.Evidence) {
	execSummary := truncate(red.RedactString(props.ExecStart), 256)
	evidenceID := "ev:systemd:" + unit

	cand := &protocol.Candidate{
		CandidateID:   "systemd:" + unit,
		SourceType:    "systemd",
		SourceLocator: "systemd://" + unit,
		DiscoveredAt:  now,
		Name:          truncate(red.RedactString(unit), 256),
		Framework:     cls.framework,
		Confidence:    cls.confidence,
		Attributes: map[string]string{
			"active_state":    truncate(red.RedactString(props.ActiveState), 64),
			"description":     truncate(red.RedactString(props.Description), 256),
			"exec_summary":    execSummary,
			"discovery_basis": cls.basis,
		},
		EvidenceIDs: []string{evidenceID},
	}
	// 进入哈希的只有 unit 事实（名称/状态/脱敏后的 exec 摘要），绝无敏感原文。
	facts, _ := json.Marshal(map[string]any{
		"unit":         unit,
		"active_state": props.ActiveState,
		"exec_summary": execSummary,
	})
	ev := &protocol.Evidence{
		EvidenceID:       evidenceID,
		SourceType:       "systemd",
		SourceLocator:    "systemd://" + unit,
		SubjectRef:       strptr(cand.CandidateID),
		ObservedAt:       now,
		CollectedAt:      now,
		ConnectorVersion: connectorVersion,
		ContentHash:      protocol.ContentHash(facts),
		RedactionProfile: protocol.RedactionProfile,
		Classification:   "internal",
	}
	return cand, ev
}

// healthOp 报告 systemctl 可用性（缺失时 dependency 置为不可用）。
func healthOp() protocol.HealthReport {
	dep := protocol.DependencyHealth{Name: "systemctl_binary", OK: true}
	if _, err := lookPath("systemctl"); err != nil {
		dep.OK = false
		dep.Message = "systemctl binary not found in PATH"
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
