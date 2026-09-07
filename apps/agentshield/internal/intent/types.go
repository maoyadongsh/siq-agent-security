package intent

import (
	"bytes"
	"encoding/json"
	"io"
	"time"
)

type Principal struct {
	Type string `json:"type"`
	ID   string `json:"id"`
}
type Agent struct {
	ID       string `json:"id"`
	Platform string `json:"platform"`
}
type Authority struct {
	Issuer      string   `json:"issuer"`
	Revision    string   `json:"revision"`
	EvidenceIDs []string `json:"evidence_ids"`
}
type ResourceConstraint struct {
	Domain   string `json:"domain"`
	Operator string `json:"operator"`
	Value    any    `json:"value"`
}
type ParameterConstraint struct {
	Path     string `json:"path"`
	Operator string `json:"operator"`
	Value    any    `json:"value"`
	Values   []any  `json:"values,omitempty"`
}

// Contract is the signed intent/v2 wire contract. V1 remains a separate schema.
type Contract struct {
	ProvenanceRefs       []string              `json:"provenance_refs,omitempty"`
	SchemaVersion        string                `json:"schema_version"`
	IntentID             string                `json:"intent_id"`
	TaskID               string                `json:"task_id"`
	Principal            Principal             `json:"principal"`
	Agent                Agent                 `json:"agent"`
	Purpose              string                `json:"purpose"`
	AllowedTools         []string              `json:"allowed_tools"`
	AllowedEffects       []string              `json:"allowed_effects"`
	ResourceConstraints  []ResourceConstraint  `json:"resource_constraints"`
	ParameterConstraints []ParameterConstraint `json:"parameter_constraints"`
	IssuedAt             string                `json:"issued_at"`
	ValidFrom            string                `json:"valid_from"`
	ExpiresAt            string                `json:"expires_at"`
	Authority            Authority             `json:"authority"`
	SigningSchema        string                `json:"signing_schema"`
	Digest               string                `json:"digest"`
	Signature            string                `json:"signature"`
}

func (c Contract) Expired(now time.Time) bool {
	t, err := time.Parse(time.RFC3339, c.ExpiresAt)
	return err != nil || !now.Before(t)
}

// Violation carries a stable public code without parameter or contract contents.
type Violation struct{ Code string }

func (v *Violation) Error() string { return v.Code }
func violation(code string) error  { return &Violation{Code: code} }

// Reject omitted required values at the wire boundary; explicit JSON null is an equality value.
func (p *ParameterConstraint) UnmarshalJSON(raw []byte) error {
	type wire ParameterConstraint
	var value wire
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	dec.UseNumber()
	if err := dec.Decode(&value); err != nil {
		return violation("intent_invalid_constraint")
	}
	var extra any
	if dec.Decode(&extra) != io.EOF {
		return violation("intent_invalid_constraint")
	}
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil {
		return violation("intent_invalid_constraint")
	}
	if _, ok := fields["path"]; !ok {
		return violation("intent_invalid_parameter_pointer")
	}
	if value.Operator != "one_of" {
		if _, ok := fields["value"]; !ok {
			return violation("intent_invalid_constraint")
		}
	}
	*p = ParameterConstraint(value)
	return nil
}
