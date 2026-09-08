// Package runtimeauthz separates authority validity from advisory policy modes.
// It does not resolve identities or grant permissions; the existing engine owns
// the transaction and consumes verified intent/context/provenance results.
package runtimeauthz

type AuthorityResult struct {
	Valid      bool
	Status     string
	ReasonCode string
}

type PolicyResult struct {
	Action     string
	ReasonCode string
	Reason     string
}

// Authority classifies known constraint violations as policy, never treating an
// unknown validation error as permission to execute in an advisory mode.
func Authority(code string, bound bool) AuthorityResult {
	status := "unbound_legacy"
	if bound {
		status = "valid"
	}
	switch code {
	case "", "intent_tool_not_allowed", "intent_effect_not_allowed", "intent_resource_not_allowed", "intent_parameter_violation", "runtime_effect_unknown":
		return AuthorityResult{Valid: true, Status: status}
	default:
		return AuthorityResult{Status: "invalid", ReasonCode: code}
	}
}

// ApplyMode runs only after authority validation. PolicyAction remains the raw
// policy result; the returned action is the only execution permission.
func ApplyMode(authority AuthorityResult, policy PolicyResult, mode string) (action string, advisory *string) {
	if !authority.Valid {
		return "deny", nil
	}
	if (mode == "warn" || mode == "audit_only") && policy.Action != "allow" {
		raw := policy.Action
		return "allow", &raw
	}
	return policy.Action, nil
}
