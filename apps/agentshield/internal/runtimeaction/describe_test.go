package runtimeaction

import (
	"reflect"
	"testing"
)

func TestDescriptorInterpreterAliasesRemainUnknown(t *testing.T) {
	for _, tool := range []string{"exec", "terminal", "Bash", "sh", "python", "python3", "node", "powershell", "pwsh"} {
		for _, params := range []map[string]any{{"command": "printf fixture"}, {"input": map[string]any{"command": "curl https://example.test"}}} {
			d := Describe(tool, params)
			if !d.ShellLike || !d.Mutating || !hasEffect(d.Effects, EffectProcessExec) || !hasEffect(d.Effects, EffectUnknown) {
				t.Fatal("interpreter gained complete effect claim", tool, d)
			}
			if len(d.Resources) != 0 {
				t.Fatal("shell text manufactured resource authority", d)
			}
			if _, exists := params["input"]; exists && (!d.Egress || len(d.Hosts) != 1 || !hasEffect(d.Effects, EffectNetworkRequest)) {
				t.Fatal("nested egress escaped descriptor", tool, d)
			}
		}
	}
}

func TestDescriptorHighImpactPointersAndCompatibility(t *testing.T) {
	params := map[string]any{"a/b": []any{map[string]any{"recipient": "user@example.test", "credential_ref": "vault-ref"}}, "repo": "org/repo", "branch": "main", "ordinary": "text", "path": "/work/report"}
	d := Describe("write_file", params)
	want := []string{"/a~1b/0/credential_ref", "/a~1b/0/recipient", "/branch", "/path", "/repo"}
	if !reflect.DeepEqual(d.HighImpactParameterPaths, want) {
		t.Fatal(d.HighImpactParameterPaths)
	}
	if !d.Mutating || !d.FilesystemWriteHint || d.ShellLike || d.Egress || d.ResourceError != nil || len(d.Resources) != 1 {
		t.Fatal(d)
	}
	op, effects := Normalize("write_file", params)
	resources, err := ExtractResources("write_file", params)
	if op != d.Operation || !reflect.DeepEqual(effects, d.Effects) || err != d.ResourceError || !reflect.DeepEqual(resources, d.Resources) {
		t.Fatal("legacy helpers diverged")
	}
	bad := Describe("write_file", map[string]any{"path": "/work/report", "file_path": false})
	if bad.ResourceError == nil || len(bad.Resources) != 0 {
		t.Fatal("invalid parameter produced partial authority", bad)
	}
}

func TestDescriptorFileAliasesShareWriteChecks(t *testing.T) {
	for _, tool := range []string{"write_file", "write", "Write", "edit", "Edit", "patch", "delete_file", "remove"} {
		d := Describe(tool, map[string]any{"path": "/secret/report"})
		if !d.Mutating || !d.FilesystemWriteHint || len(d.Paths) != 1 || len(d.Resources) != 1 {
			t.Fatal("file alias bypassed write checks", tool, d)
		}
	}
	d := Describe("unknown_connector", map[string]any{"identity": "principal", "destination_host": "example.test", "deployment_target": "production", "database_scope": "tenant-a", "account": "a"})
	if len(d.HighImpactParameterPaths) != 5 || !hasEffect(d.Effects, EffectUnknown) {
		t.Fatal("unknown connector lost high-impact parameters", d)
	}
}
