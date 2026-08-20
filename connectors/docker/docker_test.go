package main

// P1-9 Docker 发现分类测试：
// 标签只是高置信提示而非发现前置条件；未打标签的智能体容器（影子智能体）
// 必须经启发式信号进入候选；无信号容器不产生候选噪音。

import (
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

func TestClassifyContainerLabel(t *testing.T) {
	cls := classifyContainer(containerRow{
		Names:  "my-service",
		Image:  "registry.internal/svc:1.0",
		Labels: "team=core,siq.agent=true",
	})
	if !cls.candidate || cls.basis != "label" || cls.confidence != 1.0 {
		t.Fatalf("labeled container must be high-confidence candidate: %+v", cls)
	}
	if cls.framework != "unknown" {
		t.Fatalf("no framework signal expected, got %q", cls.framework)
	}
}

func TestClassifyContainerShadowAgentByImage(t *testing.T) {
	// 未打标签的 dify 容器必须被发现（P1-9 影子智能体漏报修复）
	cls := classifyContainer(containerRow{
		Names:   "dify-api-1",
		Image:   "langgenius/dify-api:0.6",
		Command: "python app.py",
	})
	if !cls.candidate || cls.basis != "heuristic" || cls.framework != "dify" {
		t.Fatalf("unlabeled dify container must be heuristic candidate: %+v", cls)
	}
	if cls.confidence >= 1.0 {
		t.Fatalf("heuristic confidence must be below label confidence: %+v", cls)
	}
}

func TestClassifyContainerGenericSignal(t *testing.T) {
	cls := classifyContainer(containerRow{
		Names:   "ollama",
		Image:   "ollama/ollama:latest",
		Command: "/bin/ollama serve",
	})
	if !cls.candidate || cls.basis != "heuristic" || cls.framework != "unknown" {
		t.Fatalf("generic agent signal must yield unknown-framework candidate: %+v", cls)
	}
}

func TestClassifyContainerNoSignalSkipped(t *testing.T) {
	for _, row := range []containerRow{
		{Names: "nginx", Image: "nginx:1.27", Command: "nginx -g daemon off;"},
		{Names: "postgres", Image: "postgres:16", Command: "postgres"},
		{Names: "redis", Image: "redis:7", Command: "redis-server"},
	} {
		if cls := classifyContainer(row); cls.candidate {
			t.Fatalf("non-agent container %s must not become candidate: %+v", row.Names, cls)
		}
	}
}

func TestClassifyContainerLabelOverridesFramework(t *testing.T) {
	// 标签 + 框架信号：标签给置信度，框架由内容信号决定
	cls := classifyContainer(containerRow{
		Names:  "hermes-hub",
		Image:  "siq/hermes:2.0",
		Labels: "siq.agent=true",
	})
	if !cls.candidate || cls.basis != "label" || cls.framework != "hermes" {
		t.Fatalf("labeled hermes container: %+v", cls)
	}
}

func TestBuildObjectsCarriesClassification(t *testing.T) {
	row := containerRow{ID: "abcdef1234567890", Names: "dify-api-1", Image: "langgenius/dify-api:0.6"}
	insp := &dockerInspect{}
	insp.Config.Image = "langgenius/dify-api:0.6"
	insp.Image = "sha256:deadbeef"
	cls := classifyContainer(row)

	red := protocol.NewRedactor()
	cand, ev := buildObjects(row, insp, cls, "2026-08-20T00:00:00Z", red)
	if cand.Framework != "dify" || cand.Confidence != cls.confidence {
		t.Fatalf("candidate must carry classification: %+v", cand)
	}
	if cand.Attributes["discovery_basis"] != "heuristic" {
		t.Fatalf("discovery_basis attribute missing: %v", cand.Attributes)
	}
	if ev.SubjectRef == nil || *ev.SubjectRef != cand.CandidateID {
		t.Fatal("evidence must reference candidate")
	}
}
