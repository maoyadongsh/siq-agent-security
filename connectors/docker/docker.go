// Command docker-connector is the Docker Connector (connector-protocol.v1.md).
// It enumerates ALL visible containers via the docker CLI (os/exec; no docker
// SDK dependency), classifies agent candidates by image/command/label signals,
// and emits candidates + evidence.
//
// Discovery policy (P1-9): the siq.agent=true label is only a high-confidence
// hint / managed flag, NEVER a discovery precondition — unlabeled agent
// containers (shadow agents) must still surface as heuristic candidates.
//
// Security invariants:
//   - container environment values are NEVER read: the inspect payload is
//     decoded into a struct that deliberately has no Env field;
//   - candidate attributes carry image / digest / mount summaries only;
//   - network access is not used (network_access: false).
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
			fmt.Fprintf(os.Stderr, "docker-connector: %v\n", err)
			os.Exit(1)
		}
		return
	}
	fmt.Fprintln(os.Stderr, "usage: docker-connector --serve")
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
	case errors.Is(err, errDockerMissing):
		return &protocol.ProtocolError{Code: protocol.CodeUnsupported, Message: err.Error()}
	default:
		return &protocol.ProtocolError{Code: "internal_error", Message: err.Error()}
	}
}

var errDockerMissing = errors.New("docker binary not found")

func capabilities() protocol.ConnectorCapabilities {
	return protocol.ConnectorCapabilities{
		Version:             connectorVersion,
		Objects:             []string{"docker"},
		RequiredPermissions: []string{"exec:docker"},
		DataCategories:      []string{"image_names", "mount_paths", "labels"},
		MaxOutputBytes:      protocol.DefaultOutputLimitBytes,
		NetworkAccess:       false,
	}
}

// validateScopeOp: docker has no filesystem scope; an empty scope is valid,
// any explicit roots are run through the shared safety rules.
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

// collectOp enumerates all visible containers, classifies agent candidates
// (P1-9: label is a hint, not a precondition) and emits one candidate + one
// evidence per candidate container.
func collectOp(plan protocol.ScanPlan) (protocol.EvidenceBatch, error) {
	if _, err := exec.LookPath("docker"); err != nil {
		return protocol.EvidenceBatch{}, errDockerMissing
	}
	limits := plan.Limits
	if limits.MaxFiles <= 0 {
		limits.MaxFiles = 100
	}
	ctx, cancel := context.WithTimeout(context.Background(), opTimeout)
	defer cancel()

	rows, err := listContainers(ctx)
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

	for _, row := range rows {
		cls := classifyContainer(row)
		if !cls.candidate {
			continue // 无智能体信号的容器不产生候选噪音
		}
		if int64(len(ids)) >= limits.MaxFiles {
			batch.Truncated = true
			break
		}
		insp, err := inspectContainer(ctx, row.ID)
		if err != nil {
			fmt.Fprintf(os.Stderr, "docker: inspect %s: %v\n", row.ID, err)
			continue
		}
		cand, ev := buildObjects(row, insp, cls, now, red)
		batch.Candidates = append(batch.Candidates, cand)
		batch.Evidence = append(batch.Evidence, ev)
		ids = append(ids, row.ID)
	}
	sort.Strings(ids)
	batch.Cursor = "docker-cursor:" + hashIDs(ids)
	lastCursor = batch.Cursor
	return batch, nil
}

// containerRow is one line of `docker ps --format '{{json .}}'`.
type containerRow struct {
	ID      string `json:"ID"`
	Names   string `json:"Names"`
	Image   string `json:"Image"`
	Command string `json:"Command"`
	Labels  string `json:"Labels"`
	Status  string `json:"Status"`
}

// listContainers enumerates ALL visible containers（P1-9：标签不再作为发现前置条件）。
// docker daemon 不可达/权限不足时错误如实上抛（协议错误响应），形成显式覆盖缺口而非静默漏报。
func listContainers(ctx context.Context) ([]containerRow, error) {
	cmd := exec.CommandContext(ctx, "docker", "ps", "--format", "{{json .}}")
	out, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("docker ps: %w", err)
	}
	var rows []containerRow
	dec := json.NewDecoder(bytes.NewReader(out))
	for {
		var row containerRow
		if err := dec.Decode(&row); err != nil {
			if err == io.EOF {
				break
			}
			return nil, fmt.Errorf("docker ps: decode: %w", err)
		}
		if row.ID != "" {
			rows = append(rows, row)
		}
	}
	return rows, nil
}

