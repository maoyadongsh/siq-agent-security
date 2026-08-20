package main

// P1-4 Kubernetes 发现源测试（fixture 驱动，不依赖真实集群/kubectl）：
//   - siq.agent=true 标签只是高置信提示而非发现前置条件；
//   - 未打标签的 dify 镜像 pod（影子智能体）必须经启发式信号被发现；
//   - 无信号 pod/容器跳过，不产生候选噪音；
//   - kubectl 缺失/预算耗尽显式报错，不得静默漏报；
//   - env 秘密值绝不出现在任何输出中（contract §4 负向安全用例）。

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

// fixturePods：带标签 hermes pod（env 含秘密值）、未打标签的 dify pod
// （影子智能体）、无信号 nginx pod、带 ollama initContainer 的 pod。
const fixturePods = `{
  "items": [
    {
      "metadata": {
        "name": "hermes-hub-7d9f",
        "namespace": "prod",
        "labels": {"app": "hermes", "siq.agent": "true"}
      },
      "spec": {
        "containers": [
          {
            "name": "hermes",
            "image": "siq/hermes:2.0",
            "env": [
              {"name": "OPENAI_API_KEY", "value": "sk-secret-deadbeef-12345"},
              {"name": "AGENT_TOKEN", "value": "tok-ultra-secret-67890"}
            ]
          }
        ]
      }
    },
    {
      "metadata": {"name": "dify-api-0", "namespace": "apps", "labels": {"app": "dify"}},
      "spec": {
        "containers": [
          {"name": "api", "image": "langgenius/dify-api:0.6"}
        ]
      }
    },
    {
      "metadata": {"name": "web-frontend", "namespace": "default"},
      "spec": {
        "containers": [
          {"name": "nginx", "image": "nginx:1.27"}
        ]
      }
    },
    {
      "metadata": {"name": "ml-worker", "namespace": "ml"},
      "spec": {
        "containers": [
          {"name": "worker", "image": "python:3.12-slim"}
        ],
        "initContainers": [
          {"name": "ollama-pull", "image": "ollama/ollama:latest"}
        ]
      }
    }
  ]
}`

// fakeRunner 注入固定 fixture / 错误，替代真实 kubectl。
type fakeRunner struct {
	isAvailable bool
	payload     string
	err         error
}

func (f fakeRunner) available() bool { return f.isAvailable }

func (f fakeRunner) getPods(_ context.Context, maxBytes int64) ([]byte, error) {
	if f.err != nil {
		return nil, f.err
	}
	if maxBytes <= 0 || int64(len(f.payload)) > maxBytes {
		return nil, errBudgetExhausted
	}
	return []byte(f.payload), nil
}

func collectFixture(t *testing.T, plan protocol.ScanPlan) protocol.EvidenceBatch {
	t.Helper()
	batch, err := collectOp(plan, fakeRunner{isAvailable: true, payload: fixturePods})
	if err != nil {
		t.Fatalf("collect fixture: %v", err)
	}
	return batch
}

func candidateByID(batch protocol.EvidenceBatch, id string) *protocol.Candidate {
	for _, c := range batch.Candidates {
		if c.CandidateID == id {
			return c
		}
	}
	return nil
}

