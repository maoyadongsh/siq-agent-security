package grant

// RuntimeToolSets returns executable tool candidates and approval requirements.
// Explicit denies win across platform lists and facts; resource checks remain required.
func RuntimeToolSets(g *Grant) (allow, requireApproval map[string]bool) {
	allow, requireApproval = map[string]bool{}, map[string]bool{}
	if g.HermesToolsetAllowlist != nil {
		for _, t := range *g.HermesToolsetAllowlist {
			allow[t] = true
		}
	}
	if g.OpenClawToolPolicy != nil {
		for _, t := range g.OpenClawToolPolicy.Allow {
			allow[t] = true
		}
		for _, t := range g.OpenClawToolPolicy.RequireApproval {
			requireApproval[t] = true
		}
		for _, t := range g.OpenClawToolPolicy.Deny {
			delete(allow, t)
		}
	}
	// facts are the ground truth for platforms without a list output
	for _, f := range g.Facts {
		if f.Domain == "tool" && f.Effect == "allow" && (f.State == "declared" || f.State == "effective") {
			allow[f.Resource.Value] = true
			if f.Conditions["require_approval"] == true {
				requireApproval[f.Resource.Value] = true
			}
		}
	}
	// A deny cannot be reintroduced as an allow by another fact or a rebuilt
	// platform list, and it cannot become a hold that later grants execution.
	denyTool := func(tool string) {
		if tool == "*" {
			clear(allow)
			clear(requireApproval)
			return
		}
		delete(allow, tool)
		delete(requireApproval, tool)
	}
	if g.OpenClawToolPolicy != nil {
		for _, t := range g.OpenClawToolPolicy.Deny {
			denyTool(t)
		}
	}
	for _, f := range g.Facts {
		if f.Domain == "tool" && f.Effect == "deny" {
			denyTool(f.Resource.Value)
		}
	}
	return allow, requireApproval
}
