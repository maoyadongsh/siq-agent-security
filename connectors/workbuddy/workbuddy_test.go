package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

// writeInstall 在 dir 下布置一个 WorkBuddy 安装 fixture（约定布局：
// config.yaml + buddies.json）。
func writeInstall(t *testing.T, dir string, config string, buddies string) {
	t.Helper()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if config != "" {
		if err := os.WriteFile(filepath.Join(dir, configFileName), []byte(config), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	if buddies != "" {
		if err := os.WriteFile(filepath.Join(dir, buddiesFileName), []byte(buddies), 0o600); err != nil {
			t.Fatal(err)
		}
	}
}

// ValidateBatchReferencesLocal 是 Edge 侧规则的本地副本，用于断言批次
// 引用有效性（合同 §4：每条 evidence 必须被同批 candidate 引用）。
func ValidateBatchReferencesLocal(cands []*protocol.Candidate, evs []*protocol.Evidence) (kept, dropped []*protocol.Evidence, err error) {
	referenced := make(map[string]bool)
	for _, c := range cands {
		for _, id := range c.EvidenceIDs {
			referenced[id] = true
		}
	}
	for _, ev := range evs {
		if referenced[ev.EvidenceID] {
			kept = append(kept, ev)
		} else {
			dropped = append(dropped, ev)
		}
	}
	return kept, dropped, nil
}

func TestValidateScopeOp(t *testing.T) {
	dir := t.TempDir()
	// trailing "/*" glob 需要至少一个已存在的子目录匹配。
	if err := os.Mkdir(filepath.Join(dir, "sub"), 0o755); err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		name      string
		scope     *protocol.Scope
		wantValid bool
	}{
		{"nil scope", nil, false},
		{"empty scope", &protocol.Scope{}, false},
		{"filesystem root", &protocol.Scope{Roots: []string{"/"}}, false},
		{"env root", &protocol.Scope{Roots: []string{dir + "/.env-workbuddy"}}, false},
		{"secret root", &protocol.Scope{Roots: []string{dir + "/secret-stuff"}}, false},
		{"existing dir", &protocol.Scope{Roots: []string{dir}}, true},
		{"trailing glob", &protocol.Scope{Roots: []string{dir + "/*"}}, true},
		{"missing dir", &protocol.Scope{Roots: []string{dir + "/nope"}}, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			vr := validateScopeOp(tc.scope)
			if vr.Valid != tc.wantValid {
				t.Fatalf("valid=%v want %v (errors=%v)", vr.Valid, tc.wantValid, vr.Errors)
			}
		})
	}
}

func TestPlanScanOp(t *testing.T) {
	dir := t.TempDir()
	// 空 scope：默认根 ~/.workbuddy 顶替
	plan, err := planScanOp(planScanParams{})
	if err != nil {
		t.Fatal(err)
	}
	if len(plan.Scope.Roots) != 1 || plan.Scope.Roots[0] != defaultRoot {
		t.Errorf("default roots=%v want [%s]", plan.Scope.Roots, defaultRoot)
	}
	// 显式 roots 覆盖默认根
	plan, err = planScanOp(planScanParams{Scope: &protocol.Scope{Roots: []string{dir}}})
	if err != nil {
		t.Fatal(err)
	}
	if plan.Scope.Roots[0] != dir {
		t.Errorf("explicit root not honored: %v", plan.Scope.Roots)
	}
	// 显式 roots 必须过 ValidateScopeSafety
	if _, err = planScanOp(planScanParams{Scope: &protocol.Scope{Roots: []string{"/"}}}); err == nil {
		t.Error("filesystem root must be rejected by plan_scan")
	}
	if _, err = planScanOp(planScanParams{Scope: &protocol.Scope{Roots: []string{dir + "/missing"}}}); err == nil {
		t.Error("missing root must be rejected by plan_scan")
	}
}

func TestDescribeCapabilities(t *testing.T) {
	resp := dispatch(&protocol.Request{ID: "r1", Op: protocol.OpDescribe, Params: json.RawMessage(`{}`)})
	if !resp.OK {
		t.Fatalf("describe failed: %+v", resp.Error)
	}
	caps, ok := resp.Result.(protocol.ConnectorCapabilities)
	if !ok {
		t.Fatalf("describe result type %T", resp.Result)
	}
	if caps.NetworkAccess {
		t.Error("network_access must be false")
	}
	if caps.MaxOutputBytes != protocol.DefaultOutputLimitBytes {
		t.Errorf("max_output_bytes=%d want %d", caps.MaxOutputBytes, protocol.DefaultOutputLimitBytes)
	}
	if len(caps.Objects) != 1 || caps.Objects[0] != "workbuddy_profile" {
		t.Errorf("objects=%v want [workbuddy_profile]", caps.Objects)
	}
}

