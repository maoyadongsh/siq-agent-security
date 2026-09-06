package main

// PiAgent Connector 测试（fixture 驱动，contract §4 负向语料）：
// 完整安装产出 N 候选、agents.json 畸形显式报错、apiKey 值永不进输出、
// 符号链接逃逸跳过、字节预算截断标记、未安装空批次、空 scope 拒绝。

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

func writeFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

// writeInstall 构造一个完整 piagent 安装根：config.yaml + agents.json +
// agents/<id>/SOUL.md（可选）。agentsJSON 为原始文本，便于注入畸形/含密 fixture。
func writeInstall(t *testing.T, root, configYAML, agentsJSON string, souls ...string) {
	t.Helper()
	if configYAML != "" {
		writeFile(t, filepath.Join(root, "config.yaml"), configYAML)
	}
	if agentsJSON != "" {
		writeFile(t, filepath.Join(root, "agents.json"), agentsJSON)
	}
	for _, id := range souls {
		writeFile(t, filepath.Join(root, "agents", id, "SOUL.md"), "人格描述")
	}
}

const twoAgentsJSON = `{"agents":[
  {"id":"coder","name":"代码助手","model":"pi-7b","workspace":"/home/u/work"},
  {"id":"ops","name":"运维助手","workspace":"/srv/ops"}
]}`

func collectFromRoot(t *testing.T, root string, limits protocol.CollectLimits) (protocol.EvidenceBatch, error) {
	t.Helper()
	return collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{root}},
		Limits: limits,
	})
}

func TestValidateScopeRejectsEmpty(t *testing.T) {
	// contract §4：空 scope 必须拒绝（默认根仅由 plan/collect 替换）
	if errs := validateScope(nil); len(errs) == 0 {
		t.Fatal("nil scope accepted")
	}
	if errs := validateScope(&protocol.Scope{}); len(errs) == 0 {
		t.Fatal("empty roots accepted")
	}
}

func TestValidateScopeRejectsRoot(t *testing.T) {
	if errs := validateScope(&protocol.Scope{Roots: []string{"/"}}); len(errs) == 0 {
		t.Fatal("root path accepted")
	}
}

func TestValidateScopeAcceptsExplicitRoot(t *testing.T) {
	dir := t.TempDir()
	if errs := validateScope(&protocol.Scope{Roots: []string{dir}}); len(errs) != 0 {
		t.Fatalf("explicit root rejected: %v", errs)
	}
}

func TestPlanScanSubstitutesDefaultRoot(t *testing.T) {
	plan, err := planScanOp(planScanParams{})
	if err != nil {
		t.Fatal(err)
	}
	if len(plan.Scope.Roots) != 1 || plan.Scope.Roots[0] != defaultRoot {
		t.Fatalf("expected default root, got %v", plan.Scope.Roots)
	}
}

func TestPlanScanRejectsInvalidExplicitScope(t *testing.T) {
	if _, err := planScanOp(planScanParams{Scope: &protocol.Scope{Roots: []string{"/"}}}); err == nil {
		t.Fatal("expected error for filesystem root scope")
	}
}

func TestCollectNotInstalledEmptyBatch(t *testing.T) {
	// 根目录不存在 = 未安装，空批次而非错误
	root := filepath.Join(t.TempDir(), "does-not-exist")
	batch, err := collectFromRoot(t, root, defaultLimits())
	if err != nil {
		t.Fatalf("missing root must not be an error: %v", err)
	}
	if len(batch.Candidates) != 0 || len(batch.Evidence) != 0 {
		t.Fatalf("expected empty batch, got %d candidates / %d evidence",
			len(batch.Candidates), len(batch.Evidence))
	}
	if batch.Truncated {
		t.Fatal("empty batch must not be truncated")
	}
}

