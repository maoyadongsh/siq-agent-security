package grant

import (
	"slices"
	"testing"

	"siq-agent-security/apps/agentshield/internal/admission"
)

func TestPatchDesiredPreservesExecApproval(t *testing.T) {
	declarations := []admission.DeclaredFact{
		fact("process", "process.exec", "tool", "shell"),
		fact("resource", "package.install", "package", "pip"),
		fact("credential", "credential.read", "credential_ref", ".env"),
	}
	patches := map[string]DesiredPatch{
		"network":    {HasNetwork: true, Network: []NetworkPatch{{Endpoint: "api.example.test:443", Effect: "allow"}}},
		"tools":      {HasTools: true, Tools: []string{"exec", "read_file"}},
		"models":     {HasModels: true, Models: []string{"fixture-model"}},
		"filesystem": {HasFilesystem: true, Filesystem: &FilesystemPatch{ReadOnly: []string{"/fixture"}}},
	}
	for _, declaration := range declarations {
		for name, patch := range patches {
			t.Run(declaration.Domain+"/"+name, func(t *testing.T) {
				adm := sampleAdmission()
				adm.DeclaredFacts = []admission.DeclaredFact{fact("tool", "tool.invoke", "tool", "exec"), declaration}
				original := build(t, "openclaw", adm).Grant
				if !slices.Contains(original.OpenClawToolPolicy.RequireApproval, "exec") {
					t.Fatal("fixture did not require approval before patch")
				}
				patched, _, err := PatchDesired(original, patch, key(t))
				if err != nil {
					t.Fatal(err)
				}
				if !slices.Contains(patched.OpenClawToolPolicy.RequireApproval, "exec") {
					t.Fatal("patch removed per-use exec approval while its source fact remains")
				}
				if !slices.Contains(patched.OpenClawToolPolicy.Allow, "exec") {
					t.Fatal("fixture must exercise approval precedence over explicit tool allow")
				}
				if patched.Status != "pending_approval" {
					t.Fatal("patch bypassed grant approval")
				}
				if declaration.Domain == "credential" {
					found := false
					for _, f := range patched.Facts {
						found = found || (f.Domain == "credential" && f.Effect == "deny")
					}
					if !found {
						t.Fatal("patch removed credential denial")
					}
				}
			})
		}
	}
}

func TestPatchDesiredDoesNotInventExecApproval(t *testing.T) {
	adm := sampleAdmission()
	adm.DeclaredFacts = []admission.DeclaredFact{fact("tool", "tool.invoke", "tool", "exec")}
	original := build(t, "openclaw", adm).Grant
	patched, _, err := PatchDesired(original, DesiredPatch{HasModels: true, Models: []string{"fixture"}}, key(t))
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Contains(patched.OpenClawToolPolicy.Allow, "exec") || len(patched.OpenClawToolPolicy.RequireApproval) != 0 {
		t.Fatal("patch introduced an approval gate without a source fact")
	}
}