func TestCollectBuddies(t *testing.T) {
	root := t.TempDir()
	install := filepath.Join(root, ".workbuddy")
	buddies := `{"buddies": [
		{"id": "buddy-1", "name": "Legal Advisor", "role": "advisor", "skills": ["search", "draft"]},
		{"id": "buddy-2", "name": "Ops Bot", "role": "operator", "skills": ["deploy"], "apiKey": "sk-secretvalue123456", "token": "tok-secret-abcdef"}
	]}`
	writeInstall(t, install, "model:\n  default: gpt-4o\napiKey: sk-config-secret999\n", buddies)
	// .env 绝不读取：内容不得出现在任何输出字段。
	if err := os.WriteFile(filepath.Join(install, ".env"), []byte("OPENAI_API_KEY=sk-env-secret-value"), 0o600); err != nil {
		t.Fatal(err)
	}

	plan := protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{install}},
		Limits: protocol.CollectLimits{MaxFiles: 200, MaxBytes: 1 << 20},
	}
	batch, err := collectOp(plan)
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 2 {
		t.Fatalf("candidates=%d want 2", len(batch.Candidates))
	}
	if batch.Truncated {
		t.Error("batch must not be truncated")
	}
	cand := batch.Candidates[0]
	if cand.CandidateID != "workbuddy:buddy-1" {
		t.Errorf("candidate_id=%q", cand.CandidateID)
	}
	if cand.SourceType != "workbuddy_profile" || cand.Framework != "workbuddy" {
		t.Errorf("source_type=%q framework=%q", cand.SourceType, cand.Framework)
	}
	if cand.Confidence != 1.0 {
		t.Errorf("confidence=%v want 1.0", cand.Confidence)
	}
	if cand.Name != "Legal Advisor" {
		t.Errorf("name=%q", cand.Name)
	}
	if cand.Attributes["role"] != "advisor" {
		t.Errorf("attributes.role=%q", cand.Attributes["role"])
	}
	if cand.Attributes["skills"] != "draft,search" {
		t.Errorf("attributes.skills=%q want draft,search", cand.Attributes["skills"])
	}
	if cand.Attributes["has_config"] != "true" {
		t.Errorf("attributes.has_config=%q want true", cand.Attributes["has_config"])
	}
	if len(cand.EvidenceIDs) != 1 {
		t.Fatalf("evidence_ids=%v want 1 reference", cand.EvidenceIDs)
	}

	if len(batch.Evidence) != 2 {
		t.Fatalf("evidence=%d want 2", len(batch.Evidence))
	}
	ev := batch.Evidence[0]
	if ev.SourceType != "manifest" {
		t.Errorf("evidence source_type=%q want manifest", ev.SourceType)
	}
	if ev.ContentHash == "" {
		t.Error("evidence missing content_hash")
	}
	if ev.RedactionProfile != protocol.RedactionProfile {
		t.Errorf("redaction_profile=%q", ev.RedactionProfile)
	}
	if ev.SubjectRef == nil || *ev.SubjectRef != cand.CandidateID {
		t.Errorf("subject_ref=%v want %s", ev.SubjectRef, cand.CandidateID)
	}
	if !strings.HasPrefix(batch.Cursor, "workbuddy-cursor:") {
		t.Errorf("cursor=%q", batch.Cursor)
	}

	// 合同 §4：每条 evidence 必须被同批 candidate 引用。
	kept, dropped, err := ValidateBatchReferencesLocal(batch.Candidates, batch.Evidence)
	if err != nil {
		t.Fatal(err)
	}
	if len(kept) != 2 || len(dropped) != 0 {
		t.Errorf("batch references: kept=%d dropped=%d", len(kept), len(dropped))
	}

	// 安全红线：apiKey/token/.env/config.yaml 的 secret 值绝不进输出。
	raw, _ := json.Marshal(batch)
	for _, secret := range []string{"sk-secretvalue123456", "tok-secret-abcdef", "sk-env-secret-value", "sk-config-secret999"} {
		if strings.Contains(string(raw), secret) {
			t.Errorf("secret %q leaked into batch output", secret)
		}
	}
}

