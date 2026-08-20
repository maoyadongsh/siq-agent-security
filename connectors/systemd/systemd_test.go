package main

// P1-4 systemd 发现源测试：fake systemctl runner 注入，不依赖真实 systemd。
// 覆盖：已知框架 unit 命中、通用 agent 信号命中、无关服务不产生候选、
// systemctl 缺失显式报错、ExecStart 敏感参数不进入 attributes、
// evidence 必须被同批 candidate 引用（合同 §4）。

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"testing"
	"time"

	"siq-agent-security/edge/agent/protocol"
)

// fakeRunner 返回一个可注入 runSystemctl 的假实现：
// list-unit-files 返回 units 原文，show <unit> 查 shows 表。
func fakeRunner(units string, shows map[string]string) func(context.Context, ...string) ([]byte, error) {
	return func(_ context.Context, args ...string) ([]byte, error) {
		if len(args) > 0 && args[0] == "list-unit-files" {
			return []byte(units), nil
		}
		if len(args) > 0 && args[0] == "show" {
			if out, ok := shows[args[1]]; ok {
				return []byte(out), nil
			}
			return nil, fmt.Errorf("unit %s not found", args[1])
		}
		return nil, fmt.Errorf("unexpected systemctl args: %v", args)
	}
}

// withFakes 注入 fake lookPath/runner 并设置 opTimeout，测试结束自动恢复。
func withFakes(t *testing.T, runner func(context.Context, ...string) ([]byte, error)) {
	t.Helper()
	origLook, origRun, origTimeout := lookPath, runSystemctl, opTimeout
	lookPath = func(file string) (string, error) {
		if file == "systemctl" {
			return "/usr/bin/systemctl", nil
		}
		return "", errors.New("not found")
	}
	runSystemctl = runner
	opTimeout = time.Minute
	t.Cleanup(func() {
		lookPath, runSystemctl, opTimeout = origLook, origRun, origTimeout
		lastCursor = ""
	})
}

const fixtureUnits = `hermes.service enabled enabled
openclaw.service enabled enabled
piagent.service disabled disabled
workbuddy.service enabled enabled
dify-api.service enabled enabled
mcp-gateway.service enabled enabled
backupagent.service enabled enabled
nginx.service enabled enabled
postgres.service enabled enabled
`

func showFixture(id, desc, state, execStart string) string {
	return "Id=" + id + "\nDescription=" + desc + "\nActiveState=" + state + "\nExecStart=" + execStart + "\n"
}

var fixtureShows = map[string]string{
	"hermes.service":      showFixture("hermes.service", "Hermes agent runtime", "active", "{ path=/opt/hermes/bin/hermes ; argv[]=/opt/hermes/bin/hermes serve ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }"),
	"openclaw.service":    showFixture("openclaw.service", "OpenClaw agent", "active", "{ path=/usr/local/bin/openclaw ; argv[]=/usr/local/bin/openclaw run ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }"),
	"piagent.service":     showFixture("piagent.service", "Pi agent", "inactive", "{ path=/opt/pi/piagent ; argv[]=/opt/pi/piagent start ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }"),
	"workbuddy.service":   showFixture("workbuddy.service", "WorkBuddy assistant", "active", "{ path=/usr/bin/workbuddy ; argv[]=/usr/bin/workbuddy daemon ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }"),
	"dify-api.service":    showFixture("dify-api.service", "Dify API", "active", "{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 /app/api/app.py ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }"),
	"mcp-gateway.service": showFixture("mcp-gateway.service", "MCP gateway", "active", "{ path=/usr/local/bin/mcp-gateway ; argv[]=/usr/local/bin/mcp-gateway serve ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }"),
	// 名称含通用信号 agent，但 exec 路径无任何智能体信号 → 再确认剔除
	"backupagent.service": showFixture("backupagent.service", "Backup sync daemon", "active", "{ path=/usr/bin/rsync ; argv[]=/usr/bin/rsync -a /data /backup ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }"),
}

