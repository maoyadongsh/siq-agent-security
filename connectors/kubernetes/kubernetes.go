// Command kubernetes-connector is the Kubernetes Connector
// (connector-protocol.v1.md, P1-4 发现源扩展). It enumerates ALL pods across
// all namespaces via the kubectl CLI (os/exec; no client-go dependency),
// classifies agent candidates by image/container-name signals plus the
// siq.agent=true pod label, and emits candidates + evidence.
//
// 发现策略（P1-4 运行级发现源）：
//   - `kubectl get pods -A -o json` 一次性枚举全集群 pod（含 initContainers）；
//   - pod label `siq.agent=true` 只是高置信提示/纳管标记（basis=label,
//     confidence=1.0），绝非发现前置条件——未打标签的智能体容器（影子智能体，
//     如 dify/hermes 镜像）必须经启发式信号进入候选；
//   - 已知框架关键词 → heuristic/0.8；通用智能体信号词 → heuristic/0.6；
//     无任何信号的容器跳过，不产生候选噪音。
//
// 安全边界（对齐 directory/docker connector 的不变量）：
//   - 容器 env 值绝不离开本进程：pod JSON 解码结构体刻意不声明 env value
//     字段，只统计变量个数；
//   - candidate attributes 只携带 namespace/container/image(脱敏截断)/label
//     计数/discovery_basis 等摘要；所有字符串经 protocol.Redactor 脱敏；
//   - 每条 evidence 必须被同批 candidate 引用（contract §4）；
//   - kubectl 缺失或执行失败显式报错（覆盖缺口），不得静默漏报；
//   - kubectl 输出走流式解码，字节预算耗尽时优雅截断（Truncated=true，
//     保留已解出的完整 pod）而非整批失败——集群规模不应导致发现整体失能；
//   - network_access: true。kubectl 是本机 CLI 子进程不假，但
//     `kubectl get pods -A` 本身必然通过网络（TCP，常见于连接到独立于本机
//     的 API Server/托管控制面）与 Kubernetes API Server 通信，这与
//     systemd/docker 连接的本机 IPC/Unix socket 有本质区别；声明
//     network_access=false 会误导依赖该字段做网络隔离判断的调用方。
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

// defaultLimits：MaxFiles 语义为「候选容器条数上限」，MaxBytes 为 kubectl
// 单次输出的严格字节预算（本 Connector 无文件读取，预算作用于 pod 清单）。
var defaultLimits = protocol.CollectLimits{MaxFiles: 1000, MaxBytes: protocol.DefaultOutputLimitBytes}

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
			fmt.Fprintf(os.Stderr, "kubernetes-connector: %v\n", err)
			os.Exit(1)
		}
		return
	}
	fmt.Fprintln(os.Stderr, "usage: kubernetes-connector --serve")
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
			batch, err := collectOp(p.Plan, defaultRunner)
			if err != nil {
				perr = errToProtocol(err)
			} else {
				result = batch
			}
		}
	case protocol.OpCheckpoint:
		result = protocol.CursorResult{Cursor: lastCursor}
	case protocol.OpHealth:
		result = healthOp(defaultRunner)
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
	case errors.Is(err, errKubectlMissing):
		// kubectl 不在 PATH：能力缺失是显式覆盖缺口，unsupported 而非静默空批次
		return &protocol.ProtocolError{Code: protocol.CodeUnsupported, Message: err.Error()}
	default:
		return &protocol.ProtocolError{Code: "internal_error", Message: err.Error()}
	}
}

var errKubectlMissing = errors.New("kubectl binary not found")

func capabilities() protocol.ConnectorCapabilities {
	return protocol.ConnectorCapabilities{
		Version:             connectorVersion,
		Objects:             []string{"kubernetes"},
		RequiredPermissions: []string{"exec:kubectl"},
		DataCategories:      []string{"image_names", "container_names", "labels"},
		MaxOutputBytes:      protocol.DefaultOutputLimitBytes,
		// kubectl 子进程本身要连接 Kubernetes API Server（TCP），与本机 IPC
		// 性质的 docker/systemd 连接不同，如实声明为 true（见文件头说明）。
		NetworkAccess: true,
	}
}

// validateScopeOp: kubernetes 无文件系统 scope（同 docker connector）；空 scope
// 合法，显式 roots 仍走共享安全规则校验。
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
	return protocol.ScanPlan{Scope: p.Scope, Cursor: p.Cursor, Limits: defaultLimits}
}

