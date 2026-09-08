// Package completion models explicitly requested, deterministic effect checks.
package completion

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"regexp"
)

type Requirement struct {
	RequirementID       string `json:"requirement_id"`
	EffectType          string `json:"effect_type"`
	ResourceRef         string `json:"resource_ref"`
	ExpectedDigest      string `json:"expected_digest"`
	MinimumIndependence string `json:"minimum_independence"`
	MinimumCoverage     string `json:"minimum_coverage"`
}

var ErrRequirement = errors.New("completion_requirement_invalid")
var identifier = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`)
var resource = regexp.MustCompile(`^filesystem:sha256:[0-9a-f]{64}$`)
var digest = regexp.MustCompile(`^[0-9a-f]{64}$`)

func (r Requirement) Validate() error {
	if !identifier.MatchString(r.RequirementID) || r.EffectType != "file.write" || !resource.MatchString(r.ResourceRef) || !digest.MatchString(r.ExpectedDigest) || (r.MinimumIndependence != "host_independent" && r.MinimumIndependence != "external_independent") || (r.MinimumCoverage != "partial" && r.MinimumCoverage != "full") {
		return ErrRequirement
	}
	return nil
}
func (r *Requirement) UnmarshalJSON(raw []byte) error {
	type wire Requirement
	var out wire
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if d.Decode(&out) != nil {
		return ErrRequirement
	}
	var extra any
	if d.Decode(&extra) != io.EOF {
		return ErrRequirement
	}
	value := Requirement(out)
	if err := value.Validate(); err != nil {
		return err
	}
	*r = value
	return nil
}
