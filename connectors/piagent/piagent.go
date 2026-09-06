// Command piagent-connector is the PiAgent Profile Connector
// (connector-protocol.v1.md). It discovers PiAgent ("pi" framework)
// installations under the well-known root ~/.piagent (or explicit scope
// roots) and emits deterministic candidates + evidence.
//
// 约定布局（fixture 驱动，应用级发现）：
//
//	<root>/config.yaml            全局配置（只提取白名单标量：model 默认值）
//	<root>/agents.json            {"agents":[{"id","name","model","workspace"}]}
//	<root>/agents/<id>/SOUL.md    可选人格文件（只探测存在性，不读正文）
//
// 安全边界（contract §4 / 安全不变量）：
//   - 绝不采集 secret 值：agents.json 只解码白名单字段 id/name/model/workspace，
//     apiKey/token 等字段根本不进入结构体；config.yaml 只提取 model 标量；
//     .env / secrets/ / keys/ 绝不读取正文，只记 name+size 的 secret_ref evidence。
//   - 符号链接逃逸 scope 的文件/目录一律跳过并写 stderr 诊断。
//   - 文件内容不出本进程（payload_ref 恒空）：只输出内容哈希与脱敏属性；
//     路径与属性经 protocol.Redactor 脱敏并截断。
//   - 字节预算严格模式：readFileLimited 预算耗尽返回 errBudgetExhausted 并置
//     batch.Truncated，禁止回退默认大小继续读取（对齐 directory connector）。
//   - 根目录不存在 = 未安装，产出空批次而非错误；agents.json 畸形 = 显式报错，
//     不得静默漏报。
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

// defaultRoot 是众所周知安装根（参照 hermes connector 的默认根模式）。
const defaultRoot = "~/.piagent"

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
			fmt.Fprintf(os.Stderr, "piagent-connector: %v\n", err)
			os.Exit(1)
		}
		return
	}
	fmt.Fprintln(os.Stderr, "usage: piagent-connector --serve")
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
	msg := err.Error()
	switch {
	case strings.Contains(msg, "empty scope"):
		return &protocol.ProtocolError{Code: protocol.CodeScopeInvalid, Message: msg}
	default:
		return &protocol.ProtocolError{Code: "internal_error", Message: msg}
	}
}

func capabilities() protocol.ConnectorCapabilities {
	return protocol.ConnectorCapabilities{
		Version:             connectorVersion,
		Objects:             []string{"piagent_profile"},
		RequiredPermissions: []string{"read:" + protocol.ExpandHome(defaultRoot)},
		DataCategories:      []string{"config_names", "model_names"},
		MaxOutputBytes:      protocol.DefaultOutputLimitBytes,
		NetworkAccess:       false,
	}
}

// validateScopeOp implements validate_scope. Contract §4: 空 scope 必须拒绝
// （plan/collect 可替换为默认众所周知根，但对“什么都没有”的显式校验无效）。
// 显式 roots 走共享安全规则 ValidateScopeSafety。
func validateScopeOp(scope *protocol.Scope) protocol.ValidationResult {
	errs := validateScope(scope)
	return protocol.ValidationResult{Valid: len(errs) == 0, Errors: errs}
}

func validateScope(scope *protocol.Scope) []string {
	if scope == nil || len(scope.Roots) == 0 {
		return []string{"empty scope: no roots（validate_scope 必须显式给出 roots；默认根仅由 plan/collect 替换）"}
	}
	if err := protocol.ValidateScopeSafety(scope); err != nil {
		return []string{err.Error()}
	}
	return nil
}

// planScanOp: 空 scope 替换为默认根 ~/.piagent；显式 roots 先过
// ValidateScopeSafety（scope 显式覆盖模式）。
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

// effectiveScope substitutes the default well-known root when none was given.
func effectiveScope(s *protocol.Scope) *protocol.Scope {
	if s == nil || len(s.Roots) == 0 {
		return &protocol.Scope{Roots: []string{defaultRoot}}
	}
	out := *s
	return &out
}

// agentsManifest 是 agents.json 的解码投影。安全红线：只声明白名单字段
// id/name/model/workspace —— apiKey/token 等字段的值根本不进入内存投影，
// 更不可能出现在任何输出里（参照 docker connector 不声明 Env 的做法）。
type agentsManifest struct {
	Agents []struct {
		ID        string `json:"id"`
		Name      string `json:"name"`
		Model     string `json:"model"`
		Workspace string `json:"workspace"`
	} `json:"agents"`
}