// runner 抽象 kubectl 调用，便于测试注入（fixture 驱动，不依赖真实集群）。
type runner interface {
	// available 报告 kubectl 是否在 PATH。
	available() bool
	// getPods 执行 `kubectl get pods -A -o json`，最多读取 maxBytes+1 字节
	// （防内存放大）；是否命中预算边界由调用方按返回长度与 maxBytes 的关系
	// 判定，getPods 本身不对预算耗尽报错——由调用方决定优雅截断而非整批失败。
	getPods(ctx context.Context, maxBytes int64) ([]byte, error)
}

// defaultRunner 是生产使用的真实 kubectl 执行器。
var defaultRunner runner = execRunner{}

type execRunner struct{}

func (execRunner) available() bool {
	_, err := exec.LookPath("kubectl")
	return err == nil
}

// getPods 读取 kubectl 输出，硬上限 maxBytes+1 字节防内存放大。
// 若真实输出超出预算，读取会在边界处停止（不等于失败）：调用方通过流式
// JSON 解码提取已完整读到的 pod 对象，整批不因集群规模过大而失能
// （P1-6 预算语义显式化：截断是显式、可观测的降级，而非报错清零）。
func (execRunner) getPods(ctx context.Context, maxBytes int64) ([]byte, error) {
	cmd := exec.CommandContext(ctx, "kubectl", "get", "pods", "-A", "-o", "json")
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, fmt.Errorf("kubectl get pods: %w", err)
	}
	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("kubectl get pods: %w", err)
	}
	data, readErr := io.ReadAll(io.LimitReader(stdout, maxBytes+1))
	waitErr := cmd.Wait()
	if readErr != nil {
		return nil, fmt.Errorf("kubectl get pods: read: %w", readErr)
	}
	truncated := int64(len(data)) > maxBytes
	// 预算边界之外提前停止读取时，kubectl 进程常因管道未排空而以非零状态
	// 退出（或被 opTimeout 终止）：这是截断的正常副作用而非真实故障，不
	// 应上抛为错误；只有「未截断却仍执行失败」才是需要如实上报的真实故障。
	if waitErr != nil && !truncated {
		return nil, fmt.Errorf("kubectl get pods: %w", waitErr)
	}
	return data, nil
}

// collectOp 枚举全集群 pod 的容器（含 initContainers），按 P1-4 策略分类并
// 为每个候选容器产出 1 candidate + 1 evidence（每条 evidence 必被引用）。
//
// 预算耗尽处理：旧实现要求 kubectl 完整输出必须 ≤ MaxBytes，否则
// errBudgetExhausted 导致整批采集失败（0 候选）——大集群/大量 pod 的
// 正常场景反而会让发现能力完全失能。现在改为流式解码：读取严格限制在
// MaxBytes+1 字节内，超出部分之前已完整解出的 pod 对象仍然参与分类产出
// candidate，只将 batch.Truncated 置位，不整批报错。
func collectOp(plan protocol.ScanPlan, r runner) (protocol.EvidenceBatch, error) {
	if !r.available() {
		return protocol.EvidenceBatch{}, errKubectlMissing
	}
	limits := plan.Limits
	if limits.MaxFiles <= 0 {
		limits.MaxFiles = defaultLimits.MaxFiles
	}
	if limits.MaxBytes <= 0 {
		limits.MaxBytes = defaultLimits.MaxBytes
	}
	ctx, cancel := context.WithTimeout(context.Background(), opTimeout)
	defer cancel()

	raw, err := r.getPods(ctx, limits.MaxBytes)
	if err != nil {
		// kubectl 不可达/权限不足：错误如实上抛，形成显式覆盖缺口
		return protocol.EvidenceBatch{}, err
	}

	batch := protocol.EvidenceBatch{
		Candidates: []*protocol.Candidate{},
		Evidence:   []*protocol.Evidence{},
	}

	// hitBudget 精确判定是否真的越界：getPods 最多读 MaxBytes+1 字节，
	// 只有真实输出严格大于 MaxBytes 时读到的长度才会等于 MaxBytes+1。
	hitBudget := int64(len(raw)) > limits.MaxBytes
	items, decodeErr := decodePodItems(bytes.NewReader(raw))
	if decodeErr != nil && !hitBudget {
		// 未触及预算边界却仍解码失败：kubectl 输出本身畸形，真实错误
		return protocol.EvidenceBatch{}, fmt.Errorf("kubectl get pods: decode: %w", decodeErr)
	}
	if hitBudget {
		// 预算边界处的截断：已解出的完整 pod 照常参与下方分类，整批不失败。
		// 注意：json.Decoder.More() 在数据于空白符处被截断时会静默返回
		// false 而非报错，所以 Truncated 必须独立基于字节长度判定，不能
		// 依赖 decodeErr 是否非 nil。
		batch.Truncated = true
	}

	now := time.Now().UTC().Format(time.RFC3339)
	red := protocol.NewRedactor()
	var ids []string

loop:
	for _, p := range items {
		for _, c := range allContainers(p) {
			cls := classifyContainer(p.Metadata.Labels, c.spec)
			if !cls.candidate {
				continue // 无智能体信号的容器不产生候选噪音
			}
			if int64(len(ids)) >= limits.MaxFiles {
				batch.Truncated = true
				break loop
			}
			cand, ev := buildObjects(p, c, cls, now, red)
			batch.Candidates = append(batch.Candidates, cand)
			batch.Evidence = append(batch.Evidence, ev)
			ids = append(ids, cand.CandidateID)
		}
	}
	sort.Strings(ids)
	batch.Cursor = "kubernetes-cursor:" + hashIDs(ids)
	lastCursor = batch.Cursor
	return batch, nil
}

