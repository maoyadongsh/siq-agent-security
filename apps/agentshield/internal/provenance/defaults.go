package provenance

import "siq-agent-security/apps/agentshield/internal/runtimeaction"

// ConstraintsForAction fills uncovered high-impact paths without mutating the
// signed intent. Only an explicit constraint may relax the trusted default.
func ConstraintsForAction(explicit []Constraint, descriptor runtimeaction.Descriptor) []Constraint {
	out := append([]Constraint{}, explicit...)
	seen := map[string]bool{}
	for _, c := range explicit {
		seen[c.ParameterPath] = true
	}
	for _, path := range descriptor.HighImpactParameterPaths {
		if seen[path] {
			continue
		}
		seen[path] = true
		out = append(out, Constraint{ParameterPath: path, AllowedSourceTypes: []string{"USER", "SYSTEM", "TRUSTED_IAM", "TRUSTED_DATABASE"}, MinimumTrust: "trusted", Required: true})
	}
	return out
}
