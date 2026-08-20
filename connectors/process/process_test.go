package main

// process Connector 测试（fixture 驱动，不依赖真实系统进程）：
//   - 分类：已知框架关键词（hermes→hermes、piagent→pi 等）置信度 0.8；
//     通用信号（ollama 等）置信度 0.6 且 framework "unknown"；
//     无信号进程（bash/nginx）跳过；
//   - 安全红线：含 `--api-key=sk-test123...` 的 args 绝不出现在任何输出字段
//     （整个批次序列化后断言原文/参数名均不存在）；
//   - ps 缺失显式报错（unsupported）；限额耗尽显式 Truncated。

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

func TestClassifyProcess(t *testing.T) {
	cases := []struct {
		name       string
		comm       string
		args       string
		candidate  bool
		framework  string
		confidence float64
		keyword    string
	}{
		{"hermes 框架命中", "python3", "python3 /opt/hermes/bin/hermes serve --port 8080", true, "hermes", 0.8, "hermes"},
		{"openclaw 框架命中", "node", "node /usr/lib/openclaw/dist/index.js", true, "openclaw", 0.8, "openclaw"},
		{"piagent 映射为 pi", "piagent", "piagent run --config /etc/piagent.yaml", true, "pi", 0.8, "piagent"},
		{"workbuddy 框架命中", "workbuddy", "workbuddy daemon", true, "workbuddy", 0.8, "workbuddy"},
		{"dify 框架命中", "python", "python /app/api/app.py --app dify-api", true, "dify", 0.8, "dify"},
		{"ollama 通用信号", "ollama", "ollama serve", true, "unknown", 0.6, "ollama"},
		{"mcp-server 通用信号", "node", "node /opt/tools/mcp-server.js", true, "unknown", 0.6, "mcp-server"},
		{"uvicorn 通用信号", "uvicorn", "uvicorn app:app --host 0.0.0.0", true, "unknown", 0.6, "uvicorn"},
		{"bash 无信号跳过", "bash", "-bash", false, "", 0, ""},
		{"nginx 无信号跳过", "nginx", "nginx: master process /usr/sbin/nginx", false, "", 0, ""},
		{"postgres 无信号跳过", "postgres", "postgres: checkpointer", false, "", 0, ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			cls := classifyProcess(tc.comm, tc.args)
			if cls.candidate != tc.candidate {
				t.Fatalf("candidate = %v, want %v", cls.candidate, tc.candidate)
			}
			if !tc.candidate {
				return
			}
			if cls.framework != tc.framework || cls.confidence != tc.confidence || cls.keyword != tc.keyword {
				t.Fatalf("got %+v, want framework=%q confidence=%v keyword=%q",
					cls, tc.framework, tc.confidence, tc.keyword)
			}
		})
	}
}

func TestParsePS(t *testing.T) {
	out := []byte("    1      0 systemd /sbin/init splash\n" +
		"  800      1 python3 python3 /opt/hermes/bin/hermes serve --port 8080\n" +
		"  100      1 bash -bash\n" +
		"\n" + // 空行跳过
		"garbage\n") // 字段不足跳过
	rows := parsePS(out)
	if len(rows) != 3 {
		t.Fatalf("parsed %d rows, want 3: %+v", len(rows), rows)
	}
	r := rows[1]
	if r.pid != "800" || r.ppid != "1" || r.comm != "python3" {
		t.Fatalf("bad row: %+v", r)
	}
	if r.args != "python3 /opt/hermes/bin/hermes serve --port 8080" {
		t.Fatalf("args must keep full remainder: %q", r.args)
	}
	// 无 args 列时回退为 comm
	if rows[2].args != "-bash" {
		t.Fatalf("args fallback = %q, want %q", rows[2].args, "-bash")
	}
}

// psFixture 覆盖：hermes 命中、ollama 命中、bash/nginx 跳过、
// 含 --api-key=sk-test123... 的 agent 进程（经 "agent" 通用信号命中）。
const psFixture = "    1      0 systemd /sbin/init\n" +
	"  800      1 python3 python3 /opt/hermes/bin/hermes serve --port 8080\n" +
	"  900      1 ollama ollama serve\n" +
	"  100      1 bash -bash\n" +
	"  200      1 nginx nginx: master process /usr/sbin/nginx\n" +
	"  700      1 python python /home/u/agent/app.py --api-key=sk-test1234567890ab\n"

func fixtureRunner(out string) psRunner {
	return func(ctx context.Context) ([]byte, error) { return []byte(out), nil }
}

func findCandidate(batch protocol.EvidenceBatch, comm string) *protocol.Candidate {
	for _, c := range batch.Candidates {
		if c.Name == comm {
			return c
		}
	}
	return nil
}