func collectFixture(t *testing.T) protocol.EvidenceBatch {
	t.Helper()
	withFakes(t, fakeRunner(fixtureUnits, fixtureShows))
	batch, err := collectOp(protocol.ScanPlan{})
	if err != nil {
		t.Fatalf("collectOp: %v", err)
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

func TestClassifyNameTable(t *testing.T) {
	cases := []struct {
		name       string
		unit       string
		candidate  bool
		framework  string
		confidence float64
	}{
		{"framework hermes", "hermes.service", true, "hermes", 0.8},
		{"framework openclaw", "openclaw.service", true, "openclaw", 0.8},
		{"framework piagent maps to pi", "piagent.service", true, "pi", 0.8},
		{"framework workbuddy", "workbuddy.service", true, "workbuddy", 0.8},
		{"framework dify", "dify-api.service", true, "dify", 0.8},
		{"generic mcp signal", "mcp-gateway.service", true, "unknown", 0.6},
		{"generic ollama signal", "ollama.service", true, "unknown", 0.6},
		{"generic langchain signal", "langchain-worker.service", true, "unknown", 0.6},
		{"generic agent signal", "myagent.service", true, "unknown", 0.6},
		{"no signal nginx", "nginx.service", false, "", 0},
		{"no signal postgres", "postgres.service", false, "", 0},
		{"no signal redis", "redis.service", false, "", 0},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			cls := classifyName(tc.unit)
			if cls.candidate != tc.candidate {
				t.Fatalf("%s: candidate=%v want %v", tc.unit, cls.candidate, tc.candidate)
			}
			if !tc.candidate {
				return
			}
			if cls.framework != tc.framework || cls.confidence != tc.confidence {
				t.Fatalf("%s: got %+v", tc.unit, cls)
			}
			if cls.basis != "unit_keyword" {
				t.Fatalf("%s: basis must be unit_keyword, got %q", tc.unit, cls.basis)
			}
		})
	}
}

func TestReconfirmTable(t *testing.T) {
	cases := []struct {
		name      string
		cls       unitClassification
		head      string
		candidate bool
		framework string
		basis     string
	}{
		{"generic name + signal in exec path keeps candidate",
			unitClassification{candidate: true, framework: "unknown", confidence: 0.6, basis: "unit_keyword"},
			"/usr/local/bin/mcp-gateway", true, "unknown", "unit_keyword"},
		{"generic name + no signal in exec path drops candidate",
			unitClassification{candidate: true, framework: "unknown", confidence: 0.6, basis: "unit_keyword"},
			"/usr/bin/rsync", false, "", ""},
		{"framework name survives plain exec path",
			unitClassification{candidate: true, framework: "dify", confidence: 0.8, basis: "unit_keyword"},
			"/usr/bin/python3", true, "dify", "unit_keyword"},
		{"exec path framework keyword upgrades generic hit",
			unitClassification{candidate: true, framework: "unknown", confidence: 0.6, basis: "unit_keyword"},
			"/opt/hermes/bin/hermes", true, "hermes", "exec_path"},
		// 回归：名称初筛未命中任何信号（candidate=false，framework 零值 ""）时，
		// exec 路径仍必须能独立判定候选——这是结构性漏报的核心场景。
		{"no name signal + exec path matches known framework",
			unitClassification{candidate: false},
			"/opt/hermes/bin/hermes", true, "hermes", "exec_path"},
		{"no name signal + exec path matches generic signal",
			unitClassification{candidate: false},
			"/usr/local/bin/myagent", true, "unknown", "exec_path"},
		{"no name signal + no exec signal stays non-candidate",
			unitClassification{candidate: false},
			"/usr/bin/rsync", false, "", ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := reconfirm(tc.cls, tc.head)
			if got.candidate != tc.candidate || (tc.candidate && got.framework != tc.framework) {
				t.Fatalf("reconfirm(%+v, %q) = %+v", tc.cls, tc.head, got)
			}
			if tc.candidate && got.basis != tc.basis {
				t.Fatalf("reconfirm(%+v, %q) basis = %q, want %q", tc.cls, tc.head, got.basis, tc.basis)
			}
		})
	}
}

func TestCollectKnownFrameworkUnits(t *testing.T) {
	batch := collectFixture(t)
	want := map[string]struct {
		framework  string
		confidence float64
	}{
		"systemd:hermes.service":    {"hermes", 0.8},
		"systemd:openclaw.service":  {"openclaw", 0.8},
		"systemd:piagent.service":   {"pi", 0.8},
		"systemd:workbuddy.service": {"workbuddy", 0.8},
		"systemd:dify-api.service":  {"dify", 0.8},
	}
	for id, w := range want {
		cand := candidateByID(batch, id)
		if cand == nil {
			t.Fatalf("missing candidate %s", id)
		}
		if cand.SourceType != "systemd" || cand.Framework != w.framework || cand.Confidence != w.confidence {
			t.Fatalf("%s: %+v", id, cand)
		}
		if cand.Attributes["discovery_basis"] != "unit_keyword" {
			t.Fatalf("%s: discovery_basis missing: %v", id, cand.Attributes)
		}
	}
}

func TestCollectGenericSignalUnit(t *testing.T) {
	batch := collectFixture(t)
	cand := candidateByID(batch, "systemd:mcp-gateway.service")
	if cand == nil {
		t.Fatal("mcp-gateway.service must surface as generic-signal candidate")
	}
	if cand.Framework != "unknown" || cand.Confidence != 0.6 {
		t.Fatalf("generic signal candidate: %+v", cand)
	}
}