// collectOp implements collect: 安装发现 + evidence 生成。
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
	now := time.Now().UTC().Format(time.RFC3339)
	red := protocol.NewRedactor()

	// 展开 roots（支持单个尾部 /* glob，与 ValidateScopeSafety 约定一致）。
	var roots []string
	for _, raw := range sc.Roots {
		root := strings.TrimSpace(protocol.ExpandHome(raw))
		matches, err := globDirs(root)
		if err != nil {
			return protocol.EvidenceBatch{}, fmt.Errorf("root %q: %w", raw, err)
		}
		roots = append(roots, matches...)
	}
	roots = dedupeStrings(roots)
	sort.Strings(roots)

	batch := protocol.EvidenceBatch{
		Candidates: []*protocol.Candidate{},
		Evidence:   []*protocol.Evidence{},
	}
	var readBytes int64
	profiles := 0

	// readBudget 按剩余预算严格读取文件：预算耗尽返回 errBudgetExhausted，
	// 文件被预算截断时 truncated=true（调用方必须显式标注，不得误当完整内容）。
	readBudget := func(path string) (data []byte, truncated bool, err error) {
		remaining := limits.MaxBytes - readBytes
		if remaining <= 0 {
			return nil, false, errBudgetExhausted
		}
		data, err = readFileLimited(path, remaining)
		if err != nil {
			return nil, false, err
		}
		readBytes += int64(len(data))
		if fi, serr := os.Stat(path); serr == nil && fi.Size() > int64(len(data)) {
			truncated = true
		}
		return data, truncated, nil
	}

	rootSecrets := map[string][]*protocol.Evidence{} // root → 根级 secret_ref evidence
