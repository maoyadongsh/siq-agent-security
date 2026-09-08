// Package completion models explicitly requested, deterministic effect checks.
package completion

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"regexp"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"strconv"
)

type Endpoint struct {
	Scheme string `json:"scheme"`
	Host   string `json:"host"`
	Port   string `json:"port"`
}

type Requirement struct {
	ExpectedEndpoint    *Endpoint `json:"expected_endpoint,omitempty"`
	RequirementID       string    `json:"requirement_id"`
	EffectType          string    `json:"effect_type"`
	ResourceRef         string    `json:"resource_ref"`
	ExpectedDigest      string    `json:"expected_digest"`
	MinimumIndependence string    `json:"minimum_independence"`
	MinimumCoverage     string    `json:"minimum_coverage"`
}

var ErrRequirement = errors.New("completion_requirement_invalid")
var identifier = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`)
var resource = regexp.MustCompile(`^filesystem:sha256:[0-9a-f]{64}$`)
var networkResource = regexp.MustCompile(`^network:sha256:[0-9a-f]{64}$`)
var digest = regexp.MustCompile(`^[0-9a-f]{64}$`)

func (r Requirement) Validate() error {
	if !identifier.MatchString(r.RequirementID) || !digest.MatchString(r.ExpectedDigest) || (r.MinimumIndependence != "host_independent" && r.MinimumIndependence != "external_independent") || (r.MinimumCoverage != "partial" && r.MinimumCoverage != "full") {
		return ErrRequirement
	}
	switch r.EffectType {
	case "file.write":
		if !resource.MatchString(r.ResourceRef) || r.ExpectedEndpoint != nil {
			return ErrRequirement
		}
	case "network.request":
		e := r.ExpectedEndpoint
		if e == nil || !networkResource.MatchString(r.ResourceRef) || r.MinimumIndependence != "external_independent" {
			return ErrRequirement
		}
		host, err := runtimeaction.NormalizeHost(e.Host)
		port, perr := strconv.Atoi(e.Port)
		if err != nil || host != e.Host || (e.Scheme != "http" && e.Scheme != "https") || perr != nil || port < 1 || port > 65535 || strconv.Itoa(port) != e.Port {
			return ErrRequirement
		}
		refs := runtimeaction.ResourceRefs([]runtimeaction.Resource{{Domain: "network", Value: e.Host}})
		if len(refs) != 1 || "network:sha256:"+refs[0].Digest != r.ResourceRef {
			return ErrRequirement
		}
	default:
		return ErrRequirement
	}
	return nil
}
func (r *Requirement) UnmarshalJSON(raw []byte) error {
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil {
		return ErrRequirement
	}
	if b, ok := fields["expected_endpoint"]; ok && bytes.Equal(bytes.TrimSpace(b), []byte("null")) {
		return ErrRequirement
	}
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