// 已知智能体框架镜像/命令关键词 → framework（高置信启发式，有序切片防迭代随机）
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

// classifyContainer 按 标签 → 框架关键词 → 通用信号 的顺序分类（P1-9）。
// 无任何信号的容器不是智能体候选（跳过，不产生噪音）。
func classifyContainer(row containerRow) containerClassification {
	haystack := strings.ToLower(row.Image + " " + row.Command + " " + row.Names)
	labeled := false
	for _, label := range strings.Split(row.Labels, ",") {
		if strings.TrimSpace(label) == "siq.agent=true" {
			labeled = true
			break
		}
	}
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

// dockerInspect is the projection of `docker inspect` we decode.
// Security invariant: Config.Env is deliberately NOT declared — container
// environment values must never leave the host.
type dockerInspect struct {
	ID     string `json:"Id"`
	Config struct {
		Image  string            `json:"Image"`
		Labels map[string]string `json:"Labels"`
	} `json:"Config"`
	Image       string   `json:"Image"` // image hash
	RepoDigests []string `json:"RepoDigests"`
	Mounts      []struct {
		Type        string `json:"Type"`
		Source      string `json:"Source"`
		Destination string `json:"Destination"`
	} `json:"Mounts"`
}

func inspectContainer(ctx context.Context, id string) (*dockerInspect, error) {
	cmd := exec.CommandContext(ctx, "docker", "inspect", id)
	out, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("docker inspect %s: %w", id, err)
	}
	var arr []dockerInspect
	if err := json.Unmarshal(out, &arr); err != nil {
		return nil, fmt.Errorf("docker inspect %s: decode: %w", id, err)
	}
	if len(arr) == 0 {
		return nil, fmt.Errorf("docker inspect %s: empty result", id)
	}
	return &arr[0], nil
}

// buildObjects emits the candidate and its evidence for one container.
func buildObjects(row containerRow, insp *dockerInspect, cls containerClassification, now string, red *protocol.Redactor) (*protocol.Candidate, *protocol.Evidence) {
	short := row.ID
	if len(short) > 12 {
		short = short[:12]
	}
	digest := ""
	if len(insp.RepoDigests) > 0 {
		digest = insp.RepoDigests[0]
	}
	if digest == "" {
		digest = insp.Image
	}
	var mounts []string
	for _, m := range insp.Mounts {
		mounts = append(mounts, truncate(red.RedactString(m.Source), 128)+":"+truncate(red.RedactString(m.Destination), 128))
	}
	sort.Strings(mounts)

	// 不含环境变量值：只有 image/digest/mounts 摘要进入 attributes。
	cand := &protocol.Candidate{
		CandidateID:    "docker:" + short,
		SourceType:     "docker",
		SourceLocator:  "docker://" + short,
		DiscoveredAt:   now,
		Name:           truncate(red.RedactString(row.Names), 256),
		Framework:      cls.framework,
		ArtifactDigest: digest,
		Attributes: map[string]string{
			"image":           truncate(red.RedactString(row.Image), 256),
			"digest":          digest,
			"mounts":          truncate(strings.Join(mounts, ","), 1024),
			"labels_count":    strconv.Itoa(len(insp.Config.Labels)),
			"discovery_basis": cls.basis, // P1-9：label|heuristic，发现依据可审计
		},
		EvidenceIDs: []string{"ev:docker:" + short},
		Confidence:  cls.confidence,
	}
	// Canonical facts hashed into the evidence (never env values).
	facts, _ := json.Marshal(map[string]any{
		"container_id": row.ID,
		"image":        insp.Config.Image,
		"digest":       digest,
		"mounts":       mounts,
	})
	ev := &protocol.Evidence{
		EvidenceID:       "ev:docker:" + short,
		SourceType:       "container",
		SourceLocator:    "docker://" + short,
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

// healthOp reports docker CLI availability (task spec: 无 docker 命令时
// health 返回 unavailable).
func healthOp() protocol.HealthReport {
	dep := protocol.DependencyHealth{Name: "docker_binary", OK: true}
	if _, err := exec.LookPath("docker"); err != nil {
		dep.OK = false
		dep.Message = "docker binary not found in PATH"
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