func TestCollectIgnoresNonAgentUnits(t *testing.T) {
	batch := collectFixture(t)
	for _, id := range []string{"systemd:nginx.service", "systemd:postgres.service"} {
		if candidateByID(batch, id) != nil {
			t.Fatalf("non-agent unit %s must not become candidate", id)
		}
	}
	// 名称泛信号 + exec 无信号 → 再确认剔除
	if candidateByID(batch, "systemd:backupagent.service") != nil {
		t.Fatal("backupagent.service (rsync exec) must be dropped by reconfirm")
	}
}

func TestCollectDiscoversRenamedUnitViaExecStart(t *testing.T) {
	// 结构性漏报回归：unit 名称本身不含任何智能体关键词（如运维改名为
	// backend.service），但 ExecStart 实际启动的是已知框架二进制——修复前
	// 这类 unit 会在名称初筛阶段被直接跳过，永远不会被发现。
	units := "backend.service enabled enabled\ncustom-worker.service enabled enabled\nplain-cron.service enabled enabled\n"
	shows := map[string]string{
		"backend.service": showFixture("backend.service", "Backend process", "active",
			"{ path=/opt/hermes/bin/hermes ; argv[]=/opt/hermes/bin/hermes serve ; ignore_errors=no ; pid=0 ; code=(null) ; status=0/0 }"),
		"custom-worker.service": showFixture("custom-worker.service", "Custom worker", "active",
			"{ path=/usr/local/bin/myagent ; argv[]=/usr/local/bin/myagent run ; ignore_errors=no ; pid=0 ; code=(null) ; status=0/0 }"),
		"plain-cron.service": showFixture("plain-cron.service", "Plain cron job", "active",
			"{ path=/usr/bin/rsync ; argv[]=/usr/bin/rsync -a /data /backup ; ignore_errors=no ; pid=0 ; code=(null) ; status=0/0 }"),
	}
	withFakes(t, fakeRunner(units, shows))
	batch, err := collectOp(protocol.ScanPlan{})
	if err != nil {
		t.Fatalf("collectOp: %v", err)
	}

	hermes := candidateByID(batch, "systemd:backend.service")
	if hermes == nil {
		t.Fatal("backend.service running hermes via ExecStart must be discovered despite non-matching unit name")
	}
	if hermes.Framework != "hermes" || hermes.Attributes["discovery_basis"] != "exec_path" {
		t.Fatalf("backend.service must be attributed to hermes via exec_path: %+v", hermes)
	}

	generic := candidateByID(batch, "systemd:custom-worker.service")
	if generic == nil {
		t.Fatal("custom-worker.service running a generic agent binary must be discovered via ExecStart")
	}
	if generic.Framework != "unknown" || generic.Confidence != 0.6 || generic.Attributes["discovery_basis"] != "exec_path" {
		t.Fatalf("custom-worker.service classification: %+v", generic)
	}

	if candidateByID(batch, "systemd:plain-cron.service") != nil {
		t.Fatal("plain-cron.service (rsync, no signal anywhere) must not become a candidate")
	}
}

func TestCollectSystemctlMissing(t *testing.T) {
	origLook := lookPath
	lookPath = func(string) (string, error) { return "", errors.New("not found") }
	t.Cleanup(func() { lookPath = origLook })

	if _, err := collectOp(protocol.ScanPlan{}); !errors.Is(err, errSystemctlMissing) {
		t.Fatalf("expected errSystemctlMissing, got %v", err)
	}
	// 协议层映射为 unsupported（显式覆盖缺口），不得静默空批次
	perr := errToProtocol(errSystemctlMissing)
	if perr.Code != protocol.CodeUnsupported {
		t.Fatalf("missing systemctl must map to %q, got %q", protocol.CodeUnsupported, perr.Code)
	}
}

func TestCollectListFailureIsExplicitError(t *testing.T) {
	withFakes(t, func(context.Context, ...string) ([]byte, error) {
		return nil, errors.New("exit status 1")
	})
	if _, err := collectOp(protocol.ScanPlan{}); err == nil {
		t.Fatal("systemctl list failure must surface as explicit error, not empty batch")
	}
}

