// Command mcp-connector 是 MCP server 配置发现 Connector（connector-protocol.v1.md，
// P1-4 发现源扩展）。它读取主流 MCP 客户端的众所周知配置文件
// （~/.cursor/mcp.json、~/.claude.json、~/.claude/mcp.json、
// ~/.windsurf/mcp_config.json、~/.codeium/windsurf/mcp_config.json），
// 解析其中的 mcpServers 对象，把每个 server 作为一个智能体候选（协议级发现源，
// source_type = "mcp_server"）。
//
// 发现策略：
//   - 无 scope 时按"众所周知默认根"模式扫描上述默认配置文件（存在的才读）；
//   - scope 显式给 roots 时改为在每个 root 下找 mcp.json（roots 先经
//     protocol.ValidateScopeSafety 校验）；
//   - 配置文件存在即高置信（confidence 0.9），framework 一律 "unknown"。
//
// 安全边界（设计文档 §10.1 / contract §4）：
//   - server 配置的 env 值绝不采集：只输出变量名列表（env_keys）；命令行参数中
//     与 env 值逐字相同的串也会被替换为 [REDACTED]（防止 --token <值> 夹带）；
//   - command/args 经 protocol.Redactor 脱敏并截断后才进入事实哈希；
//   - url 只保留 scheme://host（去 userinfo/query/fragment，防夹带凭据）；
//   - 畸形 JSON 显式报错（协议错误响应），不得静默漏报；无 mcpServers 键的配置
//     产出空批次，不算错误；
//   - 文件读取走严格字节预算的 readFileLimited：预算耗尽显式 errBudgetExhausted +
//     batch.Truncated，禁止回退默认大小继续读取（P1-6）；
//   - 符号链接逃逸出扫描边界的配置文件跳过并写 stderr 诊断；
//   - 不访问网络（network_access: false）；文件内容不出本进程，只输出哈希与
//     脱敏后的属性。
package main

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"siq-agent-security/edge/agent/protocol"
)

const connectorVersion = "0.1.0"

// wellKnownConfig 是一个众所周知的 MCP 客户端默认配置文件。
type wellKnownConfig struct {
	path   string // "~" 前缀路径，经 protocol.ExpandHome 展开
	client string // cursor|claude|windsurf
}

// defaultConfigs 参照 hermes connector 的"众所周知默认根"模式：无 scope 时
// 只扫描这些路径中实际存在的文件。
var defaultConfigs = []wellKnownConfig{
	{"~/.cursor/mcp.json", "cursor"},
	{"~/.claude.json", "claude"},
	{"~/.claude/mcp.json", "claude"},
	{"~/.windsurf/mcp_config.json", "windsurf"},
	{"~/.codeium/windsurf/mcp_config.json", "windsurf"},
}

var (
	lastCursor string        // 最近一次 collect 的游标（checkpoint op）
	opTimeout  time.Duration // 来自 SIQ_CONNECTOR_TIMEOUT_MS
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
			fmt.Fprintf(os.Stderr, "mcp-connector: %v\n", err)
			os.Exit(1)
		}
		return
	}
	fmt.Fprintln(os.Stderr, "usage: mcp-connector --serve")
	os.Exit(2)
}

// serve 运行 NDJSON 协议循环。stdout 只承载协议消息，诊断写 stderr。
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

func capabilities() protocol.ConnectorCapabilities {
	return protocol.ConnectorCapabilities{
		Version:             connectorVersion,
		Objects:             []string{"mcp_server"},
		RequiredPermissions: []string{"read:<mcp client config files>"},
		DataCategories:      []string{"config_names", "env_key_names"},
		MaxOutputBytes:      protocol.DefaultOutputLimitBytes,
		NetworkAccess:       false,
	}
}

// validateScopeOp：空 scope 必须拒绝（contract §4）；plan/collect 阶段的
// 无 scope 回退到众所周知默认配置文件是另一回事。
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

// planScanOp：scope 显式给出时先校验；无 scope 时不在 plan 里伪造 roots
// （默认目标是文件而非目录，ValidateScopeSafety 只接受目录），collect 阶段
// 自行回退到众所周知默认配置文件。
func planScanOp(p planScanParams) (protocol.ScanPlan, error) {
	if p.Scope != nil && len(p.Scope.Roots) > 0 {
		if errs := validateScope(p.Scope); len(errs) > 0 {
			return protocol.ScanPlan{}, fmt.Errorf("%s", strings.Join(errs, "; "))
		}
	}
	return protocol.ScanPlan{Scope: p.Scope, Cursor: p.Cursor, Limits: defaultLimits()}, nil
}

