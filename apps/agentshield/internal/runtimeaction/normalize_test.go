package runtimeaction

import (
	"strings"
	"testing"
)

func TestNormalizeSeparatesToolOperationAndEffect(t *testing.T) {
	op, effects := Normalize("Bash", map[string]any{"command": "curl https://example.com"})
	if op != "exec" || len(effects) != 3 || effects[0] != EffectProcessExec || effects[1] != EffectNetworkRequest || effects[2] != EffectUnknown {
		t.Fatalf("got operation=%q effects=%v", op, effects)
	}
	op, effects = Normalize("send_message", nil)
	if op != "send" || effects[0] != EffectMessageSend {
		t.Fatalf("got operation=%q effects=%v", op, effects)
	}
}

func TestNormalizeUnknownIsExplicit(t *testing.T) {
	op, effects := Normalize("future_tool", nil)
	if op != "invoke" || len(effects) != 1 || effects[0] != EffectUnknown {
		t.Fatalf("got operation=%q effects=%v", op, effects)
	}
}

func TestActionIDIsStableForSameEnvelope(t *testing.T) {
	a := Envelope{Platform: "hermes", SessionID: "s-1", AgentID: "a-1", TaskID: "t-1", IntentID: "i-1", Tool: "read_file", ToolCallID: "tc-1", Operation: "read", Effects: []string{EffectFileRead}, ParamsDigest: strings.Repeat("a", 64)}
	b := a
	b.OccurredAt = a.OccurredAt.Add(10)
	if gotA, gotB := ActionID(a), ActionID(b); gotA != gotB {
		t.Fatalf("action ids drifted: %q vs %q", gotA, gotB)
	}
}

func TestActionIDDifferentiatesEverySecurityField(t *testing.T) {
	base := Envelope{Platform: "hermes", SessionID: "s1", AgentID: "a1", TaskID: "t1", IntentID: "i1", Tool: "read_file", ToolCallID: "call1", Operation: "read", Effects: []string{"file.read"}, ParamsDigest: strings.Repeat("a", 64)}
	edits := []func(*Envelope){
		func(e *Envelope) { e.Platform = "openclaw" }, func(e *Envelope) { e.SessionID = "s2" }, func(e *Envelope) { e.AgentID = "a2" }, func(e *Envelope) { e.TaskID = "t2" }, func(e *Envelope) { e.IntentID = "i2" }, func(e *Envelope) { e.Tool = "write_file" }, func(e *Envelope) { e.ToolCallID = "call2" }, func(e *Envelope) { e.Operation = "write" }, func(e *Envelope) { e.Effects = []string{"file.write"} }, func(e *Envelope) { e.ParamsDigest = strings.Repeat("b", 64) },
	}
	for i, edit := range edits {
		changed := base
		edit(&changed)
		if ActionID(changed) == ActionID(base) {
			t.Fatalf("field %d collapsed to the same identity", i)
		}
	}
}