rootsLoop:
	for _, root := range roots {
		if opTimeout > 0 && time.Since(start) > opTimeout {
			batch.Truncated = true
			break
		}
		manifestPath := filepath.Join(root, "agents.json")
		if _, err := os.Stat(manifestPath); err != nil {
			// agents.json 不存在：该根无清单可解析（未安装/非 piagent 根），
			// 不是错误，静默 continue 前仍记录根级 secret_ref（如有候选可挂载）。
			collectRootSecrets(root, root, red, now, rootSecrets)
			continue
		}
		if escaped, _ := symlinkEscapes(root, manifestPath); escaped {
			fmt.Fprintf(os.Stderr, "piagent: skipping %s: symlink escapes scope\n", manifestPath)
			continue
		}
		data, cut, err := readBudget(manifestPath)
		if errors.Is(err, errBudgetExhausted) {
			batch.Truncated = true
			break
		}
		if err != nil {
			fmt.Fprintf(os.Stderr, "piagent: read %s: %v\n", manifestPath, err)
			continue
		}
		if cut {
			// 清单被预算截断：无法区分“畸形”与“被切断”，按截断处理而非误报畸形。
			batch.Truncated = true
			continue
		}
		var manifest agentsManifest
		if err := json.Unmarshal(data, &manifest); err != nil {
			// 畸形清单必须显式报错，不得静默漏报（覆盖缺口显式化）。
			return protocol.EvidenceBatch{}, fmt.Errorf("piagent: parse %s: %w", manifestPath, err)
		}

		// config.yaml 存在才解析：只提取白名单标量 model（全局默认），
		// apiKey/token 类字段绝不进入输出。
		defaultModel := ""
		cfgPath := filepath.Join(root, "config.yaml")
		if _, err := os.Stat(cfgPath); err == nil {
			if escaped, _ := symlinkEscapes(root, cfgPath); escaped {
				fmt.Fprintf(os.Stderr, "piagent: skipping %s: symlink escapes scope\n", cfgPath)
			} else if cfgData, cfgCut, err := readBudget(cfgPath); errors.Is(err, errBudgetExhausted) {
				batch.Truncated = true
				break
			} else if err != nil {
				fmt.Fprintf(os.Stderr, "piagent: read %s: %v\n", cfgPath, err)
			} else {
				if cfgCut {
					batch.Truncated = true
				}
				defaultModel = extractDefaultModel(cfgData)
			}
		}

		agents := manifest.Agents
		sort.Slice(agents, func(i, j int) bool { return agents[i].ID < agents[j].ID })
		seen := map[string]bool{}
		var rootCandidates []*protocol.Candidate
		for _, a := range agents {
			if int64(profiles) >= limits.MaxFiles {
				batch.Truncated = true
				break
			}
			if opTimeout > 0 && time.Since(start) > opTimeout {
				batch.Truncated = true
				break
			}
			id := strings.TrimSpace(a.ID)
			if id == "" || seen[id] {
				continue // 空 id / 重复 id：去重保证 CandidateID 唯一
			}
			seen[id] = true

			// agents/<id>/ 目录：逃逸则跳过目录内容（候选仍由清单事实产生）。
			agentDir := filepath.Join(root, "agents", id)
			dirOK := false
			if fi, err := os.Stat(agentDir); err == nil && fi.IsDir() {
				if escaped, _ := symlinkEscapes(root, agentDir); escaped {
					fmt.Fprintf(os.Stderr, "piagent: skipping %s: symlink escapes scope\n", agentDir)
				} else {
					dirOK = true
				}
			}

			hasSoul := false
			if dirOK {
				soulPath := filepath.Join(agentDir, "SOUL.md")
				if _, err := os.Stat(soulPath); err == nil {
					if escaped, _ := symlinkEscapes(root, soulPath); escaped {
						fmt.Fprintf(os.Stderr, "piagent: skipping %s: symlink escapes scope\n", soulPath)
					} else {
						hasSoul = true
					}
				}
			}

			model := a.Model
			if model == "" {
				model = defaultModel
			}
			name := a.Name
			if name == "" {
				name = id
			}
			cand := &protocol.Candidate{
				CandidateID:   "piagent:" + id,
				SourceType:    "piagent_profile",
				SourceLocator: truncate(red.RedactString("piagent://agents/"+id), 256),
				DiscoveredAt:  now,
				Name:          truncate(red.RedactString(name), 256),
				Framework:     "pi",
				Confidence:    1.0, // 清单声明 → 确定性发现
				Attributes: map[string]string{
					"workspace": truncate(red.RedactString(a.Workspace), 256),
					"model":     truncate(red.RedactString(model), 256),
					"has_soul":  strconv.FormatBool(hasSoul),
				},
				EvidenceIDs: []string{},
			}

			// 清单事实哈希（白名单字段的规范化 JSON；绝不哈希原始文件，
			// 避免把含 apiKey 的字节序列纳入任何派生计算）。
			facts, _ := json.Marshal(map[string]any{
				"id":        id,
				"name":      name,
				"model":     model,
				"workspace": a.Workspace,
				"has_soul":  hasSoul,
			})
			ev := &protocol.Evidence{
				EvidenceID:       "ev:piagent:" + id,
				SourceType:       "manifest",
				SourceLocator:    truncate(red.RedactString("agents/"+id), 256),
				SubjectRef:       strptr(cand.CandidateID),
				ObservedAt:       now,
				CollectedAt:      now,
				CollectorID:      "", // Edge 收包后补齐（合同 §5）
				ConnectorVersion: connectorVersion,
				ContentHash:      protocol.ContentHash(facts),
				RedactionProfile: protocol.RedactionProfile,
				Classification:   "internal",
			}
			cand.EvidenceIDs = append(cand.EvidenceIDs, ev.EvidenceID)
			batch.Evidence = append(batch.Evidence, ev)

			// agents/<id>/ 下的 .env / secrets/ / keys/：绝不读取正文，
			// 只记 name+size 的 secret_ref evidence（参照 hermes 处理）。
			if dirOK {
				for _, sev := range collectSecretRefs(root, agentDir, red, now, cand.CandidateID) {
					cand.EvidenceIDs = append(cand.EvidenceIDs, sev.EvidenceID)
					batch.Evidence = append(batch.Evidence, sev)
				}
			}

			batch.Candidates = append(batch.Candidates, cand)
			rootCandidates = append(rootCandidates, cand)
			profiles++
		}

		// 根级 secret_ref：挂载到该根第一个候选（contract §4：每条 evidence
		// 必须被同批 candidate 引用；无候选时只能放弃，宁缺毋滥）。
		collectRootSecrets(root, root, red, now, rootSecrets)
		if secs := rootSecrets[root]; len(secs) > 0 && len(rootCandidates) > 0 {
			for _, sev := range secs {
				rootCandidates[0].EvidenceIDs = append(rootCandidates[0].EvidenceIDs, sev.EvidenceID)
				batch.Evidence = append(batch.Evidence, sev)
			}
		}
		if batch.Truncated && (int64(profiles) >= limits.MaxFiles || readBytes >= limits.MaxBytes) {
			break rootsLoop
		}
	}

	batch.Cursor = computeCursor(batch)
	lastCursor = batch.Cursor
	return batch, nil
}

// collectRootSecrets 扫描安装根一级条目中的 .env / secrets / keys，
// 结果暂存到 rootSecrets（等候选确定后再挂载，保证引用有效）。
func collectRootSecrets(root, scopeBase string, red *protocol.Redactor, now string, out map[string][]*protocol.Evidence) {
	if _, seen := out[root]; seen {
		return
	}
	out[root] = nil
	if escaped, _ := symlinkEscapes(scopeBase, root); escaped {
		return
	}
	for _, sev := range secretRefEntries(root, scopeBase, "ev:piagent:_root:", red, now) {
		out[root] = append(out[root], sev)
	}
	// SubjectRef 在挂载到候选时回填。
}