func defaultLimits() protocol.CollectLimits {
	return protocol.CollectLimits{MaxFiles: 200, MaxBytes: 16 * 1024 * 1024}
}

// configTarget 是一个待解析的 MCP 配置文件。
type configTarget struct {
	path     string // 展开后的绝对路径
	client   string // cursor|claude|windsurf|unknown
	boundary string // 符号链接逃逸检查的边界目录
}

// resolveTargets 决定本次 collect 读哪些配置文件：
// scope 显式给 roots → 每个 root 下找 mcp.json；否则扫描众所周知默认路径。
// 只返回实际存在的常规文件（存在的才读，不存在的静默跳过是默认路径语义，
// 不是漏报——spec：CLI/文件缺失时显式报错或空批次）。
func resolveTargets(scope *protocol.Scope) ([]configTarget, error) {
	var targets []configTarget
	if scope != nil && len(scope.Roots) > 0 {
		if err := protocol.ValidateScopeSafety(scope); err != nil {
			return nil, err
		}
		for _, raw := range scope.Roots {
			root := strings.TrimSuffix(strings.TrimSpace(protocol.ExpandHome(raw)), "/*")
			path := filepath.Join(root, "mcp.json")
			if fi, err := os.Stat(path); err == nil && fi.Mode().IsRegular() {
				targets = append(targets, configTarget{path: path, client: clientForPath(path), boundary: root})
			}
		}
	} else {
		home := protocol.ExpandHome("~")
		for _, wk := range defaultConfigs {
			path := protocol.ExpandHome(wk.path)
			if fi, err := os.Stat(path); err == nil && fi.Mode().IsRegular() {
				targets = append(targets, configTarget{path: path, client: wk.client, boundary: home})
			}
		}
	}
	sort.Slice(targets, func(i, j int) bool { return targets[i].path < targets[j].path })
	return targets, nil
}

// clientForPath 按路径特征推断客户端（scope roots 模式下路径不含众所周知
// 位置时退化为 "unknown"）。
func clientForPath(path string) string {
	lower := strings.ToLower(path)
	switch {
	case strings.Contains(lower, ".cursor"):
		return "cursor"
	case strings.Contains(lower, ".claude"):
		return "claude"
	case strings.Contains(lower, "windsurf"), strings.Contains(lower, ".codeium"):
		return "windsurf"
	default:
		return "unknown"
	}
}

// mcpConfigFile 是 MCP 客户端配置文件的顶层结构（~/.claude.json 同样以
// mcpServers 为键；其他顶层键一律忽略）。
type mcpConfigFile struct {
	MCPServers map[string]mcpServerConfig `json:"mcpServers"`
}

// mcpServerConfig 是单个 server 的配置。安全不变量：Env 的值只在本进程内
// 用于"逐字值防夹带"脱敏，绝不进入任何输出字段。
type mcpServerConfig struct {
	Command string            `json:"command"`
	Args    []string          `json:"args"`
	Env     map[string]string `json:"env"`
	URL     string            `json:"url"`
}