func TestCollectOpClassifies(t *testing.T) {
	batch, err := collectOp(protocol.ScanPlan{}, fixtureRunner(psFixture))
	if err != nil {
		t.Fatalf("collect: %v", err)
	}
	if len(batch.Candidates) != 3 {
		t.Fatalf("candidates = %d, want 3 (hermes/ollama/agent-app): %+v", len(batch.Candidates), batch.Candidates)
	}

	hermes := findCandidate(batch, "python3")
	if hermes == nil || hermes.Framework != "hermes" || hermes.Confidence != 0.8 {
		t.Fatalf("hermes process must be framework candidate: %+v", hermes)
	}
	if hermes.Attributes["ppid_comm"] != "systemd" {
		t.Fatalf("ppid_comm must resolve from snapshot: %v", hermes.Attributes)
	}
	if hermes.Attributes["discovery_basis"] != "process_scan" {
		t.Fatalf("discovery_basis missing: %v", hermes.Attributes)
	}
	if len(hermes.Attributes["args_sha256"]) != 16 {
		t.Fatalf("args_sha256 must be 16-hex truncated digest: %q", hermes.Attributes["args_sha256"])
	}
	if !strings.HasPrefix(hermes.CandidateID, "process_list:python3:") {
		t.Fatalf("candidate id shape: %q", hermes.CandidateID)
	}

	ollama := findCandidate(batch, "ollama")
	if ollama == nil || ollama.Framework != "unknown" || ollama.Confidence != 0.6 {
		t.Fatalf("ollama must be generic-signal candidate: %+v", ollama)
	}

	// bash/nginx 不产生候选
	if findCandidate(batch, "bash") != nil || findCandidate(batch, "nginx") != nil {
		t.Fatal("bash/nginx must not become candidates")
	}

	// 每条 evidence 必须被本批 candidate 引用（合同 §4），且 1:1
	if len(batch.Evidence) != len(batch.Candidates) {
		t.Fatalf("evidence %d != candidates %d", len(batch.Evidence), len(batch.Candidates))
	}
	evByID := map[string]*protocol.Evidence{}
	for _, ev := range batch.Evidence {
		evByID[ev.EvidenceID] = ev
	}
	for _, cand := range batch.Candidates {
		if len(cand.EvidenceIDs) != 1 {
			t.Fatalf("candidate %s evidence ids: %v", cand.CandidateID, cand.EvidenceIDs)
		}
		ev := evByID[cand.EvidenceIDs[0]]
		if ev == nil {
			t.Fatalf("candidate %s references missing evidence", cand.CandidateID)
		}
		if ev.SubjectRef == nil || *ev.SubjectRef != cand.CandidateID {
			t.Fatalf("evidence %s must reference candidate %s", ev.EvidenceID, cand.CandidateID)
		}
		if ev.SourceType != "process" || ev.ContentHash == "" {
			t.Fatalf("bad evidence: %+v", ev)
		}
	}
	if batch.Cursor == "" || !strings.HasPrefix(batch.Cursor, "process-cursor:") {
		t.Fatalf("cursor missing: %q", batch.Cursor)
	}
}

// 安全红线负向测试：args 中的 api-key 原文绝不出现在批次的任何序列化字段。
func TestCollectOpNeverLeaksArgs(t *testing.T) {
	batch, err := collectOp(protocol.ScanPlan{}, fixtureRunner(psFixture))
	if err != nil {
		t.Fatalf("collect: %v", err)
	}
	raw, err := json.Marshal(batch)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	s := string(raw)
	for _, forbidden := range []string{
		"sk-test123", "--api-key", "api-key",
		"/home/u/agent/app.py", // 完整 args 不得出现
	} {
		if strings.Contains(s, forbidden) {
			t.Fatalf("batch leaks raw args content %q: %s", forbidden, s)
		}
	}
	// 该进程仍须作为候选被发现（只存摘要与关键词）
	app := findCandidate(batch, "python")
	if app == nil {
		t.Fatal("agent app process must still be a candidate")
	}
	if app.Attributes["match_keyword"] != "agent" {
		t.Fatalf("match_keyword = %q, want %q", app.Attributes["match_keyword"], "agent")
	}
	if app.Attributes["args_sha256"] == "" {
		t.Fatal("args digest must be present")
	}
}