func TestClassifyContainer(t *testing.T) {
	cases := []struct {
		name       string
		labels     map[string]string
		spec       containerSpec
		candidate  bool
		framework  string
		confidence float64
		basis      string
	}{
		{
			name:      "labeled pod high confidence",
			labels:    map[string]string{"siq.agent": "true"},
			spec:      containerSpec{Name: "svc", Image: "registry.internal/svc:1.0"},
			candidate: true, framework: "unknown", confidence: 1.0, basis: "label",
		},
		{
			name:      "unlabeled dify image shadow agent",
			spec:      containerSpec{Name: "api", Image: "langgenius/dify-api:0.6"},
			candidate: true, framework: "dify", confidence: 0.8, basis: "heuristic",
		},
		{
			name:      "piagent maps to pi",
			spec:      containerSpec{Name: "piagent", Image: "corp/piagent:1.0"},
			candidate: true, framework: "pi", confidence: 0.8, basis: "heuristic",
		},
		{
			name:      "generic ollama signal",
			spec:      containerSpec{Name: "ollama", Image: "ollama/ollama:latest"},
			candidate: true, framework: "unknown", confidence: 0.6, basis: "heuristic",
		},
		{
			name:      "generic mcp signal in name",
			spec:      containerSpec{Name: "mcp-server", Image: "corp/tools:2.1"},
			candidate: true, framework: "unknown", confidence: 0.6, basis: "heuristic",
		},
		{
			name:      "label plus framework keeps label basis",
			labels:    map[string]string{"siq.agent": "true"},
			spec:      containerSpec{Name: "hermes", Image: "siq/hermes:2.0"},
			candidate: true, framework: "hermes", confidence: 1.0, basis: "label",
		},
		{name: "nginx no signal", spec: containerSpec{Name: "nginx", Image: "nginx:1.27"}},
		{name: "postgres no signal", spec: containerSpec{Name: "db", Image: "postgres:16"}},
		{name: "redis no signal", spec: containerSpec{Name: "cache", Image: "redis:7"}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			cls := classifyContainer(tc.labels, tc.spec)
			if cls.candidate != tc.candidate {
				t.Fatalf("candidate = %v, want %v (%+v)", cls.candidate, tc.candidate, cls)
			}
			if !tc.candidate {
				return
			}
			if cls.framework != tc.framework || cls.confidence != tc.confidence || cls.basis != tc.basis {
				t.Fatalf("classification = %+v, want framework=%q confidence=%v basis=%q",
					cls, tc.framework, tc.confidence, tc.basis)
			}
		})
	}
}

func TestCollectLabeledPod(t *testing.T) {
	batch := collectFixture(t, protocol.ScanPlan{})
	cand := candidateByID(batch, "kubernetes:prod/hermes-hub-7d9f/hermes")
	if cand == nil {
		t.Fatalf("labeled pod container must be a candidate: %+v", batch.Candidates)
	}
	if cand.Confidence != 1.0 || cand.Attributes["discovery_basis"] != "label" {
		t.Fatalf("labeled candidate must carry label basis: %+v", cand)
	}
	if cand.Framework != "hermes" {
		t.Fatalf("framework signal expected, got %q", cand.Framework)
	}
	if cand.Name != "hermes-hub-7d9f" {
		t.Fatalf("candidate name must be the pod name, got %q", cand.Name)
	}
	if cand.Attributes["namespace"] != "prod" || cand.Attributes["pod_labels_count"] != "2" {
		t.Fatalf("attributes missing namespace/labels_count: %v", cand.Attributes)
	}
}

func TestCollectShadowDifyPod(t *testing.T) {
	// 未打标签的 dify 镜像 pod（影子智能体）必须被发现（P1-4 漏报修复语义）
	batch := collectFixture(t, protocol.ScanPlan{})
	cand := candidateByID(batch, "kubernetes:apps/dify-api-0/api")
	if cand == nil {
		t.Fatal("unlabeled dify pod must surface as heuristic candidate")
	}
	if cand.Framework != "dify" || cand.Attributes["discovery_basis"] != "heuristic" {
		t.Fatalf("shadow dify candidate: %+v", cand)
	}
	if cand.Confidence >= 1.0 {
		t.Fatalf("heuristic confidence must be below label confidence: %v", cand.Confidence)
	}
}

func TestCollectNoSignalSkipped(t *testing.T) {
	batch := collectFixture(t, protocol.ScanPlan{})
	if candidateByID(batch, "kubernetes:default/web-frontend/nginx") != nil {
		t.Fatal("no-signal nginx container must not become candidate")
	}
	// ml-worker 常规容器 python:3.12-slim 无信号，也必须跳过
	if candidateByID(batch, "kubernetes:ml/ml-worker/worker") != nil {
		t.Fatal("no-signal worker container must not become candidate")
	}
}