// pod / containerSpec 是 `kubectl get pods -A -o json` 中单个 pod 元素的
// 解码投影。安全不变量：env 只声明 Name 字段——Value/valueFrom 刻意不声明，
// 容器环境变量值绝不离开本进程（对齐 docker connector 对 Config.Env 的处理）。
type pod struct {
	Metadata struct {
		Name      string            `json:"name"`
		Namespace string            `json:"namespace"`
		Labels    map[string]string `json:"labels"`
	} `json:"metadata"`
	Spec struct {
		Containers     []containerSpec `json:"containers"`
		InitContainers []containerSpec `json:"initContainers"`
	} `json:"spec"`
}

type containerSpec struct {
	Name  string `json:"name"`
	Image string `json:"image"`
	Env   []struct {
		Name string `json:"name"` // 只取变量名；Value 字段刻意不存在
	} `json:"env"`
}

// decodePodItems 流式解码 `kubectl get pods -o json` 的
// `{"apiVersion":...,"items":[pod,...],"kind":"List",...}` 顶层结构：
// 逐个 token 消费，只在遇到 "items" 键时逐个 Decode 数组元素，其余顶层字段
// （apiVersion/kind/metadata 等）原样跳过，不关心其取值。
//
// 这样即便输入在某个 pod 对象中途被截断（字节预算耗尽/上游提前停止读取），
// 之前已完整解码的 pod 依然正确返回；调用方结合 error 与是否命中预算边界
// 判定这是「优雅截断」还是「真实的畸形 JSON」。
func decodePodItems(r io.Reader) ([]pod, error) {
	dec := json.NewDecoder(r)
	tok, err := dec.Token()
	if err != nil {
		return nil, err
	}
	if d, ok := tok.(json.Delim); !ok || d != '{' {
		return nil, fmt.Errorf("unexpected top-level JSON token %v", tok)
	}
	var items []pod
	for dec.More() {
		keyTok, err := dec.Token()
		if err != nil {
			return items, err
		}
		key, _ := keyTok.(string)
		if key != "items" {
			var skip json.RawMessage
			if err := dec.Decode(&skip); err != nil {
				return items, err
			}
			continue
		}
		arrTok, err := dec.Token()
		if err != nil {
			return items, err
		}
		if d, ok := arrTok.(json.Delim); !ok || d != '[' {
			return items, fmt.Errorf("'items' field is not an array")
		}
		for dec.More() {
			var p pod
			if err := dec.Decode(&p); err != nil {
				return items, err
			}
			items = append(items, p)
		}
		if _, err := dec.Token(); err != nil { // 消费收尾 ']'
			return items, err
		}
	}
	return items, nil
}

// containerRef 标记容器来源（常规容器 / initContainer）。
type containerRef struct {
	spec containerSpec
	init bool
}

func allContainers(p pod) []containerRef {
	refs := make([]containerRef, 0, len(p.Spec.Containers)+len(p.Spec.InitContainers))
	for _, c := range p.Spec.Containers {
		refs = append(refs, containerRef{spec: c})
	}
	for _, c := range p.Spec.InitContainers {
		refs = append(refs, containerRef{spec: c, init: true})
	}
	return refs
}