func TestCollectFullInstall(t *testing.T) {
	root := t.TempDir()
	writeInstall(t, root, "model: pi-7b-global\n", twoAgentsJSON, "coder")

	batch, err := collectFromRoot(t, root, defaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 2 {
		t.Fatalf("expected 2 candidates, got %d", len(batch.Candidates))
	}

	byID := map[string]*protocol.Candidate{}
	for _, c := range batch.Candidates {
		byID[c.CandidateID] = c
		if c.SourceType != "piagent_profile" {
			t.Fatalf("unexpected source_type %q", c.SourceType)
		}
		if c.Framework != "pi" {
			t.Fatalf("unexpected framework %q", c.Framework)
		}
		if c.Confidence != 1.0 {
			t.Fatalf("expected confidence 1.0, got %v", c.Confidence)
		}
	}
	coder := byID["piagent:coder"]
	if coder == nil {
		t.Fatal("missing piagent:coder candidate")
	}
	if coder.Name != "代码助手" {
		t.Fatalf("unexpected name %q", coder.Name)
	}
	if coder.Attributes["has_soul"] != "true" {
		t.Fatalf("coder must have has_soul=true, got %q", coder.Attributes["has_soul"])
	}
	if coder.Attributes["model"] != "pi-7b" {
		t.Fatalf("unexpected coder model %q", coder.Attributes["model"])
	}
	if coder.Attributes["workspace"] != "/home/u/work" {
		t.Fatalf("unexpected coder workspace %q", coder.Attributes["workspace"])
	}
	ops := byID["piagent:ops"]
	if ops == nil {
		t.Fatal("missing piagent:ops candidate")
	}
	if ops.Attributes["has_soul"] != "false" {
		t.Fatalf("ops must have has_soul=false, got %q", ops.Attributes["has_soul"])
	}
	// config.yaml 的 model 作为全局默认回退
	if ops.Attributes["model"] != "pi-7b-global" {
		t.Fatalf("expected global default model fallback, got %q", ops.Attributes["model"])
	}

	// contract §4 不变量：每条 evidence 必须被同批 candidate 引用，
	// 且每条 manifest evidence 的 SubjectRef 指向其 candidate。
	referenced := map[string]bool{}
	for _, c := range batch.Candidates {
		for _, id := range c.EvidenceIDs {
			referenced[id] = true
		}
	}
	if len(batch.Evidence) == 0 {
		t.Fatal("expected evidence")
	}
	for _, ev := range batch.Evidence {
		if !referenced[ev.EvidenceID] {
			t.Fatalf("orphan evidence: %s", ev.EvidenceID)
		}
		if ev.SourceType != "manifest" {
			t.Fatalf("unexpected evidence source_type %q", ev.SourceType)
		}
		if ev.SubjectRef == nil || !strings.HasPrefix(*ev.SubjectRef, "piagent:") {
			t.Fatalf("evidence %s missing candidate subject_ref", ev.EvidenceID)
		}
		if ev.ContentHash == "" {
			t.Fatalf("evidence %s missing content hash", ev.EvidenceID)
		}
	}
	if batch.Cursor == "" {
		t.Fatal("expected cursor")
	}
}

func TestCollectMalformedAgentsJSON(t *testing.T) {
	// 畸形清单必须显式报错（覆盖缺口显式化），不得静默空批次
	root := t.TempDir()
	writeInstall(t, root, "", "{not valid json")
	_, err := collectFromRoot(t, root, defaultLimits())
	if err == nil {
		t.Fatal("expected explicit error for malformed agents.json")
	}
	if !strings.Contains(err.Error(), "agents.json") {
		t.Fatalf("error should name the manifest file, got %v", err)
	}
}

func TestCollectNeverEmitsAPIKeyValues(t *testing.T) {
	// 安全红线：apiKey/token 字段值绝不进入任何输出（候选/证据/游标）。
	const secretValue = "sk-piSecretKey123456789"
	root := t.TempDir()
	writeInstall(t, root,
		"model: pi-7b\napi_key: "+secretValue+"\ntoken: tok-secret-abcdef\n",
		`{"agents":[{"id":"a1","name":"助手","model":"m","workspace":"/w","apiKey":"`+secretValue+`","token":"tok-secret-abcdef"}]}`,
		"a1")

	batch, err := collectFromRoot(t, root, defaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 1 {
		t.Fatalf("expected 1 candidate, got %d", len(batch.Candidates))
	}
	raw, err := json.Marshal(batch)
	if err != nil {
		t.Fatal(err)
	}
	for _, s := range []string{secretValue, "tok-secret-abcdef"} {
		if strings.Contains(string(raw), s) {
			t.Fatalf("secret value %q leaked into batch output", s)
		}
	}
}

func TestCollectSkipsSymlinkEscape(t *testing.T) {
	// agents/<id>/SOUL.md 是指向 scope 外的符号链接：跳过（has_soul=false），不读正文
	root := t.TempDir()
	outside := t.TempDir()
	writeFile(t, filepath.Join(outside, "SOUL.md"), "外部人格，绝不可读")
	writeInstall(t, root, "", `{"agents":[{"id":"a1","name":"助手","model":"m","workspace":"/w"}]}`)
	if err := os.MkdirAll(filepath.Join(root, "agents", "a1"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(outside, "SOUL.md"), filepath.Join(root, "agents", "a1", "SOUL.md")); err != nil {
		t.Skip("symlink not supported")
	}

	batch, err := collectFromRoot(t, root, defaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 1 {
		t.Fatalf("expected 1 candidate, got %d", len(batch.Candidates))
	}
	if got := batch.Candidates[0].Attributes["has_soul"]; got != "false" {
		t.Fatalf("escaping SOUL.md symlink must be skipped, has_soul=%q", got)
	}
	// 逃逸目录作为 agents/<id>：目录内容整体跳过
	root2 := t.TempDir()
	writeInstall(t, root2, "", `{"agents":[{"id":"a2","name":"助手2","model":"m","workspace":"/w"}]}`)
	if err := os.Symlink(outside, filepath.Join(root2, "agents")); err != nil {
		t.Skip("symlink not supported")
	}
	batch2, err := collectFromRoot(t, root2, defaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	if len(batch2.Candidates) != 1 {
		t.Fatalf("expected 1 candidate, got %d", len(batch2.Candidates))
	}
	if got := batch2.Candidates[0].Attributes["has_soul"]; got != "false" {
		t.Fatalf("escaping agents dir must not yield soul, has_soul=%q", got)
	}
}

func TestReadFileLimitedRefusesSymlink(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "real.md")
	link := filepath.Join(dir, "SOUL.md")
	writeFile(t, target, "soul")
	if err := os.Symlink(target, link); err != nil {
		t.Skip("symlink not supported")
	}
	if _, err := readFileLimited(link, 1<<20); err == nil {
		t.Fatal("DEV10-I: symlink path must not be read via openRegular")
	}
}

func TestCollectByteBudgetTruncates(t *testing.T) {
	// 预算只够 agents.json 的一部分：显式 truncated，不误报畸形、不回退默认大小
	root := t.TempDir()
	writeInstall(t, root, "", twoAgentsJSON)
	batch, err := collectFromRoot(t, root, protocol.CollectLimits{MaxFiles: 10, MaxBytes: 32})
	if err != nil {
		t.Fatal(err)
	}
	if !batch.Truncated {
		t.Fatal("expected truncated flag when byte budget cuts the manifest")
	}
	if len(batch.Candidates) != 0 {
		t.Fatalf("cut manifest must not yield candidates, got %d", len(batch.Candidates))
	}
}

func TestReadFileLimitedZeroBudget(t *testing.T) {
	// 剩余预算为 0/负数必须返回显式错误，禁止回退继续读（对齐 directory P1-6）
	dir := t.TempDir()
	path := filepath.Join(dir, "agents.json")
	writeFile(t, path, strings.Repeat("x", 100))
	for _, budget := range []int64{0, -1} {
		if _, err := readFileLimited(path, budget); !errors.Is(err, errBudgetExhausted) {
			t.Fatalf("budget %d: expected errBudgetExhausted, got %v", budget, err)
		}
	}
	if data, err := readFileLimited(path, 10); err != nil || len(data) != 10 {
		t.Fatalf("budget 10: got len=%d err=%v", len(data), err)
	}
}

func TestCollectSecretRefEvidence(t *testing.T) {
	// .env / secrets/ 绝不读取正文：只记 name+size 的 secret_ref evidence，
	// 且必须被同批 candidate 引用（contract §4）。
	const envContent = "PI_API_KEY=sk-neverReadThisValue999"
	root := t.TempDir()
	writeInstall(t, root, "", `{"agents":[{"id":"a1","name":"助手","model":"m","workspace":"/w"}]}`)
	writeFile(t, filepath.Join(root, "agents", "a1", ".env"), envContent)
	if err := os.MkdirAll(filepath.Join(root, "agents", "a1", "secrets"), 0o755); err != nil {
		t.Fatal(err)
	}

	batch, err := collectFromRoot(t, root, defaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 1 {
		t.Fatalf("expected 1 candidate, got %d", len(batch.Candidates))
	}
	var secretRefs []*protocol.Evidence
	for _, ev := range batch.Evidence {
		if ev.Classification == "secret_ref" {
			secretRefs = append(secretRefs, ev)
		}
	}
	if len(secretRefs) != 2 {
		t.Fatalf("expected 2 secret_ref evidence, got %d", len(secretRefs))
	}
	// .env 正文的哈希绝不允许出现；secret_ref 哈希只能由 name+size 派生
	envHash := protocol.ContentHash([]byte(envContent))
	for _, ev := range batch.Evidence {
		if ev.ContentHash == envHash {
			t.Fatal(".env content must never be read/hashed")
		}
	}
	raw, _ := json.Marshal(batch)
	if strings.Contains(string(raw), "neverReadThisValue") {
		t.Fatal(".env value leaked into batch output")
	}
	// 引用完整性
	referenced := map[string]bool{}
	for _, id := range batch.Candidates[0].EvidenceIDs {
		referenced[id] = true
	}
	for _, ev := range secretRefs {
		if !referenced[ev.EvidenceID] {
			t.Fatalf("secret_ref evidence %s not referenced by candidate", ev.EvidenceID)
		}
		if ev.SubjectRef == nil || *ev.SubjectRef != "piagent:a1" {
			t.Fatalf("secret_ref evidence %s wrong subject_ref", ev.EvidenceID)
		}
	}
}

func TestExtractDefaultModel(t *testing.T) {
	cases := []struct {
		name string
		yaml string
		want string
	}{
		{"simple", "model: pi-7b\n", "pi-7b"},
		{"quoted", `model: "pi-7b" # 默认` + "\n", "pi-7b"},
		{"ignores other keys", "api_key: sk-xxx\ntoken: abc\n", ""},
		{"ignores nested", "provider:\n  model: nested\n", ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := extractDefaultModel([]byte(tc.yaml)); got != tc.want {
				t.Fatalf("got %q, want %q", got, tc.want)
			}
		})
	}
}

func TestCapabilities(t *testing.T) {
	caps := capabilities()
	if caps.NetworkAccess {
		t.Fatal("network_access must be false")
	}
	if caps.MaxOutputBytes != protocol.DefaultOutputLimitBytes {
		t.Fatalf("unexpected max_output_bytes %d", caps.MaxOutputBytes)
	}
	if len(caps.Objects) != 1 || caps.Objects[0] != "piagent_profile" {
		t.Fatalf("unexpected objects %v", caps.Objects)
	}
}

func TestDispatchUnknownOp(t *testing.T) {
	resp := dispatch(&protocol.Request{ID: "r1", Op: "bogus", Params: json.RawMessage(`{}`)})
	if resp.OK || resp.Error == nil || resp.Error.Code != protocol.CodeUnsupported {
		t.Fatalf("expected unsupported error, got %+v", resp)
	}
}

func TestDispatchDescribeAndHealth(t *testing.T) {
	resp := dispatch(&protocol.Request{ID: "r1", Op: protocol.OpDescribe, Params: json.RawMessage(`{}`)})
	if !resp.OK {
		t.Fatalf("describe failed: %+v", resp.Error)
	}
	resp = dispatch(&protocol.Request{ID: "r2", Op: protocol.OpHealth, Params: json.RawMessage(`{}`)})
	if !resp.OK {
		t.Fatalf("health failed: %+v", resp.Error)
	}
}