func TestCollectInitContainer(t *testing.T) {
	// initContainers 同样纳入枚举（ollama init 容器是通用信号候选）
	batch := collectFixture(t, protocol.ScanPlan{})
	cand := candidateByID(batch, "kubernetes:ml/ml-worker/ollama-pull")
	if cand == nil {
		t.Fatal("ollama initContainer must surface as candidate")
	}
	if cand.Attributes["init_container"] != "true" || cand.Confidence != 0.6 {
		t.Fatalf("init container attributes: %+v", cand)
	}
}

func TestCollectEveryEvidenceReferenced(t *testing.T) {
	// contract §4：每条 evidence 必须被同批 candidate 引用
	batch := collectFixture(t, protocol.ScanPlan{})
	if len(batch.Candidates) == 0 || len(batch.Evidence) != len(batch.Candidates) {
		t.Fatalf("candidates=%d evidence=%d", len(batch.Candidates), len(batch.Evidence))
	}
	referenced := map[string]bool{}
	for _, c := range batch.Candidates {
		for _, id := range c.EvidenceIDs {
			referenced[id] = true
		}
	}
	for _, ev := range batch.Evidence {
		if !referenced[ev.EvidenceID] {
			t.Fatalf("evidence %s not referenced by any candidate", ev.EvidenceID)
		}
		if ev.SubjectRef == nil || candidateByID(batch, *ev.SubjectRef) == nil {
			t.Fatalf("evidence %s subject_ref dangling", ev.EvidenceID)
		}
		if ev.SourceType != "k8s" || ev.ContentHash == "" {
			t.Fatalf("evidence must carry k8s source type and content hash: %+v", ev)
		}
	}
	if batch.Cursor == "" {
		t.Fatal("collect must produce a cursor")
	}
}

func TestCollectEnvValuesNeverLeak(t *testing.T) {
	// 负向安全用例：fixture 中的秘密值绝不出现在任何序列化输出中
	batch := collectFixture(t, protocol.ScanPlan{})
	out, err := json.Marshal(batch)
	if err != nil {
		t.Fatalf("marshal batch: %v", err)
	}
	for _, secret := range []string{"sk-secret-deadbeef-12345", "tok-ultra-secret-67890", "OPENAI_API_KEY", "AGENT_TOKEN"} {
		if strings.Contains(string(out), secret) {
			t.Fatalf("env secret %q leaked into batch output: %s", secret, out)
		}
	}
	// 只保留变量计数，不含任何变量名/值
	cand := candidateByID(batch, "kubernetes:prod/hermes-hub-7d9f/hermes")
	if cand == nil || cand.Attributes["env_vars_count"] != "2" {
		t.Fatalf("env_vars_count expected on labeled candidate: %+v", cand)
	}
}

func TestCollectKubectlMissing(t *testing.T) {
	// kubectl 不在 PATH：显式错误（覆盖缺口），不得静默返回空批次
	_, err := collectOp(protocol.ScanPlan{}, fakeRunner{isAvailable: false, payload: fixturePods})
	if !errors.Is(err, errKubectlMissing) {
		t.Fatalf("want errKubectlMissing, got %v", err)
	}
	perr := errToProtocol(err)
	if perr.Code != protocol.CodeUnsupported {
		t.Fatalf("kubectl missing must map to unsupported, got %q", perr.Code)
	}
}

func TestCollectKubectlFailurePropagates(t *testing.T) {
	// kubectl 执行失败（集群不可达/权限不足）：错误如实上抛，不静默漏报
	boom := errors.New("connection refused")
	_, err := collectOp(protocol.ScanPlan{}, fakeRunner{isAvailable: true, err: boom})
	if !errors.Is(err, boom) {
		t.Fatalf("kubectl failure must propagate, got %v", err)
	}
}

func TestCollectBudgetExhausted(t *testing.T) {
	// 字节预算耗尽：显式 limit_exceeded，不解析不完整 JSON
	plan := protocol.ScanPlan{Limits: protocol.CollectLimits{MaxBytes: 16}}
	_, err := collectOp(plan, fakeRunner{isAvailable: true, payload: fixturePods})
	if !errors.Is(err, errBudgetExhausted) {
		t.Fatalf("want errBudgetExhausted, got %v", err)
	}
	if perr := errToProtocol(err); perr.Code != protocol.CodeLimitExceeded {
		t.Fatalf("budget exhaustion must map to limit_exceeded, got %q", perr.Code)
	}
}