// 已知智能体框架镜像/名称关键词 → framework（高置信启发式，有序切片防迭代随机）
var knownFrameworks = []struct {
	keyword   string
	framework string
}{
	{"hermes", "hermes"},
	{"openclaw", "openclaw"},
	{"dify", "dify"},
	{"piagent", "pi"},
	{"workbuddy", "workbuddy"},
}

// 通用智能体运行时信号词（只提示候选，不猜测 framework）
var agentSignals = []string{
	"agent", "ollama", "langchain", "llamaindex", "autogen", "crewai", "mcp",
}

// containerClassification 是单个容器的发现分类结果。
type containerClassification struct {
	candidate  bool    // 是否进入候选
	framework  string  // 识别出的框架，未知为 "unknown"
	confidence float64 // 发现置信度
	basis      string  // label|heuristic：发现依据（标签只是高置信提示）
}

// classifyContainer 按 pod 标签 → 框架关键词 → 通用信号 的顺序分类（P1-4）。
// 无任何信号的容器不是智能体候选（跳过，不产生噪音）。
func classifyContainer(podLabels map[string]string, c containerSpec) containerClassification {
	haystack := strings.ToLower(c.Image + " " + c.Name)
	labeled := podLabels["siq.agent"] == "true"
	framework := "unknown"
	for _, kf := range knownFrameworks {
		if strings.Contains(haystack, kf.keyword) {
			framework = kf.framework
			break
		}
	}
	if labeled {
		// 纳管标签：高置信提示；framework 仍由内容信号决定
		return containerClassification{candidate: true, framework: framework, confidence: 1.0, basis: "label"}
	}
	if framework != "unknown" {
		return containerClassification{candidate: true, framework: framework, confidence: 0.8, basis: "heuristic"}
	}
	for _, signal := range agentSignals {
		if strings.Contains(haystack, signal) {
			return containerClassification{candidate: true, framework: "unknown", confidence: 0.6, basis: "heuristic"}
		}
	}
	return containerClassification{candidate: false}
}

// buildObjects 为一个候选容器产出 candidate 与其 evidence。
func buildObjects(p pod, c containerRef, cls containerClassification, now string, red *protocol.Redactor) (*protocol.Candidate, *protocol.Evidence) {
	ns := p.Metadata.Namespace
	podName := p.Metadata.Name
	id := "kubernetes:" + ns + "/" + podName + "/" + c.spec.Name
	locator := "k8s://" + ns + "/" + podName + "/" + c.spec.Name
	evidenceID := "ev:" + id

	// 不含环境变量值：只有 namespace/container/image/计数摘要进入 attributes。
	cand := &protocol.Candidate{
		CandidateID:   id,
		SourceType:    "kubernetes",
		SourceLocator: locator,
		DiscoveredAt:  now,
		Name:          truncate(red.RedactString(podName), 256),
		Framework:     cls.framework,
		Attributes: map[string]string{
			"namespace":        truncate(red.RedactString(ns), 256),
			"container":        truncate(red.RedactString(c.spec.Name), 256),
			"image":            truncate(red.RedactString(c.spec.Image), 256),
			"pod_labels_count": strconv.Itoa(len(p.Metadata.Labels)),
			"env_vars_count":   strconv.Itoa(len(c.spec.Env)), // 只计数，不取值
			"init_container":   strconv.FormatBool(c.init),
			"discovery_basis":  cls.basis, // label|heuristic，发现依据可审计
		},
		EvidenceIDs: []string{evidenceID},
		Confidence:  cls.confidence,
	}
	// 规范事实哈希进 evidence（绝不含 env 值）。
	facts, _ := json.Marshal(map[string]any{
		"namespace":    ns,
		"pod":          podName,
		"container":    c.spec.Name,
		"image":        c.spec.Image,
		"init":         c.init,
		"labels_count": len(p.Metadata.Labels),
	})
	ev := &protocol.Evidence{
		EvidenceID:       evidenceID,
		SourceType:       "k8s",
		SourceLocator:    locator,
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

// healthOp 报告 kubectl CLI 可用性（缺失时显式 unavailable，不静默）。
func healthOp(r runner) protocol.HealthReport {
	dep := protocol.DependencyHealth{Name: "kubectl_binary", OK: true}
	if !r.available() {
		dep.OK = false
		dep.Message = "kubectl binary not found in PATH"
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
