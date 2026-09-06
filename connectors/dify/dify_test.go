package main

// Dify 部署发现 Connector 测试（contract §4 负向语料 + 规格正负用例）：
// 空 scope 拒绝、dify compose 产出候选、非 dify compose 跳过、符号链接逃逸
// 跳过、environment 段 secret 值绝不进任何输出、字节预算显式截断。

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

// difyComposeFixture 是典型的 Dify 自托管 compose（environment 段含 secret
// 值，用于验证红线：除镜像行与 service 名外内容绝不外泄）。
const difyComposeFixture = `version: "3"
services:
  api:
    image: langgenius/dify-api:0.6.8
    environment:
      SECRET_KEY: s3cr3t-plain-value-zzz
      DB_PASSWORD: hunter2-not-matched
  web:
    image: langgenius/dify-web:0.6.8
  sandbox:
    image: langgenius/dify-sandbox:0.2.1
  db:
    image: postgres:15
    environment:
      POSTGRES_PASSWORD: pg-secret-value-qqq
`

const nonDifyComposeFixture = `version: "3"
services:
  web:
    image: nginx:1.25
  db:
    image: postgres:15
`

func writeFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestParseDifyServices(t *testing.T) {
	cases := []struct {
		name     string
		content  string
		wantLen  int
		wantAPI  string // 期望的 dify-api tag（无则空）
		wantImgs []string
	}{
		{
			name:     "typical dify deployment",
			content:  difyComposeFixture,
			wantLen:  3,
			wantAPI:  "0.6.8",
			wantImgs: []string{"langgenius/dify-api:0.6.8", "langgenius/dify-web:0.6.8", "langgenius/dify-sandbox:0.2.1"},
		},
		{
			name:    "non-dify compose",
			content: nonDifyComposeFixture,
			wantLen: 0,
		},
		{
			name: "api image without tag",
			content: `services:
  api:
    image: langgenius/dify-api
`,
			wantLen:  1,
			wantAPI:  "",
			wantImgs: []string{"langgenius/dify-api"},
		},
		{
			name: "image before services block is ignored",
			content: `x-image: langgenius/dify-api:9.9.9
services:
  web:
    image: nginx:1.25
`,
			wantLen: 0,
		},
		{
			name: "comments and blank lines tolerated",
			content: `# dify compose
services:
  # api service
  api:
    image: langgenius/dify-api:0.7.0 # pinned

  web:
    image: langgenius/dify-web:0.7.0
`,
			wantLen:  2,
			wantAPI:  "0.7.0",
			wantImgs: []string{"langgenius/dify-api:0.7.0", "langgenius/dify-web:0.7.0"},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := parseDifyServices(tc.content)
			if len(got) != tc.wantLen {
				t.Fatalf("expected %d dify services, got %d: %+v", tc.wantLen, len(got), got)
			}
			for i, img := range tc.wantImgs {
				if got[i].image != img {
					t.Fatalf("service %d image: expected %q, got %q", i, img, got[i].image)
				}
			}
			apiTag := ""
			for _, s := range got {
				if s.image == "langgenius/dify-api" || strings.HasPrefix(s.image, "langgenius/dify-api:") {
					apiTag = s.tag
				}
			}
			if apiTag != tc.wantAPI {
				t.Fatalf("api tag: expected %q, got %q", tc.wantAPI, apiTag)
			}
		})
	}
}