func TestCollectRedactsExecSecrets(t *testing.T) {
	units := "dify-api.service enabled enabled\n"
	shows := map[string]string{
		"dify-api.service": showFixture("dify-api.service", "Dify API", "active",
			"{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 app.py --token=supersecrettoken123 --api_key=sk-livekey123456789 ; ignore_errors=no ; pid=0 ; code=(null) ; status=0/0 }"),
	}
	withFakes(t, fakeRunner(units, shows))
	batch, err := collectOp(protocol.ScanPlan{})
	if err != nil {
		t.Fatalf("collectOp: %v", err)
	}
	cand := candidateByID(batch, "systemd:dify-api.service")
	if cand == nil {
		t.Fatal("expected dify candidate")
	}
	summary := cand.Attributes["exec_summary"]
	for _, secret := range []string{"supersecrettoken123", "sk-livekey123456789"} {
		if strings.Contains(summary, secret) {
			t.Fatalf("exec_summary leaked secret %q: %s", secret, summary)
		}
	}
	if !strings.Contains(summary, "[REDACTED]") {
		t.Fatalf("exec_summary must show redaction marker: %s", summary)
	}
	if len(summary) > 256 {
		t.Fatalf("exec_summary must be truncated to 256, got %d", len(summary))
	}
}

func TestEvidenceReferencedByCandidates(t *testing.T) {
	batch := collectFixture(t)
	if len(batch.Candidates) == 0 || len(batch.Evidence) == 0 {
		t.Fatal("fixture must produce candidates and evidence")
	}
	candIDs := map[string]bool{}
	evIDs := map[string]bool{}
	for _, c := range batch.Candidates {
		candIDs[c.CandidateID] = true
	}
	for _, ev := range batch.Evidence {
		evIDs[ev.EvidenceID] = true
		if ev.SubjectRef == nil || !candIDs[*ev.SubjectRef] {
			t.Fatalf("evidence %s not referenced by any candidate in batch", ev.EvidenceID)
		}
		if ev.SourceType != "systemd" || ev.ContentHash == "" {
			t.Fatalf("evidence %s malformed: %+v", ev.EvidenceID, ev)
		}
	}
	for _, c := range batch.Candidates {
		for _, id := range c.EvidenceIDs {
			if !evIDs[id] {
				t.Fatalf("candidate %s references missing evidence %s", c.CandidateID, id)
			}
		}
	}
	if !strings.HasPrefix(batch.Cursor, "systemd-cursor:") {
		t.Fatalf("cursor missing: %q", batch.Cursor)
	}
}

func TestValidateScopeOp(t *testing.T) {
	if r := validateScopeOp(nil); !r.Valid {
		t.Fatalf("empty scope must be valid for host-level connector: %+v", r)
	}
	if r := validateScopeOp(&protocol.Scope{}); !r.Valid {
		t.Fatalf("empty roots must be valid: %+v", r)
	}
	if r := validateScopeOp(&protocol.Scope{Roots: []string{"/"}}); r.Valid {
		t.Fatal("root path / must be rejected by shared scope safety rules")
	}
}

func TestCapabilities(t *testing.T) {
	caps := capabilities()
	if caps.NetworkAccess {
		t.Fatal("network_access must be false")
	}
	if caps.MaxOutputBytes != protocol.DefaultOutputLimitBytes {
		t.Fatalf("max_output_bytes = %d, want %d", caps.MaxOutputBytes, protocol.DefaultOutputLimitBytes)
	}
}

func TestHealthOpReportsMissingSystemctl(t *testing.T) {
	origLook := lookPath
	lookPath = func(string) (string, error) { return "", errors.New("not found") }
	t.Cleanup(func() { lookPath = origLook })

	rep := healthOp()
	if len(rep.Dependencies) != 1 || rep.Dependencies[0].OK {
		t.Fatalf("missing systemctl must be reported unavailable: %+v", rep)
	}
}

func TestDispatchOps(t *testing.T) {
	withFakes(t, fakeRunner(fixtureUnits, fixtureShows))

	// describe
	req := &protocol.Request{ID: "r1", Op: protocol.OpDescribe, Params: json.RawMessage(`{}`)}
	if resp := dispatch(req); !resp.OK {
		t.Fatalf("describe failed: %+v", resp.Error)
	}
	// collect via dispatch
	collectParamsJSON, err := json.Marshal(collectParams{Plan: protocol.ScanPlan{}})
	if err != nil {
		t.Fatal(err)
	}
	req = &protocol.Request{ID: "r2", Op: protocol.OpCollect, Params: collectParamsJSON}
	resp := dispatch(req)
	if !resp.OK {
		t.Fatalf("collect dispatch failed: %+v", resp.Error)
	}
	// checkpoint returns the cursor set by collect
	req = &protocol.Request{ID: "r3", Op: protocol.OpCheckpoint, Params: json.RawMessage(`{}`)}
	resp = dispatch(req)
	if !resp.OK {
		t.Fatalf("checkpoint failed: %+v", resp.Error)
	}
	// unknown op → unsupported
	req = &protocol.Request{ID: "r4", Op: "bogus", Params: json.RawMessage(`{}`)}
	resp = dispatch(req)
	if resp.OK || resp.Error == nil || resp.Error.Code != protocol.CodeUnsupported {
		t.Fatalf("unknown op must be unsupported: %+v", resp)
	}
}