// collectOp 实现 collect：解析目标配置文件，每个 mcpServers 条目产出
// 一个 candidate + 一条 evidence（contract §4：evidence 必须被同批
// candidate 引用）。
func collectOp(plan protocol.ScanPlan) (protocol.EvidenceBatch, error) {
	limits := plan.Limits
	if limits.MaxFiles <= 0 {
		limits.MaxFiles = defaultLimits().MaxFiles
	}
	if limits.MaxBytes <= 0 {
		limits.MaxBytes = defaultLimits().MaxBytes
	}
	start := time.Now()

	targets, err := resolveTargets(plan.Scope)
	if err != nil {
		return protocol.EvidenceBatch{}, err
	}

	batch := protocol.EvidenceBatch{
		Candidates: []*protocol.Candidate{},
		Evidence:   []*protocol.Evidence{},
	}
	now := time.Now().UTC().Format(time.RFC3339)
	red := protocol.NewRedactor()
	var readBytes int64
	var parsed []configTarget

	for _, t := range targets {
		if opTimeout > 0 && time.Since(start) > opTimeout {
			batch.Truncated = true
			break
		}
		// contract §4 负向用例：符号链接逃逸出扫描边界的配置文件跳过。
		if escaped, _ := symlinkEscapes(t.boundary, t.path); escaped {
			fmt.Fprintf(os.Stderr, "mcp-connector: skipping %s: symlink escapes scope\n", t.path)
			continue
		}
		remaining := limits.MaxBytes - readBytes
		if remaining <= 0 {
			// 预算耗尽：显式截断，不读下一文件（P1-6）
			batch.Truncated = true
			break
		}
		data, err := readFileLimited(t.path, remaining)
		if errors.Is(err, errBudgetExhausted) {
			batch.Truncated = true
			break
		}
		if err != nil {
			fmt.Fprintf(os.Stderr, "mcp-connector: read %s: %v\n", t.path, err)
			continue
		}
		readBytes += int64(len(data))
		// 文件被预算截断：不完整 JSON 不做解析猜测，显式截断并停止（P1-6）。
		if fi, statErr := os.Stat(t.path); statErr == nil && fi.Size() > int64(len(data)) {
			fmt.Fprintf(os.Stderr, "mcp-connector: %s truncated by byte budget (%d/%d bytes)\n", t.path, len(data), fi.Size())
			batch.Truncated = true
			break
		}
		var cfg mcpConfigFile
		if err := json.Unmarshal(data, &cfg); err != nil {
			// 畸形 JSON 显式报错：宁可整个 collect 失败也不静默漏报。
			return protocol.EvidenceBatch{}, fmt.Errorf("parse %s: %w", t.path, err)
		}
		parsed = append(parsed, t)

		names := make([]string, 0, len(cfg.MCPServers))
		for name := range cfg.MCPServers {
			names = append(names, name)
		}
		sort.Strings(names)
		for _, name := range names {
			if int64(len(batch.Candidates)) >= limits.MaxFiles {
				batch.Truncated = true
				break
			}
			cand, ev := buildObjects(t, name, cfg.MCPServers[name], now, red)
			batch.Candidates = append(batch.Candidates, cand)
			batch.Evidence = append(batch.Evidence, ev)
		}
		if batch.Truncated {
			break
		}
	}

	if len(parsed) > 0 {
		batch.Cursor = computeCursor(parsed, batch.Evidence)
		lastCursor = batch.Cursor
	}
	return batch, nil
}

// buildObjects 为一个 server 配置条目生成 candidate 与其 evidence。
// 所有进入输出的字段都已脱敏/截断；env 值只在 hashEnvValues 内部使用。
func buildObjects(t configTarget, name string, srv mcpServerConfig, now string, red *protocol.Redactor) (*protocol.Candidate, *protocol.Evidence) {
	secretVals := envValueSet(srv.Env)

	// command/args：Redactor 脱敏 + 逐字 env 值防夹带 + 截断。
	command := scrubSecretValues(red.RedactString(srv.Command), secretVals)
	var redactedArgs []string
	for _, a := range srv.Args {
		redactedArgs = append(redactedArgs, truncate(scrubSecretValues(red.RedactString(a), secretVals), 128))
	}

	envKeys := make([]string, 0, len(srv.Env))
	for k := range srv.Env {
		envKeys = append(envKeys, truncate(red.RedactString(k), 128))
	}
	sort.Strings(envKeys)

	transport := inferTransport(srv)
	sanitizedURL := sanitizeURL(srv.URL)
	commandBase := ""
	if command != "" {
		commandBase = truncate(filepath.Base(command), 128)
	}

	pathHash := sha256.Sum256([]byte(t.path))
	pathHash8 := hex.EncodeToString(pathHash[:])[:8]
	evIDSum := sha256.Sum256([]byte(t.path + "\x00" + name))
	evidenceID := "ev:mcp:" + hex.EncodeToString(evIDSum[:])[:16]
	locator := red.RedactString(t.path)

	attrs := map[string]string{
		"client":          t.client,
		"transport":       transport,
		"env_keys":        strings.Join(envKeys, ","),
		"discovery_basis": "client_config",
		"config_file":     truncate(locator, 512),
	}
	if commandBase != "" {
		attrs["command"] = commandBase
	}
	if sanitizedURL != "" {
		attrs["url"] = sanitizedURL
	}

	cand := &protocol.Candidate{
		CandidateID:   "mcp:" + name + "@" + pathHash8,
		SourceType:    "mcp_server",
		SourceLocator: "mcp://" + locator,
		DiscoveredAt:  now,
		Name:          truncate(red.RedactString(name), 256),
		Framework:     "unknown",
		Confidence:    0.9, // 配置存在即高置信
		Attributes:    attrs,
		EvidenceIDs:   []string{evidenceID},
	}

	// evidence 事实哈希：只含脱敏后的配置事实，绝不含 env 值。
	facts, _ := json.Marshal(map[string]any{
		"server":    name,
		"config":    locator,
		"client":    t.client,
		"transport": transport,
		"command":   commandBase,
		"args":      redactedArgs,
		"env_keys":  envKeys,
		"url":       sanitizedURL,
	})
	ev := &protocol.Evidence{
		EvidenceID:       evidenceID,
		SourceType:       "manifest",
		SourceLocator:    locator,
		SubjectRef:       strPtr(cand.CandidateID),
		ObservedAt:       now,
		CollectedAt:      now,
		CollectorID:      "", // Edge 收包后补齐（合同 §5）
		ConnectorVersion: connectorVersion,
		ContentHash:      protocol.ContentHash(facts),
		RedactionProfile: protocol.RedactionProfile,
		Classification:   "internal",
	}
	return cand, ev
}