func TestCollectNoConfigFile(t *testing.T) {
	root := t.TempDir()
	install := filepath.Join(root, ".workbuddy")
	writeInstall(t, install, "", `{"buddies": [{"id": "b1", "name": "Solo", "role": "helper", "skills": []}]}`)

	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{install}},
		Limits: protocol.CollectLimits{MaxFiles: 200, MaxBytes: 1 << 20},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 1 {
		t.Fatalf("candidates=%d want 1", len(batch.Candidates))
	}
	if batch.Candidates[0].Attributes["has_config"] != "false" {
		t.Errorf("has_config=%q want false", batch.Candidates[0].Attributes["has_config"])
	}
}

func TestCollectMalformedBuddiesJSON(t *testing.T) {
	root := t.TempDir()
	install := filepath.Join(root, ".workbuddy")
	writeInstall(t, install, "model:\n  default: gpt-4o\n", `{"buddies": [{"id": "b1"`)

	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{install}},
		Limits: protocol.CollectLimits{MaxFiles: 200, MaxBytes: 1 << 20},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 0 || len(batch.Evidence) != 0 {
		t.Errorf("malformed buddies.json must yield empty batch (candidates=%d evidence=%d)", len(batch.Candidates), len(batch.Evidence))
	}
}

func TestCollectSymlinkEscape(t *testing.T) {
	root := t.TempDir()
	outside := t.TempDir()
	if err := os.WriteFile(filepath.Join(outside, buddiesFileName), []byte(`{"buddies": [{"id": "evil", "name": "E", "role": "r"}]}`), 0o600); err != nil {
		t.Fatal(err)
	}
	install := filepath.Join(root, ".workbuddy")
	if err := os.MkdirAll(install, 0o755); err != nil {
		t.Fatal(err)
	}
	// Contract §4 negative test: scope 内符号链接指向 scope 外 —— 必须跳过。
	if err := os.Symlink(filepath.Join(outside, buddiesFileName), filepath.Join(install, buddiesFileName)); err != nil {
		t.Skipf("cannot create symlink: %v", err)
	}
	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{install}},
		Limits: protocol.CollectLimits{MaxFiles: 200, MaxBytes: 1 << 20},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 0 {
		t.Errorf("symlink escape must be skipped, got %d candidates", len(batch.Candidates))
	}
}

func TestCollectByteBudget(t *testing.T) {
	root := t.TempDir()
	install := filepath.Join(root, ".workbuddy")
	writeInstall(t, install, "", `{"buddies": [{"id": "b1", "name": "Big", "role": "r", "skills": ["a", "b", "c"]}]}`)

	cases := []struct {
		name      string
		maxBytes  int64
		wantCands int
		wantTrunc bool
	}{
		{"budget smaller than file truncates", 16, 0, true},
		{"zero budget falls back to default limit", 0, 1, false}, // limits<=0 回退默认预算，可正常采集
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			batch, err := collectOp(protocol.ScanPlan{
				Scope:  &protocol.Scope{Roots: []string{install}},
				Limits: protocol.CollectLimits{MaxFiles: 200, MaxBytes: tc.maxBytes},
			})
			if err != nil {
				t.Fatal(err)
			}
			if len(batch.Candidates) != tc.wantCands {
				t.Errorf("candidates=%d want %d", len(batch.Candidates), tc.wantCands)
			}
			if batch.Truncated != tc.wantTrunc {
				t.Errorf("truncated=%v want %v", batch.Truncated, tc.wantTrunc)
			}
		})
	}
}

func TestCollectBudgetExhaustedAcrossRoots(t *testing.T) {
	root := t.TempDir()
	i1 := filepath.Join(root, "one")
	i2 := filepath.Join(root, "two")
	body := `{"buddies": [{"id": "b1", "name": "N", "role": "r"}]}`
	writeInstall(t, i1, "", body)
	writeInstall(t, i2, "", body)

	fi, err := os.Stat(filepath.Join(i1, buddiesFileName))
	if err != nil {
		t.Fatal(err)
	}
	// 预算恰好只够第一个 root：第二个 root 必须显式截断（errBudgetExhausted）。
	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{i1, i2}},
		Limits: protocol.CollectLimits{MaxFiles: 200, MaxBytes: fi.Size()},
	})
	if err != nil {
		t.Fatal(err)
	}
	if !batch.Truncated {
		t.Error("expected truncated=true when byte budget is exhausted across roots")
	}
	if len(batch.Candidates) != 1 {
		t.Errorf("candidates=%d want 1", len(batch.Candidates))
	}
}

