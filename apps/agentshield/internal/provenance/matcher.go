package provenance

import (
	"errors"
	"time"
)

// MatchParameters verifies every supplied binding before applying constraints.
// The read lock gives this decision one registry snapshot, including revocations.
func (s *Store) MatchParameters(params map[string]any, bindings []ParameterBinding, constraints []Constraint, scope Scope, now time.Time) error {
	storeMu.RLock()
	defer storeMu.RUnlock()
	if !scope.valid() {
		return failure("provenance_scope_mismatch")
	}
	if len(bindings) > MaxNodes || len(constraints) > MaxNodes {
		return failure("provenance_capacity")
	}
	resolved := map[string][]Assertion{}
	walk := newWalk()
	for _, binding := range bindings {
		if _, exists := resolved[binding.ParameterPath]; exists {
			return failure("provenance_authority_invalid")
		}
		value, ok := PointerValue(params, binding.ParameterPath)
		if !ok {
			return failure("provenance_missing")
		}
		if len(binding.ProvenanceRefs) == 0 || len(binding.ProvenanceRefs) > 32 {
			return failure("provenance_authority_invalid")
		}
		digest, err := ContentDigest(value)
		if err != nil {
			return err
		}
		seen := map[string]bool{}
		nodes := []Assertion{}
		for _, ref := range binding.ProvenanceRefs {
			if seen[ref] {
				return failure("provenance_authority_invalid")
			}
			seen[ref] = true
			a, err := s.loadAssertion(ref, scope)
			if err != nil {
				var violation *Violation
				if errors.As(err, &violation) && violation.Code == "provenance_not_found" {
					// Do not probe other scopes to distinguish replay from an
					// unknown ID: neither reference is bound to this request.
					return failure("provenance_scope_mismatch")
				}
				return err
			}
			node, err := s.resolveNode(a, scope, now, 1, walk)
			if err != nil {
				return err
			}
			if node.assertion.ContentDigest != digest {
				return failure("provenance_content_mismatch")
			}
			nodes = append(nodes, node.assertion)
		}
		resolved[binding.ParameterPath] = nodes
	}
	seen := map[string]bool{}
	for _, c := range constraints {
		if err := c.Validate(); err != nil {
			return err
		}
		if seen[c.ParameterPath] {
			return failure("provenance_constraint_invalid")
		}
		seen[c.ParameterPath] = true
		_, present := PointerValue(params, c.ParameterPath)
		nodes := resolved[c.ParameterPath]
		if !present || len(nodes) == 0 {
			if c.Required {
				return failure("provenance_missing")
			}
			continue
		}
		for _, node := range nodes {
			if node.Derivation == "unknown" {
				return failure("provenance_derivation_unknown")
			}
			allowed := false
			for _, source := range c.AllowedSourceTypes {
				if node.Source.Type == source {
					allowed = true
				}
			}
			if !allowed {
				return failure("provenance_source_not_allowed")
			}
			if trustRanks[node.Source.Trust] < trustRanks[c.MinimumTrust] {
				return failure("provenance_trust_insufficient")
			}
		}
	}
	return nil
}
