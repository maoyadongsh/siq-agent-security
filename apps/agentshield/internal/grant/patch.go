package grant

import (
	"fmt"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/signing"
)

// NetworkPatch is one desired network endpoint.
type NetworkPatch struct {
	Endpoint string `json:"endpoint"`
	Effect   string `json:"effect"`
}

// FilesystemPatch is static fs allow lists.
type FilesystemPatch struct {
	ReadOnly  []string `json:"read_only"`
	ReadWrite []string `json:"read_write"`
}

// ProcessPatch is the static process domain.
type ProcessPatch struct {
	ForbidPrivilegeEscalation bool `json:"forbid_privilege_escalation"`
}

// DesiredPatch is POST /v1/grants/{id}/patch-desired (pending_approval only).
type DesiredPatch struct {
	HasTools      bool
	Tools         []string
	HasNetwork    bool
	Network       []NetworkPatch
	HasFilesystem bool
	Filesystem    *FilesystemPatch
	HasProcess    bool
	Process       *ProcessPatch
	HasModels     bool
	Models        []string
}

// PatchDesired rebuilds facts + allowlists + DesiredPolicy for a pending grant.
func PatchDesired(g Grant, patch DesiredPatch, key *signing.Key) (Grant, DesiredPolicy, error) {
	if g.Status != "pending_approval" {
		return g, nil, fmt.Errorf("grant: patch-desired only allowed in pending_approval (got %s)", g.Status)
	}
	if !patch.HasTools && !patch.HasNetwork && !patch.HasFilesystem && !patch.HasProcess && !patch.HasModels {
		return g, nil, fmt.Errorf("grant: patch-desired requires at least one domain")
	}

	var kept []Fact
	for _, f := range g.Facts {
		drop := false
		switch f.Domain {
		case "tool":
			drop = patch.HasTools && f.Effect == "allow"
		case "network":
			drop = patch.HasNetwork
		case "filesystem":
			drop = patch.HasFilesystem
		case "process":
			drop = patch.HasProcess
		case "model":
			drop = patch.HasModels
		}
		if !drop {
			kept = append(kept, f)
		}
	}

	n := len(kept)
	add := func(domain, action, rtype, value, effect, state, authority string) {
		n++
		kept = append(kept, Fact{
			FactID: fmt.Sprintf("pf-p-%d-%s", n, shortID(domain+action+value)),
			Domain: domain, Action: action, Resource: admission.Resource{Type: rtype, Value: value},
			Effect: effect, State: state, Authority: authority,
		})
	}
	if patch.HasTools {
		for _, t := range patch.Tools {
			if t == "" {
				continue
			}
			add("tool", "tool.invoke", "tool", t, "allow", "declared", "human")
		}
	}
	if patch.HasNetwork {
		for _, nr := range patch.Network {
			if nr.Endpoint == "" {
				continue
			}
			eff := nr.Effect
			if eff == "" {
				eff = "allow"
			}
			add("network", "http.request", "endpoint", nr.Endpoint, eff, "declared", "human")
		}
	}
	if patch.HasFilesystem && patch.Filesystem != nil {
		for _, p := range patch.Filesystem.ReadOnly {
			if p != "" {
				add("filesystem", "fs.read", "path", p, "allow", "declared", "human")
			}
		}
		for _, p := range patch.Filesystem.ReadWrite {
			if p != "" {
				add("filesystem", "fs.write", "path", p, "allow", "declared", "human")
			}
		}
	}
	if patch.HasProcess && patch.Process != nil && patch.Process.ForbidPrivilegeEscalation {
		add("process", "process.privilege_escalation", "capability", "setuid/sudo", "deny", "inferred", "agentshield")
	}
	if patch.HasModels {
		for _, m := range patch.Models {
			if m != "" {
				add("model", "model.generate", "model", m, "allow", "declared", "human")
			}
		}
	}

	kept, overlaps := resolveOverlaps(kept)
	g.Facts = kept
	g.OverlapConflicts = overlaps

	hermes := map[string]bool{}
	ocAllow, ocReq := map[string]bool{}, map[string]bool{}
	var netRules []any
	fsRO, fsRW := map[string]bool{}, map[string]bool{}
	var models []any
	var tools []any
	needsProcess := false
	for _, f := range g.Facts {
		switch f.Domain {
		case "tool":
			if f.Effect == "allow" {
				hermes[f.Resource.Value] = true
				ocAllow[f.Resource.Value] = true
				tools = append(tools, f.Resource.Value)
			}
		case "network":
			if f.Effect == "allow" {
				netRules = append(netRules, map[string]any{"endpoint": f.Resource.Value, "effect": "allow"})
			}
		case "filesystem":
			if f.Action == "fs.read" {
				fsRO[f.Resource.Value] = true
			} else {
				fsRW[f.Resource.Value] = true
			}
		case "process":
			needsProcess = true
		case "model":
			models = append(models, f.Resource.Value)
		}
	}

	ver := 1
	pid := "pol-" + g.GrantID
	if g.DesiredPolicyRef != nil {
		ver = g.DesiredPolicyRef.Version + 1
		if g.DesiredPolicyRef.PolicyID != "" {
			pid = g.DesiredPolicyRef.PolicyID
		}
	}
	dp := DesiredPolicy{
		"policy_id": pid, "selector": map[string]any{"agent_ids": []any{g.Subject.ID}},
		"version": ver, "status": "validated", "enforcement_mode": g.EnforcementMode,
	}
	if len(netRules) > 0 {
		dp["network"] = netRules
	}
	if len(fsRO) > 0 || len(fsRW) > 0 {
		dp["filesystem"] = map[string]any{"read_only": toAny(keysSorted(fsRO)), "read_write": toAny(keysSorted(fsRW))}
	}
	if needsProcess {
		dp["process"] = map[string]any{"forbid_privilege_escalation": true}
	}
	if len(models) > 0 {
		dp["model_routing"] = map[string]any{"allowed_models": models}
	}
	if len(tools) > 0 {
		dp["tools"] = tools
	}

	var static []string
	if _, ok := dp["filesystem"]; ok {
		static = append(static, "filesystem")
	}
	if _, ok := dp["process"]; ok {
		static = append(static, "process")
	}
	if static == nil {
		static = []string{}
	}
	g.DesiredPolicyRef = &DesiredPolicyRef{PolicyID: pid, Version: ver, StaticDomainsUnavailable: static}

	switch g.Platform {
	case "hermes":
		al := keysSorted(hermes)
		g.HermesToolsetAllowlist = &al
	case "openclaw":
		g.OpenClawToolPolicy = &OpenClawToolPolicy{Allow: keysSorted(ocAllow), Deny: []string{}, RequireApproval: keysSorted(ocReq)}
	}

	g.Signature = sign(key, g)
	return g, dp, nil
}
