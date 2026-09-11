package grant

import (
	"encoding/json"
	"fmt"
	"reflect"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/admission"
)

func resourceEditFixture() ResourceEdit {
	return ResourceEdit{Tools: []string{"read_file", "exec"}, Network: []NetworkPatch{{Endpoint: "API.EXAMPLE.TEST.:0443", Effect: "allow"}, {Endpoint: "private.example.test:443", Effect: "deny"}}, Filesystem: FilesystemPatch{ReadOnly: []string{"/work/reports with spaces,commas"}, ReadWrite: []string{"/work/output"}}, Models: []string{"local/model"}}
}

func TestResourceEditPreservesRestrictionsAndSignedIdentity(t *testing.T) {
	for _, platform := range []string{"hermes", "openclaw"} {
		t.Run(platform, func(t *testing.T) {
			g := build(t, platform, sampleAdmission()).Grant
			deadline := "2099-01-01T00:00:00Z"
			g.ExpiresAt = &deadline
			for _, domain := range []string{"filesystem", "tool", "model"} {
				value := map[string]string{"filesystem": "/work/private", "tool": "exec", "model": "local/model"}[domain]
				g.Facts = append(g.Facts, Fact{FactID: "deny-" + domain, Domain: domain, Action: domain + ".deny", Resource: admission.Resource{Type: domain, Value: value}, Effect: "deny", State: "declared", Authority: "human"})
			}
			for i := range g.Facts {
				if g.Facts[i].Domain == "tool" && g.Facts[i].Resource.Value == "read_file" {
					g.Facts[i].Conditions = map[string]any{"require_approval": true}
				}
			}
			before, _ := json.Marshal(g)
			out, policy, err := EditResources(g, resourceEditFixture(), key(t))
			if err != nil {
				t.Fatal(err)
			}
			after, _ := json.Marshal(g)
			if string(before) != string(after) {
				t.Fatal("input grant mutated")
			}
			if out.GrantID != g.GrantID || out.Subject != g.Subject || out.AdmissionID != g.AdmissionID || out.Platform != g.Platform || out.Status != "pending_approval" || *out.ExpiresAt != deadline || out.EffectiveReadback != nil || !Verify(key(t).Public(), out) {
				t.Fatal("identity, lifetime, state or signature changed incorrectly")
			}
			if out.DesiredPolicyRef.Version != g.DesiredPolicyRef.Version+1 {
				t.Fatal("policy version not advanced")
			}
			for _, old := range g.Facts {
				if old.Effect == "deny" || old.Domain == "credential" || old.Domain == "process" || old.Domain == "resource" {
					found := false
					for _, f := range out.Facts {
						if reflect.DeepEqual(f, old) {
							found = true
						}
					}
					if !found {
						t.Fatalf("lost restriction %s", old.FactID)
					}
				}
			}
			approval, normalized := false, false
			for _, f := range out.Facts {
				if f.Domain == "tool" && f.Resource.Value == "read_file" {
					approval = f.Conditions["require_approval"] == true
				}
				if f.Domain == "network" && f.Resource.Value == "api.example.test:443" {
					normalized = true
				}
			}
			if !approval || !normalized {
				t.Fatal("approval condition or canonical network lost")
			}
			if !reflect.DeepEqual(policy["tools"], []any{"read_file"}) || policy["model_routing"] != nil {
				t.Fatal("denied tool/model emitted as allowed", policy)
			}
			fs := policy["filesystem"].(map[string]any)
			if !reflect.DeepEqual(fs["read_only"], []any{"/work/reports with spaces,commas"}) || !reflect.DeepEqual(fs["read_write"], []any{"/work/output"}) {
				t.Fatal("denied directory emitted as allowed", fs)
			}
			if platform == "openclaw" && (!reflect.DeepEqual(out.OpenClawToolPolicy.Deny, []string{"exec"}) || len(out.OpenClawToolPolicy.RequireApproval) != 0) {
				t.Fatal("denied exec reintroduced as approval gate")
			}
			if platform == "hermes" && !reflect.DeepEqual(*out.HermesToolsetAllowlist, []string{"read_file"}) {
				t.Fatal("denied tool in host list")
			}
		})
	}
}

func TestResourceEditEmptyListsAndChallenge(t *testing.T) {
	g := build(t, "hermes", sampleAdmission()).Grant
	ch, err := IssueChallenge(g, 1, fixedNow)
	if err != nil {
		t.Fatal(err)
	}
	empty := ResourceEdit{Tools: []string{}, Network: []NetworkPatch{}, Filesystem: FilesystemPatch{ReadOnly: []string{}, ReadWrite: []string{}}, Models: []string{}}
	out, policy, err := EditResources(g, empty, key(t))
	if err != nil {
		t.Fatal(err)
	}
	for _, f := range out.Facts {
		if f.Effect == "allow" && (f.Domain == "tool" || f.Domain == "filesystem" || f.Domain == "network" || f.Domain == "model") {
			t.Fatal("empty list kept old allow")
		}
	}
	for _, name := range []string{"tools", "filesystem", "network", "model_routing"} {
		if policy[name] != nil {
			t.Fatal("empty list retained policy", name)
		}
	}
	if ValidateChallenge(*ch, out, 1, ch.Nonce, fixedNow) != ErrChallengeMismatch {
		t.Fatal("old challenge survived edit")
	}
	for _, status := range []string{"approved", "deployed", "effective", "revoked", "rejected"} {
		g.Status = status
		if _, _, err := EditResources(g, empty, key(t)); err == nil {
			t.Fatal("edited non-pending grant", status)
		}
	}
}

