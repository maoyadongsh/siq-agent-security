package grant

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"sort"

	"siq-agent-security/apps/agentshield/internal/canon"
)

// CapabilityItem mirrors contracts.CapabilityItem on the Python side.
type CapabilityItem struct {
	Status    string // supported | unsupported | unknown
	Semantics string
	Basis     string
}

// Capabilities mirrors contracts.BackendCapabilities (the subset the compiler
// reads). Items not reported are unknown → fail-closed.
type Capabilities struct {
	Backend                     string
	SchemaVersion               string
	DynamicNetworkUpdate        bool
	ProviderCredentialInjection bool
	Items                       map[string]CapabilityItem
}

// Capability mirrors BackendCapabilities.capability(): unreported → unknown.
func (c Capabilities) Capability(name string) CapabilityItem {
	if it, ok := c.Items[name]; ok {
		return it
	}
	return CapabilityItem{Status: "unknown", Semantics: "none", Basis: "probe 能力文档未报告该能力项"}
}

// Compiled mirrors contracts.CompiledPolicy.
type Compiled struct {
	PolicyID        string
	Version         int
	Backend         string
	SchemaVersion   string
	Artifact        map[string]any
	ArtifactHash    string
	Unsupported     []string
	NeedsGeneration bool
	EnforcementMode string
}

var knownKeys = map[string]bool{
	"policy_id": true, "selector": true, "filesystem": true, "network": true, "process": true, "model_routing": true,
	"tools": true, "tool_policies": true, "data_scope_refs": true, "secrets": true, "resources": true, "audit": true,
	"exceptions": true, "enforcement_mode": true, "version": true, "status": true,
}

// fieldCapability mirrors _FIELD_CAPABILITY (order matters for the unsupported list).
var fieldCapability = []struct{ key, cap string }{
	{"tools", "tools_mcp"}, {"tool_policies", "tools_mcp"}, {"data_scope_refs", ""}, {"resources", "resources"},
	{"audit", "audit_events"}, {"exceptions", ""},
}

// ErrUnsupported mirrors UnsupportedCapability (unknown keys refuse to compile).
type ErrUnsupported struct{ msg string }

func (e *ErrUnsupported) Error() string { return e.msg }

// CompilePolicy is the Go port of policy_compiler.compile_policy. The
// artifact and therefore artifact_hash must be identical to the Python
// output for the same desired policy and capabilities (parity test).
func CompilePolicy(desired map[string]any, caps Capabilities) (*Compiled, error) {
	var unknown []string
	for k := range desired {
		if !knownKeys[k] {
			unknown = append(unknown, k)
		}
	}
	if len(unknown) > 0 {
		sort.Strings(unknown)
		return nil, &ErrUnsupported{fmt.Sprintf("未知策略字段（拒绝编译）: %v", unknown)}
	}
	artifact := map[string]any{"version": 1}
	var unsupported []string
	needsGen := false

	if fs, ok := desired["filesystem"].(map[string]any); ok && len(fs) > 0 {
		artifact["filesystem_policy"] = map[string]any{
			"read_only":  listOrEmpty(fs["read_only"]),
			"read_write": listOrEmpty(fs["read_write"]),
		}
		needsGen = true
	}
	if proc, ok := desired["process"].(map[string]any); ok && len(proc) > 0 {
		artifact["process"] = proc
		needsGen = true
	}
	if net, ok := desired["network"].([]any); ok && len(net) > 0 {
		if !caps.DynamicNetworkUpdate {
			unsupported = append(unsupported, "network.dynamic_update")
			needsGen = true
		}
		artifact["network_policies"] = net
	}
	if mr, ok := desired["model_routing"].(map[string]any); ok && len(mr) > 0 {
		item := caps.Capability("model_routing")
		switch {
		case caps.ProviderCredentialInjection && item.Status == "supported":
			artifact["inference_routing"] = mr
		case item.Status == "unknown":
			unsupported = append(unsupported, "model_routing.inference_routing: capability unknown（fail-closed）: "+item.Basis)
		default:
			unsupported = append(unsupported, "model_routing.inference_routing: capability unsupported: "+item.Basis)
		}
	}
	if sec, ok := desired["secrets"].([]any); ok && len(sec) > 0 {
		item := caps.Capability("secrets")
		if item.Status == "unknown" {
			unsupported = append(unsupported, "secrets.injection: capability unknown（fail-closed）: "+item.Basis)
		} else {
			basis := item.Basis
			if basis == "" {
				basis = "凭据注入由 Provider 侧承担（§15.2）"
			}
			unsupported = append(unsupported, "secrets.injection: capability "+item.Status+": "+basis)
		}
	}
	for _, fc := range fieldCapability {
		if truthy(desired[fc.key]) {
			unsupported = append(unsupported, capabilityReason(caps, fc.key, fc.cap))
		}
	}
	mode, _ := desired["enforcement_mode"].(string)
	if mode == "" {
		mode = "audit_only"
	}
	if item := caps.Capability("enforcement_mode." + mode); item.Status != "supported" {
		unsupported = append(unsupported, "enforcement_mode."+mode+": capability "+item.Status+": "+item.Basis)
	}

	raw, err := canon.Marshal(artifact)
	if err != nil {
		return nil, err
	}
	sum := sha256.Sum256(raw)
	pid, _ := desired["policy_id"].(string)
	version := 1
	if v, ok := desired["version"]; ok {
		if n, ok := toInt(v); ok && n > 0 {
			version = n
		}
	}
	if unsupported == nil {
		unsupported = []string{}
	}
	return &Compiled{
		PolicyID: pid, Version: version, Backend: caps.Backend, SchemaVersion: caps.SchemaVersion,
		Artifact: artifact, ArtifactHash: hex.EncodeToString(sum[:]), Unsupported: unsupported,
		NeedsGeneration: needsGen, EnforcementMode: mode,
	}, nil
}

func capabilityReason(caps Capabilities, key, capName string) string {
	if capName == "" {
		return key + ": 无对应后端能力项，由其他执行点承担"
	}
	item := caps.Capability(capName)
	switch item.Status {
	case "unknown":
		return key + ": capability " + capName + "=unknown（fail-closed 视为不可执行）: " + item.Basis
	case "unsupported":
		basis := item.Basis
		if basis == "" {
			basis = "由其他执行点承担"
		}
		return key + ": capability " + capName + "=unsupported: " + basis
	}
	return key + ": capability " + capName + "=supported/" + item.Semantics + "，本适配器不执行，由其他执行点承担"
}

func listOrEmpty(v any) []any {
	if l, ok := v.([]any); ok && l != nil {
		return l
	}
	return []any{}
}

func truthy(v any) bool {
	switch t := v.(type) {
	case nil:
		return false
	case []any:
		return len(t) > 0
	case map[string]any:
		return len(t) > 0
	case string:
		return t != ""
	case bool:
		return t
	}
	return true
}

func toInt(v any) (int, bool) {
	switch t := v.(type) {
	case int:
		return t, true
	case float64:
		return int(t), true
	case interface{ Int64() (int64, error) }:
		n, err := t.Int64()
		return int(n), err == nil
	}
	return 0, false
}