func TestValidateScopeRejectsEmpty(t *testing.T) {
	// 无默认范围：空 scope 必须拒绝（显式授权）
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

func TestValidateScopeOpValidFlagMatchesErrors(t *testing.T) {
	// 回归：validateScopeOp 曾恒返回 Valid=true，即便 Errors 非空（bug）。
	// Valid 必须与 Errors 是否为空保持一致，否则调用方可能忽略 Errors 误判为合法范围。
	if res := validateScopeOp(nil); res.Valid || len(res.Errors) == 0 {
		t.Fatalf("empty scope must report Valid=false with errors: %+v", res)
	}
	if res := validateScopeOp(&protocol.Scope{Roots: []string{"/"}}); res.Valid || len(res.Errors) == 0 {
		t.Fatalf("root path must report Valid=false with errors: %+v", res)
	}
	if res := validateScopeOp(&protocol.Scope{Roots: []string{t.TempDir()}}); !res.Valid || len(res.Errors) != 0 {
		t.Fatalf("legitimate scope must report Valid=true with no errors: %+v", res)
	}
}

func TestPlanScanRejectsEmptyScope(t *testing.T) {
	if _, err := planScanOp(planScanParams{}); err == nil {
		t.Fatal("empty scope plan accepted")
	}
}

func TestCollectFindsDifyDeployment(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "my-dify", "docker-compose.yaml"), difyComposeFixture)
	writeFile(t, filepath.Join(dir, "plain-web", "docker-compose.yml"), nonDifyComposeFixture)

	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{dir}},
		Limits: defaultLimits(),
	})
	if err != nil {
		t.Fatal(err)
	}
	if batch.Truncated {
		t.Fatal("unexpected truncation")
	}
	if len(batch.Candidates) != 1 {
		t.Fatalf("expected 1 candidate, got %d", len(batch.Candidates))
	}
	c := batch.Candidates[0]
	if c.CandidateID != "dify:"+filepath.Join("my-dify", "docker-compose.yaml") {
		t.Fatalf("unexpected candidate id: %s", c.CandidateID)
	}
	if c.SourceType != "dify_deployment" || c.Framework != "dify" {
		t.Fatalf("unexpected source/framework: %s/%s", c.SourceType, c.Framework)
	}
	if c.Confidence != 0.9 {
		t.Fatalf("unexpected confidence: %v", c.Confidence)
	}
	if c.Name != "my-dify" {
		t.Fatalf("unexpected name: %s", c.Name)
	}
	attrs := c.Attributes
	if attrs["compose_file"] != filepath.Join("my-dify", "docker-compose.yaml") {
		t.Fatalf("unexpected compose_file: %v", attrs)
	}
	if attrs["services"] != "api,web,sandbox" {
		t.Fatalf("unexpected services: %q", attrs["services"])
	}
	if attrs["api_version"] != "0.6.8" {
		t.Fatalf("unexpected api_version: %q", attrs["api_version"])
	}
	if attrs["discovery_basis"] != "compose_manifest" {
		t.Fatalf("unexpected discovery_basis: %q", attrs["discovery_basis"])
	}
	// 每条 evidence 必须被本批 candidate 引用（contract §4）
	ids := map[string]bool{}
	for _, cd := range batch.Candidates {
		for _, e := range cd.EvidenceIDs {
			ids[e] = true
		}
	}
	if len(batch.Evidence) != 1 {
		t.Fatalf("expected 1 evidence, got %d", len(batch.Evidence))
	}
	for _, ev := range batch.Evidence {
		if !ids[ev.EvidenceID] {
			t.Fatalf("orphan evidence: %s", ev.EvidenceID)
		}
		if ev.SourceType != "manifest" {
			t.Fatalf("unexpected evidence source type: %s", ev.SourceType)
		}
	}
}

func TestCollectSkipsNonDifyCompose(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "plain-web", "compose.yaml"), nonDifyComposeFixture)
	writeFile(t, filepath.Join(dir, "notes", "readme.txt"), "not a compose file")

	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{dir}},
		Limits: defaultLimits(),
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 0 || len(batch.Evidence) != 0 {
		t.Fatalf("non-dify compose must yield empty batch, got %d candidates", len(batch.Candidates))
	}
}

func TestCollectSkipsHiddenAndVendorDirs(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, ".hidden", "docker-compose.yaml"), difyComposeFixture)
	writeFile(t, filepath.Join(dir, "node_modules", "pkg", "docker-compose.yaml"), difyComposeFixture)
	writeFile(t, filepath.Join(dir, "vendor", "pkg", "compose.yml"), difyComposeFixture)

	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{dir}},
		Limits: defaultLimits(),
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 0 {
		t.Fatalf("hidden/node_modules/vendor dirs must be skipped, got %d candidates", len(batch.Candidates))
	}
}

func TestCollectSkipsSymlinkEscape(t *testing.T) {
	dir := t.TempDir()
	outside := t.TempDir()
	writeFile(t, filepath.Join(outside, "docker-compose.yaml"), difyComposeFixture)
	if err := os.Symlink(filepath.Join(outside, "docker-compose.yaml"), filepath.Join(dir, "docker-compose.yaml")); err != nil {
		t.Skip("symlink not supported")
	}
	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{dir}},
		Limits: defaultLimits(),
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 0 {
		t.Fatal("symlink escape candidate emitted")
	}
}

func TestReadFileLimitedRefusesSymlink(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "real.yaml")
	link := filepath.Join(dir, "docker-compose.yaml")
	writeFile(t, target, difyComposeFixture)
	if err := os.Symlink(target, link); err != nil {
		t.Skip("symlink not supported")
	}
	if _, err := readFileLimited(link, 1<<20); err == nil {
		t.Fatal("DEV10-I: symlink path must not be read via openRegular")
	}
}

// 安全红线：environment 段的 secret 值（含不被 Redactor 规则覆盖的明文）
// 绝不出现在任何输出字段；content_hash 只覆盖 dify 相关行而非整个文件。
func TestSecretEnvValuesNeverLeak(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "my-dify", "docker-compose.yaml"), difyComposeFixture)

	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{dir}},
		Limits: defaultLimits(),
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 1 {
		t.Fatalf("expected 1 candidate, got %d", len(batch.Candidates))
	}
	out, err := json.Marshal(batch)
	if err != nil {
		t.Fatal(err)
	}
	for _, secret := range []string{"s3cr3t-plain-value-zzz", "hunter2-not-matched", "pg-secret-value-qqq", "SECRET_KEY", "DB_PASSWORD", "POSTGRES_PASSWORD"} {
		if strings.Contains(string(out), secret) {
			t.Fatalf("secret material leaked into output: %q", secret)
		}
	}
	// content_hash 不是整个文件的哈希
	whole := protocol.ContentHash([]byte(difyComposeFixture))
	if batch.Evidence[0].ContentHash == whole {
		t.Fatal("content_hash must cover dify-related lines only, not the whole compose file")
	}
}

