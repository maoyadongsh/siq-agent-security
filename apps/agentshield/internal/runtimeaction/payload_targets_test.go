package runtimeaction

import (
	"reflect"
	"testing"
)

func TestStructuredPayloadDoesNotInventTargets(t *testing.T) {
	content := "Review /workspace and /etc/passwd; see https://docs.example.test for curl examples."
	file := Describe("write_file", map[string]any{"path": "/work/my report.md", "content": content})
	if !reflect.DeepEqual(file.Paths, []string{"/work/my report.md"}) || len(file.Hosts) != 0 || file.Egress {
		t.Fatal("payload manufactured resources", file)
	}
	network := Describe("web_fetch", map[string]any{"url": "https://api.example.test/task", "json": map[string]any{"body": content}})
	if !reflect.DeepEqual(network.Hosts, []string{"api.example.test:443"}) || !network.Egress {
		t.Fatal("payload manufactured network destinations", network)
	}
	message := Describe("send_message", map[string]any{"recipient": "user", "body": content})
	if len(message.Hosts) != 0 || !message.Egress {
		t.Fatal("message lost egress or invented host", message)
	}
}

func TestExplicitAdditionalTargetsAndInterpreterHintsRemain(t *testing.T) {
	file := Describe("write_file", map[string]any{"path": "/work/report", "file_path": "/outside/second"})
	if !reflect.DeepEqual(file.Paths, []string{"/outside/second", "/work/report"}) {
		t.Fatal("second structured path omitted", file)
	}
	shell := Describe("exec", map[string]any{"command": "curl https://outside.example.test > /outside/file"})
	if len(shell.Hosts) != 1 || len(shell.Paths) != 1 || !hasEffect(shell.Effects, EffectUnknown) {
		t.Fatal("shell command lost conservative hints", shell)
	}
}
