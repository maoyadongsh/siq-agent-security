package grant

import (
	"siq-agent-security/apps/agentshield/internal/admission"
	"testing"
)

func TestWorkBuddyToolGrantDoesNotExpandPresentationCapabilities(t *testing.T) {
	g := &Grant{Platform: "workbuddy", Facts: []Fact{
		{Domain: "tool", Action: "tool.invoke", State: "declared", Effect: "allow", Resource: admission.Resource{Value: "Read"}},
		{Domain: "filesystem", Action: "fs.read", State: "declared", Effect: "allow", Resource: admission.Resource{Value: "C:/input"}},
	}}
	allow, approval := RuntimeToolSets(g)
	if !allow["Read"] || len(allow) != 1 || len(approval) != 0 {
		t.Fatal("minimum grant changed")
	}
	for _, tool := range []string{"present_files", "Glob", "Grep"} {
		if allow[tool] || approval[tool] {
			t.Fatalf("implicit tool capability %s", tool)
		}
	}
	g.Facts = append(g.Facts, Fact{Domain: "tool", Action: "tool.invoke", State: "declared", Effect: "allow", Resource: admission.Resource{Value: "present_files"}}, Fact{Domain: "tool", Action: "tool.invoke", State: "declared", Effect: "deny", Resource: admission.Resource{Value: "present_files"}})
	allow, approval = RuntimeToolSets(g)
	if allow["present_files"] || approval["present_files"] {
		t.Fatal("explicit deny bypassed")
	}
}