// 哈希输入只含 service 名与镜像行：仅 environment 不同的两个 compose
// 必须产生相同的 content_hash（证明敏感段不进哈希输入）。
func TestFactsHashIgnoresEnvironment(t *testing.T) {
	a := parseDifyServices(difyComposeFixture)
	b := parseDifyServices(`services:
  api:
    image: langgenius/dify-api:0.6.8
    environment:
      SECRET_KEY: totally-different-value
  web:
    image: langgenius/dify-web:0.6.8
  sandbox:
    image: langgenius/dify-sandbox:0.2.1
`)
	if difyFactsHash(a) != difyFactsHash(b) {
		t.Fatal("facts hash must depend only on service names and dify image refs")
	}
}

func TestCollectByteBudgetTruncates(t *testing.T) {
	// 总预算只够第一个文件的一部分：必须显式 truncated，不得越预算多读
	dir := t.TempDir()
	pad := strings.Repeat("# padding\n", 64)
	writeFile(t, filepath.Join(dir, "a-dify", "docker-compose.yaml"), difyComposeFixture+pad)
	writeFile(t, filepath.Join(dir, "b-dify", "docker-compose.yaml"), difyComposeFixture+pad)

	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{dir}},
		Limits: protocol.CollectLimits{MaxFiles: 10, MaxBytes: 64},
	})
	if err != nil {
		t.Fatal(err)
	}
	if !batch.Truncated {
		t.Fatal("expected truncated flag when byte budget exhausted")
	}
	if len(batch.Candidates) > 1 {
		t.Fatalf("budget exhausted must stop collection, got %d candidates", len(batch.Candidates))
	}
}

func TestReadFileLimitedZeroBudget(t *testing.T) {
	// 剩余预算为 0/负数必须返回显式错误，禁止回退默认大小继续读
	dir := t.TempDir()
	path := filepath.Join(dir, "docker-compose.yaml")
	writeFile(t, path, difyComposeFixture)
	for _, budget := range []int64{0, -1} {
		if _, err := readFileLimited(path, budget); !errors.Is(err, errBudgetExhausted) {
			t.Fatalf("budget %d: expected errBudgetExhausted, got %v", budget, err)
		}
	}
	if data, err := readFileLimited(path, 16); err != nil || len(data) != 16 {
		t.Fatalf("budget 16: got len=%d err=%v", len(data), err)
	}
}

func TestCollectApiVersionOmittedWithoutTag(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "dify-no-tag", "compose.yaml"), `services:
  api:
    image: langgenius/dify-api
  web:
    image: langgenius/dify-web:latest
`)
	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{dir}},
		Limits: defaultLimits(),
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 1 {
		t.Fatalf("expected 1 candidate, got %d", len(batch.Candidates))
	}
	if _, ok := batch.Candidates[0].Attributes["api_version"]; ok {
		t.Fatal("api_version must be omitted when dify-api image has no tag")
	}
}

func TestDispatchOps(t *testing.T) {
	// describe：能力声明必须符合合同（无网络、输出上限）
	params, _ := json.Marshal(map[string]any{})
	resp := dispatch(&protocol.Request{ID: "r1", Op: protocol.OpDescribe, Params: params})
	if !resp.OK {
		t.Fatal("describe failed")
	}
	caps := capabilities()
	if caps.NetworkAccess {
		t.Fatal("network access must be false")
	}
	if caps.MaxOutputBytes != protocol.DefaultOutputLimitBytes {
		t.Fatalf("unexpected max_output_bytes: %d", caps.MaxOutputBytes)
	}
	// 未知 op：显式 unsupported，不静默
	resp = dispatch(&protocol.Request{ID: "r2", Op: "bogus", Params: params})
	if resp.OK || resp.Error == nil || resp.Error.Code != protocol.CodeUnsupported {
		t.Fatalf("unknown op must be unsupported: %+v", resp)
	}
	// health / checkpoint 可应答
	if resp := dispatch(&protocol.Request{ID: "r3", Op: protocol.OpHealth, Params: params}); !resp.OK {
		t.Fatal("health failed")
	}
	if resp := dispatch(&protocol.Request{ID: "r4", Op: protocol.OpCheckpoint, Params: params}); !resp.OK {
		t.Fatal("checkpoint failed")
	}
	// validate_scope 空 scope：ok 但 valid=false 语义由 errors 承载
	vsParams, _ := json.Marshal(map[string]any{"scope": map[string]any{}})
	resp = dispatch(&protocol.Request{ID: "r5", Op: protocol.OpValidateScope, Params: vsParams})
	if !resp.OK {
		t.Fatal("validate_scope op failed")
	}
	vr, _ := json.Marshal(resp.Result)
	if !strings.Contains(string(vr), "empty scope") {
		t.Fatalf("empty scope must be reported: %s", vr)
	}
}