func TestCollectOpPSMissing(t *testing.T) {
	missing := func(ctx context.Context) ([]byte, error) { return nil, errPSMissing }
	if _, err := collectOp(protocol.ScanPlan{}, missing); !errors.Is(err, errPSMissing) {
		t.Fatalf("collect must surface errPSMissing, got %v", err)
	}
	// 协议映射：ps 缺失 → unsupported（显式覆盖缺口，不静默跳过）
	if pe := errToProtocol(errPSMissing); pe.Code != protocol.CodeUnsupported {
		t.Fatalf("errToProtocol code = %q, want %q", pe.Code, protocol.CodeUnsupported)
	}
}

func TestCollectOpRunnerFailure(t *testing.T) {
	boom := errors.New("exit status 1")
	failing := func(ctx context.Context) ([]byte, error) { return nil, boom }
	if _, err := collectOp(protocol.ScanPlan{}, failing); !errors.Is(err, boom) {
		t.Fatalf("runner failure must propagate, got %v", err)
	}
}

func TestCollectOpLimits(t *testing.T) {
	// MaxFiles=1：候选数受限且显式 Truncated
	plan := protocol.ScanPlan{Limits: protocol.CollectLimits{MaxFiles: 1}}
	batch, err := collectOp(plan, fixtureRunner(psFixture))
	if err != nil {
		t.Fatalf("collect: %v", err)
	}
	if len(batch.Candidates) != 1 || !batch.Truncated {
		t.Fatalf("MaxFiles limit: candidates=%d truncated=%v", len(batch.Candidates), batch.Truncated)
	}

	// MaxBytes 极小：ps 输出截断到行边界，显式 Truncated，不报错
	plan = protocol.ScanPlan{Limits: protocol.CollectLimits{MaxBytes: 60}}
	batch, err = collectOp(plan, fixtureRunner(psFixture))
	if err != nil {
		t.Fatalf("collect: %v", err)
	}
	if !batch.Truncated {
		t.Fatal("byte budget exceeded must set Truncated")
	}
	if len(batch.Candidates) > 1 {
		t.Fatalf("truncated output should yield at most the first rows' candidates: %+v", batch.Candidates)
	}
}

func TestDispatchOps(t *testing.T) {
	// describe：能力声明
	mkReq := func(op string, params string) *protocol.Request {
		return &protocol.Request{ID: "t1", Op: op, Params: json.RawMessage(params)}
	}
	resp := dispatch(mkReq(protocol.OpDescribe, "{}"))
	if !resp.OK {
		t.Fatalf("describe: %+v", resp.Error)
	}
	caps, ok := resp.Result.(protocol.ConnectorCapabilities)
	if !ok {
		t.Fatalf("describe result type %T", resp.Result)
	}
	if caps.NetworkAccess {
		t.Fatal("network_access must be false")
	}
	if caps.MaxOutputBytes != protocol.DefaultOutputLimitBytes {
		t.Fatalf("max_output_bytes = %d", caps.MaxOutputBytes)
	}

	// validate_scope：空 scope 合法（同 docker，无文件系统范围）
	resp = dispatch(mkReq(protocol.OpValidateScope, `{"scope":null}`))
	if !resp.OK || !resp.Result.(protocol.ValidationResult).Valid {
		t.Fatalf("empty scope must be valid: %+v", resp)
	}

	// plan_scan：默认限额
	resp = dispatch(mkReq(protocol.OpPlanScan, `{"scope":null}`))
	if !resp.OK {
		t.Fatalf("plan_scan: %+v", resp.Error)
	}
	plan := resp.Result.(protocol.ScanPlan)
	if plan.Limits.MaxFiles != defaultMaxProcesses || plan.Limits.MaxBytes != defaultMaxPSBytes {
		t.Fatalf("plan limits: %+v", plan.Limits)
	}

	// checkpoint：collect 后游标可见
	lastCursor = ""
	if _, err := collectOp(protocol.ScanPlan{}, fixtureRunner(psFixture)); err != nil {
		t.Fatalf("collect: %v", err)
	}
	resp = dispatch(mkReq(protocol.OpCheckpoint, "{}"))
	if !resp.OK || resp.Result.(protocol.CursorResult).Cursor == "" {
		t.Fatalf("checkpoint: %+v", resp)
	}

	// health：报告 ps 依赖
	resp = dispatch(mkReq(protocol.OpHealth, "{}"))
	if !resp.OK {
		t.Fatalf("health: %+v", resp.Error)
	}
	health := resp.Result.(protocol.HealthReport)
	if len(health.Dependencies) != 1 || health.Dependencies[0].Name != "ps_binary" {
		t.Fatalf("health: %+v", health)
	}

	// 未知 op：unsupported
	resp = dispatch(mkReq("bogus", "{}"))
	if resp.OK || resp.Error.Code != protocol.CodeUnsupported {
		t.Fatalf("unknown op must be unsupported: %+v", resp)
	}
}
