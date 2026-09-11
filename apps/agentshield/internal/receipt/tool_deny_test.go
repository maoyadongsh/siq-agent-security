package receipt

import (
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
)

func TestToolDenyCannotBecomeAllowOrApprovalAcrossModes(t *testing.T) {
	for _, platform := range []string{"hermes", "openclaw"} {
		for _, mode := range []string{"block", "warn", "audit_only"} {
			for _, source := range []string{"fact", "platform"} {
				if source == "platform" && platform != "openclaw" {
					continue
				}
				for _, target := range []string{"read_file", "*"} {
					t.Run(platform+"/"+mode+"/"+source+"/"+target, func(t *testing.T) {
						g := deployedGrant(t, platform, false)
						allowed := scopedFact("allowed", "tool", "tool.invoke", "read_file", "allow")
						allowed.Conditions = map[string]any{"require_approval": true}
						g.Facts = append(g.Facts, allowed)
						if source == "fact" {
							g.Facts = append(g.Facts, scopedFact("denied", "tool", "tool.invoke", target, "deny"))
						} else {
							g.OpenClawToolPolicy = &grant.OpenClawToolPolicy{Allow: []string{"read_file"}, RequireApproval: []string{"read_file"}, Deny: []string{target}}
						}
						fx := newFixture(t, mode, g, false)
						d, err := fx.eng.Decide(req(platform, "read_file", map[string]any{"path": "/work/report"}))
						if err != nil {
							t.Fatal(err)
						}
						if mode == "block" {
							if d.Action != ActionDeny {
								t.Fatal("deny became executable or approvable", d.Action)
							}
						} else if d.Action != ActionAllow || d.Receipt.AdvisoryAction == nil || *d.Receipt.AdvisoryAction != ActionDeny {
							t.Fatal("policy mode lost deny advisory")
						}
						allow, approval := toolSets(g)
						if allow["read_file"] || approval["read_file"] {
							t.Fatal("denied tool remains in execution/hold sets")
						}
					})
				}
			}
		}
	}
}