func TestCollectMaxFilesTruncation(t *testing.T) {
	root := t.TempDir()
	install := filepath.Join(root, ".workbuddy")
	writeInstall(t, install, "", `{"buddies": [
		{"id": "b1", "name": "A", "role": "r"},
		{"id": "b2", "name": "B", "role": "r"}
	]}`)
	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{install}},
		Limits: protocol.CollectLimits{MaxFiles: 1, MaxBytes: 1 << 20},
	})
	if err != nil {
		t.Fatal(err)
	}
	if !batch.Truncated {
		t.Error("expected truncated=true when max_files is hit")
	}
	if len(batch.Candidates) != 1 {
		t.Errorf("candidates=%d want 1", len(batch.Candidates))
	}
}

func TestCollectNotInstalled(t *testing.T) {
	// 默认根 ~/.workbuddy 不存在：空批次而非报错（任务规格）。
	home := t.TempDir()
	t.Setenv("HOME", home)
	batch, err := collectOp(protocol.ScanPlan{
		Scope:  nil,
		Limits: protocol.CollectLimits{MaxFiles: 200, MaxBytes: 1 << 20},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 0 || len(batch.Evidence) != 0 {
		t.Errorf("missing install must yield empty batch (candidates=%d evidence=%d)", len(batch.Candidates), len(batch.Evidence))
	}
	if batch.Truncated {
		t.Error("empty batch must not be truncated")
	}
}

func TestCollectRejectsInvalidExplicitScope(t *testing.T) {
	dir := t.TempDir()
	// 显式 roots 在 collect 侧纵深防御校验。
	if _, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{dir + "/missing"}},
		Limits: protocol.CollectLimits{MaxFiles: 200, MaxBytes: 1 << 20},
	}); err == nil {
		t.Error("collect with nonexistent explicit root must fail (scope_invalid)")
	}
}

func TestRedactsKeyShapedValues(t *testing.T) {
	root := t.TempDir()
	install := filepath.Join(root, ".workbuddy")
	writeInstall(t, install, "", `{"buddies": [{"id": "b1", "name": "bot api_key=sk-livekey99999", "role": "token=tok-role-secret1", "skills": ["search"]}]}`)

	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{install}},
		Limits: protocol.CollectLimits{MaxFiles: 200, MaxBytes: 1 << 20},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 1 {
		t.Fatalf("candidates=%d want 1", len(batch.Candidates))
	}
	cand := batch.Candidates[0]
	if strings.Contains(cand.Name, "sk-livekey99999") || strings.Contains(cand.Attributes["role"], "tok-role-secret1") {
		t.Errorf("secret-shaped values must be redacted: name=%q role=%q", cand.Name, cand.Attributes["role"])
	}
	if !strings.Contains(cand.Name, "[REDACTED]") {
		t.Errorf("name=%q want redaction marker", cand.Name)
	}
}

func TestDispatchUnknownOp(t *testing.T) {
	resp := dispatch(&protocol.Request{ID: "r9", Op: "nope", Params: json.RawMessage(`{}`)})
	if resp.OK {
		t.Fatal("unknown op must fail")
	}
	if resp.Error.Code != protocol.CodeUnsupported {
		t.Errorf("code=%q want %q", resp.Error.Code, protocol.CodeUnsupported)
	}
}

func TestCheckpointAndHealth(t *testing.T) {
	lastCursor = "workbuddy-cursor:test"
	resp := dispatch(&protocol.Request{ID: "r10", Op: protocol.OpCheckpoint, Params: json.RawMessage(`{}`)})
	if !resp.OK {
		t.Fatalf("checkpoint failed: %+v", resp.Error)
	}
	cur, ok := resp.Result.(protocol.CursorResult)
	if !ok || cur.Cursor != "workbuddy-cursor:test" {
		t.Errorf("checkpoint result=%+v", resp.Result)
	}
	resp = dispatch(&protocol.Request{ID: "r11", Op: protocol.OpHealth, Params: json.RawMessage(`{}`)})
	if !resp.OK {
		t.Fatalf("health failed: %+v", resp.Error)
	}
	rep, ok := resp.Result.(protocol.HealthReport)
	if !ok {
		t.Fatalf("health result type %T", resp.Result)
	}
	if rep.Version != connectorVersion || len(rep.Dependencies) != 1 || rep.Dependencies[0].Name != "workbuddy_home" {
		t.Errorf("health report=%+v", rep)
	}
}