// inferTransport 按 url 或 command 推断传输方式：url 含 /sse → sse，
// 其余 url → http，command → stdio，皆无 → unknown。
func inferTransport(srv mcpServerConfig) string {
	if srv.URL != "" {
		if strings.Contains(strings.ToLower(srv.URL), "/sse") {
			return "sse"
		}
		return "http"
	}
	if srv.Command != "" {
		return "stdio"
	}
	return "unknown"
}

// sanitizeURL 只保留 scheme://host：去 userinfo/query/fragment，防夹带凭据。
// 解析失败或无 scheme/host 时返回空串（宁缺毋滥）。
func sanitizeURL(raw string) string {
	if raw == "" {
		return ""
	}
	u, err := url.Parse(raw)
	if err != nil || u.Scheme == "" || u.Host == "" {
		return ""
	}
	return u.Scheme + "://" + u.Host
}

// envValueSet 收集 env 值（长度 ≥4 才有夹带风险），用于逐字防夹带脱敏。
func envValueSet(env map[string]string) map[string]bool {
	set := make(map[string]bool, len(env))
	for _, v := range env {
		if len(v) >= 4 {
			set[v] = true
		}
	}
	return set
}

// scrubSecretValues 把 s 中与任一 env 值逐字相同的串替换为 [REDACTED]
// （防御 --token <env值> 这类参数夹带；Redactor 的正则之外的最后防线）。
func scrubSecretValues(s string, secretVals map[string]bool) string {
	for v := range secretVals {
		if strings.Contains(s, v) {
			s = strings.ReplaceAll(s, v, "[REDACTED]")
		}
	}
	return s
}

// computeCursor：稳定增量游标（配置文件路径 + 各 evidence 事实哈希，
// 不以墙钟时间为依据）。
func computeCursor(targets []configTarget, evidence []*protocol.Evidence) string {
	h := sha256.New()
	byLocator := map[string][]string{}
	for _, ev := range evidence {
		byLocator[ev.SourceLocator] = append(byLocator[ev.SourceLocator], ev.ContentHash)
	}
	for _, t := range targets {
		h.Write([]byte(t.path))
		h.Write([]byte{0})
		hashes := byLocator[t.path]
		sort.Strings(hashes)
		for _, ch := range hashes {
			h.Write([]byte(ch))
			h.Write([]byte{0})
		}
	}
	return "mcp-cursor:" + hex.EncodeToString(h.Sum(nil))
}

// healthOp 报告是否找到任一众所周知 MCP 客户端配置文件。
func healthOp() protocol.HealthReport {
	found := 0
	for _, wk := range defaultConfigs {
		if fi, err := os.Stat(protocol.ExpandHome(wk.path)); err == nil && fi.Mode().IsRegular() {
			found++
		}
	}
	dep := protocol.DependencyHealth{Name: "mcp_client_configs", OK: found > 0}
	if found == 0 {
		dep.Message = "no well-known MCP client config files found"
	}
	return protocol.HealthReport{Version: connectorVersion, Dependencies: []protocol.DependencyHealth{dep}}
}

// errBudgetExhausted：剩余字节预算为 0 时的显式结果（P1-6）。
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
	return io.ReadAll(io.LimitReader(f, maxBytes))
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
	return &protocol.ProtocolError{Code: "bad_request", Message: err.Error()}
}

func toProtocolError(err error) *protocol.ProtocolError {
	msg := err.Error()
	code := "internal_error"
	if strings.Contains(msg, "empty scope") || strings.Contains(msg, "scope root") {
		code = protocol.CodeScopeInvalid
	}
	return &protocol.ProtocolError{Code: code, Message: msg}
}