// collectSecretRefs 扫描 dir 一级条目，为每个 secret 指示条目生成
// secret_ref evidence（name+size，绝不读正文），SubjectRef 指向 candidate。
func collectSecretRefs(scopeBase, dir string, red *protocol.Redactor, now, subjectRef string) []*protocol.Evidence {
	evs := secretRefEntries(dir, scopeBase, "ev:piagent:"+strings.TrimPrefix(subjectRef, "piagent:")+":", red, now)
	for _, ev := range evs {
		ev.SubjectRef = strptr(subjectRef)
	}
	return evs
}

// secretRefEntries 返回 dir 下 .env* / secrets / keys 条目的 secret_ref
// evidence（未挂 SubjectRef）。条目本身若是逃逸符号链接则跳过。
func secretRefEntries(dir, scopeBase, idPrefix string, red *protocol.Redactor, now string) []*protocol.Evidence {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil
	}
	var names []string
	for _, e := range entries {
		name := e.Name()
		if protocol.IsEnvFile(name) || name == "secrets" || name == "keys" {
			names = append(names, name)
		}
	}
	sort.Strings(names)
	var out []*protocol.Evidence
	for _, name := range names {
		full := filepath.Join(dir, name)
		if escaped, _ := symlinkEscapes(scopeBase, full); escaped {
			fmt.Fprintf(os.Stderr, "piagent: skipping %s: symlink escapes scope\n", full)
			continue
		}
		fi, err := os.Stat(full)
		if err != nil {
			continue
		}
		rel, _ := filepath.Rel(scopeBase, full)
		out = append(out, &protocol.Evidence{
			EvidenceID:       idPrefix + name,
			SourceType:       "manifest",
			SourceLocator:    truncate(red.RedactString(rel), 256),
			ObservedAt:       now,
			CollectedAt:      now,
			ConnectorVersion: connectorVersion,
			RedactionProfile: protocol.RedactionProfile,
			Classification:   "secret_ref",
			// content = 名称 + size 的唯一可哈希表示，绝不包含正文
			ContentHash: protocol.ContentHash([]byte(fmt.Sprintf("secret-ref:%s:%d", rel, fi.Size()))),
		})
	}
	return out
}

// extractDefaultModel 从 config.yaml 提取顶层 model 标量（无 YAML 依赖，
// 标准库最佳-effort 解析，对齐 hermes extractConfigFacts 的白名单思路）：
// 只识别顶层 "model:" 键，其他键（尤其 apiKey/token）一律忽略。
func extractDefaultModel(data []byte) string {
	for _, raw := range strings.Split(string(data), "\n") {
		line := strings.TrimRight(raw, "\r")
		trimmed := strings.TrimSpace(line)
		if trimmed == "" || strings.HasPrefix(trimmed, "#") {
			continue
		}
		indent := len(line) - len(strings.TrimLeft(line, " "))
		if indent == 0 && strings.HasPrefix(trimmed, "model:") {
			return yamlScalar(strings.TrimPrefix(trimmed, "model:"))
		}
	}
	return ""
}

// yamlScalar trims a YAML scalar: surrounding quotes and a trailing
// " #comment"（近似实现，与 hermes connector 保持一致的限制）。
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

// healthOp 报告默认众所周知根是否存在（未安装不是错误，OK=false 如实上报）。
func healthOp() protocol.HealthReport {
	dir := protocol.ExpandHome(defaultRoot)
	_, err := os.Stat(dir)
	dep := protocol.DependencyHealth{Name: "piagent_root", OK: err == nil}
	if err != nil {
		dep.Message = fmt.Sprintf("default piagent root %s not found", dir)
	}
	return protocol.HealthReport{Version: connectorVersion, Dependencies: []protocol.DependencyHealth{dep}}
}

// errBudgetExhausted: 剩余字节预算为 0 时的显式结果（对齐 directory P1-6）。
// 预算耗尽必须表现为 truncated/skipped，禁止回退到默认大小继续读取。
var errBudgetExhausted = errors.New("byte budget exhausted")

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
// Contract §4 negative test: 逃逸符号链接必须拒绝 —— 跳过并写 stderr。
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

// globDirs returns the existing directories matched by pattern (or the plain
// path itself when it has no glob characters). Missing paths yield no dirs —
// 未安装表现为空结果而非错误。
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

// computeCursor builds a deterministic cursor from the batch（候选 ID +
// evidence 内容哈希，稳定于内容而非墙钟 —— 增量依据必须稳定）。
func computeCursor(batch protocol.EvidenceBatch) string {
	h := sha256.New()
	for _, c := range batch.Candidates {
		h.Write([]byte(c.CandidateID))
		h.Write([]byte{0})
	}
	for _, ev := range batch.Evidence {
		h.Write([]byte(ev.EvidenceID))
		h.Write([]byte(ev.ContentHash))
		h.Write([]byte{0})
	}
	return "piagent-cursor:" + hex.EncodeToString(h.Sum(nil))
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