func TestCollectTruncatedAtMaxFiles(t *testing.T) {
	plan := protocol.ScanPlan{Limits: protocol.CollectLimits{MaxFiles: 1}}
	batch := collectFixture(t, plan)
	if !batch.Truncated || len(batch.Candidates) != 1 {
		t.Fatalf("max_files=1 must truncate with exactly 1 candidate: %+v", batch)
	}
}

func TestCollectEmptyClusterEmptyBatch(t *testing.T) {
	// 集群无 pod 是合法空批次（与「kubectl 缺失报错」区分，不得混为静默漏报）
	batch, err := collectOp(protocol.ScanPlan{}, fakeRunner{isAvailable: true, payload: `{"items":[]}`})
	if err != nil {
		t.Fatalf("empty cluster must be a valid empty batch: %v", err)
	}
	if len(batch.Candidates) != 0 || len(batch.Evidence) != 0 || batch.Truncated {
		t.Fatalf("empty cluster: %+v", batch)
	}
}

func TestCapabilities(t *testing.T) {
	caps := capabilities()
	if caps.NetworkAccess {
		t.Fatal("kubernetes connector must declare network_access=false")
	}
	if caps.MaxOutputBytes != protocol.DefaultOutputLimitBytes {
		t.Fatalf("max_output_bytes = %d, want %d", caps.MaxOutputBytes, protocol.DefaultOutputLimitBytes)
	}
}

func TestValidateScopeEmptyValid(t *testing.T) {
	// 同 docker connector：无文件系统 scope，空 scope 合法
	if res := validateScopeOp(nil); !res.Valid {
		t.Fatalf("nil scope must be valid: %+v", res)
	}
	if res := validateScopeOp(&protocol.Scope{}); !res.Valid {
		t.Fatalf("empty scope must be valid: %+v", res)
	}
}

func TestPlanScanCarriesLimits(t *testing.T) {
	plan := planScanOp(planScanParams{Cursor: "c0"})
	if plan.Limits.MaxFiles <= 0 || plan.Limits.MaxBytes <= 0 {
		t.Fatalf("plan must carry default limits: %+v", plan.Limits)
	}
	if plan.Cursor != "c0" {
		t.Fatalf("cursor must round-trip: %+v", plan)
	}
}

func TestCheckpointRoundTrip(t *testing.T) {
	lastCursor = ""
	if _, err := collectOp(protocol.ScanPlan{}, fakeRunner{isAvailable: true, payload: fixturePods}); err != nil {
		t.Fatalf("collect: %v", err)
	}
	resp := dispatch(&protocol.Request{ID: "r1", Op: protocol.OpCheckpoint, Params: json.RawMessage(`{}`)})
	if !resp.OK {
		t.Fatalf("checkpoint: %+v", resp.Error)
	}
	res, ok := resp.Result.(protocol.CursorResult)
	if !ok || res.Cursor == "" {
		t.Fatalf("checkpoint must return last collect cursor: %+v", resp.Result)
	}
	if !strings.HasPrefix(res.Cursor, "kubernetes-cursor:") {
		t.Fatalf("cursor shape: %q", res.Cursor)
	}
}

func TestHealth(t *testing.T) {
	ok := healthOp(fakeRunner{isAvailable: true})
	if len(ok.Dependencies) != 1 || !ok.Dependencies[0].OK {
		t.Fatalf("kubectl present must be healthy: %+v", ok)
	}
	missing := healthOp(fakeRunner{isAvailable: false})
	if missing.Dependencies[0].OK || missing.Dependencies[0].Message == "" {
		t.Fatalf("kubectl missing must be explicit unavailable: %+v", missing)
	}
}

func TestDispatchUnknownOp(t *testing.T) {
	resp := dispatch(&protocol.Request{ID: "r9", Op: "bogus", Params: json.RawMessage(`{}`)})
	if resp.OK || resp.Error == nil || resp.Error.Code != protocol.CodeUnsupported {
		t.Fatalf("unknown op must be unsupported: %+v", resp)
	}
}