func TestResourceEditPreservesLegacyPlatformOnlyRestrictions(t *testing.T) {
	g := build(t, "openclaw", sampleAdmission()).Grant
	g.OpenClawToolPolicy = &OpenClawToolPolicy{Allow: []string{"read_file", "exec"}, Deny: []string{"exec"}, RequireApproval: []string{"read_file", "exec"}}
	for _, deny := range []string{"exec", "*"} {
		g.OpenClawToolPolicy.Deny = []string{deny}
		out, policy, err := EditResources(g, resourceEditFixture(), key(t))
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(out.OpenClawToolPolicy.Deny, []string{deny}) {
			t.Fatal("lost platform-only deny")
		}
		for _, tool := range out.OpenClawToolPolicy.Allow {
			if tool == "exec" || deny == "*" {
				t.Fatal("platform deny expanded")
			}
		}
		approval := false
		for _, f := range out.Facts {
			if f.Domain == "tool" && f.Resource.Value == "read_file" {
				approval = f.Conditions["require_approval"] == true
			}
		}
		if !approval {
			t.Fatal("lost platform-only approval condition")
		}
		if deny == "*" && policy["tools"] != nil {
			t.Fatal("wildcard deny emitted allows")
		}
	}
}

func TestResourceEditValidationAndLimits(t *testing.T) {
	g := build(t, "hermes", sampleAdmission()).Grant
	for name, mutate := range map[string]func(*ResourceEdit){
		"nil tools": func(e *ResourceEdit) { e.Tools = nil }, "nil network": func(e *ResourceEdit) { e.Network = nil }, "nil models": func(e *ResourceEdit) { e.Models = nil }, "nil readonly": func(e *ResourceEdit) { e.Filesystem.ReadOnly = nil }, "nil readwrite": func(e *ResourceEdit) { e.Filesystem.ReadWrite = nil },
		"duplicate": func(e *ResourceEdit) { e.Tools = []string{"read_file", "read_file"} }, "wildcard tool": func(e *ResourceEdit) { e.Tools = []string{"*"} }, "long tool": func(e *ResourceEdit) { e.Tools = []string{strings.Repeat("a", 129)} },
		"relative": func(e *ResourceEdit) { e.Filesystem.ReadOnly = []string{"work"} }, "traversal": func(e *ResourceEdit) { e.Filesystem.ReadOnly = []string{"/work/../private"} }, "control": func(e *ResourceEdit) { e.Filesystem.ReadOnly = []string{"/work/\tprivate"} }, "windows": func(e *ResourceEdit) { e.Filesystem.ReadOnly = []string{`C:\work`} },
		"bare host": func(e *ResourceEdit) { e.Network[0].Endpoint = "example.test" }, "url": func(e *ResourceEdit) { e.Network[0].Endpoint = "https://example.test:443/path" }, "zero port": func(e *ResourceEdit) { e.Network[0].Endpoint = "example.test:0" }, "high port": func(e *ResourceEdit) { e.Network[0].Endpoint = "example.test:65536" }, "effect": func(e *ResourceEdit) { e.Network[0].Effect = "ask" },
		"canonical duplicate": func(e *ResourceEdit) {
			e.Network = append(e.Network, NetworkPatch{Endpoint: "api.example.test:443", Effect: "allow"})
		},
	} {
		t.Run(name, func(t *testing.T) {
			e := resourceEditFixture()
			mutate(&e)
			if _, _, err := EditResources(g, e, key(t)); err != ErrResourcesInvalid {
				t.Fatal(err)
			}
		})
	}
	for _, domain := range []string{"tools", "models", "readonly", "readwrite", "network"} {
		for _, count := range []int{32, 33} {
			e := resourceEditFixture()
			values := []string{}
			for i := 0; i < count; i++ {
				values = append(values, fmt.Sprintf("item%d", i))
			}
			switch domain {
			case "tools":
				e.Tools = values
			case "models":
				e.Models = values
			case "readonly", "readwrite":
				for i := range values {
					values[i] = "/work/" + values[i]
				}
				if domain == "readonly" {
					e.Filesystem.ReadOnly = values
				} else {
					e.Filesystem.ReadWrite = values
				}
			case "network":
				e.Network = []NetworkPatch{}
				for _, value := range values {
					e.Network = append(e.Network, NetworkPatch{Endpoint: value + ".test:443", Effect: "allow"})
				}
			}
			_, _, err := EditResources(g, e, key(t))
			if (err == nil) != (count == 32) {
				t.Fatal(domain, count, err)
			}
		}
	}
}
