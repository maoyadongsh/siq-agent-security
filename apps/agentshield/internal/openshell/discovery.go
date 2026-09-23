package openshell

import (
	"encoding/json"
	"io"
	"sort"
	"strings"
	"time"
)

type DiscoveredTarget struct {
	ID      string `json:"sandbox_id"`
	Name    string `json:"name"`
	Phase   string `json:"phase"`
	Version string `json:"policy_version"`
}

type TargetCatalog struct {
	Schema         string             `json:"schema_version"`
	ObservedAt     string             `json:"observed_at"`
	State          string             `json:"state"`
	CLIFound       bool               `json:"cli_found"`
	Source         string             `json:"source"`
	CLIVersion     string             `json:"cli_version"`
	Gateway        string             `json:"gateway"`
	Fingerprint    string             `json:"endpoint_fingerprint"`
	CanInspect     bool               `json:"can_inspect"`
	Items          []DiscoveredTarget `json:"items"`
	StartedGateway bool               `json:"started_gateway"`
}

type TargetInspection struct {
	Schema      string `json:"schema_version"`
	ID          string `json:"sandbox_id"`
	Name        string `json:"name"`
	Fingerprint string `json:"endpoint_fingerprint"`
	ObservedAt  string `json:"observed_at"`
	ExpiresAt   string `json:"expires_at"`
	State       string `json:"state"`
	Revision    string `json:"revision"`
	Digest      string `json:"policy_digest"`
	Enforcement bool   `json:"enforcement_verified"`
}

func parseDiscoveredTargets(raw string) ([]DiscoveredTarget, error) {
	decoder := json.NewDecoder(strings.NewReader(raw))
	decoder.UseNumber()
	var rows []sandboxLoadRow
	var trailing any
	if decoder.Decode(&rows) != nil || rows == nil || len(rows) >= 1000 || decoder.Decode(&trailing) != io.EOF {
		return nil, fail("openshell_catalog_invalid")
	}
	items := make([]DiscoveredTarget, 0, len(rows))
	ids, names := map[string]bool{}, map[string]bool{}
	for _, row := range rows {
		if !sandboxUUID.MatchString(row.ID) || !validTaskTarget(row.Name) || ids[row.ID] || names[row.Name] {
			return nil, fail("openshell_catalog_invalid")
		}
		version, err := row.CurrentPolicyVersion.Int64()
		if err != nil || version < 0 {
			return nil, fail("openshell_catalog_invalid")
		}
		phase := row.Phase
		switch phase {
		case "Ready", "Pending", "Creating", "Running", "Stopping", "Stopped", "Error", "Terminated":
		default:
			phase = "Unknown"
		}
		ids[row.ID], names[row.Name] = true, true
		items = append(items, DiscoveredTarget{ID: row.ID, Name: row.Name, Phase: phase, Version: row.CurrentPolicyVersion.String()})
	}
	sort.Slice(items, func(i, j int) bool { return items[i].Name < items[j].Name })
	return items, nil
}

// DiscoverTargets never executes tools, creates resources, or falls back to
// container-name guesses. Unbound CLI configurations remain discovery-only.
func (c *Client) DiscoverTargets() TargetCatalog {
	out := TargetCatalog{Schema: "local-openshell-targets/v1", ObservedAt: time.Now().UTC().Format(time.RFC3339Nano), State: "unconfigured", Source: SourceNone, Items: []DiscoveredTarget{}}
	if c == nil {
		return out
	}
	d := c.Diagnose()
	out.CLIFound, out.Source, out.Gateway = d.CLIFound, d.Source, d.ActiveGateway
	if d.Capabilities != nil {
		out.CLIVersion = d.Capabilities.CLIVersion
	}
	if !d.ProbeOK {
		if out.CLIFound || out.Source == SourceInvalid || out.Source == SourceEnvSH {
			out.State = "unreachable"
		}
		return out
	}
	before := c.InvocationFingerprint()
	out.State = "catalog_unavailable"
	raw, err := c.cli("sandbox", "list", "--limit", "1000", "--output", "json")
	if err != nil || before != c.InvocationFingerprint() {
		return out
	}
	items, err := parseDiscoveredTargets(raw)
	if err != nil {
		return out
	}
	out.State, out.Items = "available", items
	out.Fingerprint = before
	out.CanInspect = before != "" && d.Capabilities != nil && d.Capabilities.EndpointFingerprint == before
	return out
}

func catalogContains(c TargetCatalog, id, name, fingerprint string) bool {
	if c.State != "available" || !c.CanInspect || fingerprint == "" || c.Fingerprint != fingerprint {
		return false
	}
	for _, item := range c.Items {
		if item.ID == id && item.Name == name {
			return true
		}
	}
	return false
}

func (c *Client) InspectDiscoveredTarget(id, name, fingerprint string) (TargetInspection, error) {
	return c.inspectDiscoveredTarget(id, name, fingerprint, "")
}

func (c *Client) inspectDiscoveredTarget(id, name, fingerprint, expectedGateway string) (TargetInspection, error) {
	if c == nil || !sandboxUUID.MatchString(id) || !validTaskTarget(name) || len(fingerprint) != 64 {
		return TargetInspection{}, fail("openshell_target_selection_changed")
	}
	before := c.DiscoverTargets()
	if !catalogContains(before, id, name, fingerprint) || expectedGateway != "" && before.Gateway != expectedGateway {
		return TargetInspection{}, fail("openshell_target_selection_changed")
	}
	d := c.DiagnoseTarget(name)
	if !d.ProbeOK || d.State != StatePolicyReadable || d.Revision == "" || len(d.PolicyDigest) != 64 {
		return TargetInspection{}, fail("openshell_target_policy_unavailable")
	}
	after := c.DiscoverTargets()
	if !catalogContains(after, id, name, fingerprint) || before.Gateway != after.Gateway || expectedGateway != "" && after.Gateway != expectedGateway {
		return TargetInspection{}, fail("openshell_target_selection_changed")
	}
	for _, item := range after.Items {
		if item.ID == id && item.Version != d.Revision {
			return TargetInspection{}, fail("openshell_target_selection_changed")
		}
	}
	return TargetInspection{Schema: "local-openshell-target-inspection/v1", ID: id, Name: name, Fingerprint: fingerprint,
		ObservedAt: d.ObservedAt, ExpiresAt: d.ExpiresAt, State: "policy_readable", Revision: d.Revision, Digest: d.PolicyDigest}, nil
}
