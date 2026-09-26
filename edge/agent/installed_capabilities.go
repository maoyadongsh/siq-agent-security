package main

import (
	"context"
	"errors"
	"path/filepath"
	"regexp"
	"slices"
	"sort"
	"time"
	"unicode"

	"siq-agent-security/edge/agent/installplan"
	"siq-agent-security/edge/agent/protocol"
)

var errInstalledCapabilities = errors.New("installed_connector_capabilities_unverified")
var capabilityLabel = regexp.MustCompile(`^[A-Za-z0-9_.:/-]{1,128}$`)

type capabilityProbe func(context.Context, string, installplan.Connector) (*protocol.ConnectorCapabilities, *protocol.ValidationResult, error)

// Only call with a freshly verified private stage and a validated plan. No PATH
// lookup or discovery of executable files from scanned directories is allowed.
func installedCapabilities(ctx context.Context, stage string, p *installplan.Plan, probe capabilityProbe) (map[string]any, error) {
	if p == nil || !filepath.IsAbs(stage) || len(p.Connectors) == 0 || len(p.Connectors) > 12 {
		return nil, errInstalledCapabilities
	}
	connectors := make([]string, 0, len(p.Connectors))
	versions := map[string]string{}
	taskTypes := map[string][]string{}
	categories := map[string]bool{}
	for _, selected := range p.Connectors {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		if versions[selected.ID] != "" || !capabilityLabel.MatchString(selected.ID) || filepath.Base(selected.ID) != selected.ID {
			return nil, errInstalledCapabilities
		}
		path := filepath.Join(stage, "bin", p.TargetArch, selected.ID+"-connector")
		deadline, cancel := context.WithTimeout(ctx, 5*time.Second)
		caps, scope, err := probe(deadline, path, selected)
		if deadline.Err() != nil {
			err = deadline.Err()
		}
		cancel()
		if err != nil || caps == nil || scope == nil || !scope.Valid || len(scope.Errors) != 0 || caps.Version != selected.Version || caps.MaxOutputBytes <= 0 || caps.MaxOutputBytes > protocol.DefaultOutputLimitBytes || !validCapabilityLabels(caps.Objects, true) || !validCapabilityLabels(caps.DataCategories, false) || !validPermissionDescriptions(caps.RequiredPermissions) {
			return nil, errInstalledCapabilities
		}
		connectors = append(connectors, selected.ID)
		versions[selected.ID] = caps.Version
		taskTypes[selected.ID] = []string{"scan"}
		if selected.ID == "directory" && !caps.NetworkAccess && slices.Contains(caps.Objects, "skill_manifest") {
			taskTypes[selected.ID] = append(taskTypes[selected.ID], "skill_scan")
		}
		for _, category := range caps.DataCategories {
			categories[category] = true
		}
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	data := make([]string, 0, len(categories))
	if len(categories) > 64 {
		return nil, errInstalledCapabilities
	}
	for category := range categories {
		data = append(data, category)
	}
	sort.Strings(data)
	return map[string]any{"connectors": connectors, "protocol_version": "connector-protocol.v1", "data_categories": data, "inventory_schema": "enterprise-installed-capabilities/v2", "connector_versions": versions, "connector_task_types": taskTypes}, nil
}

// Existing connectors include local paths here. Validate bounded display text,
// not machine IDs, and never forward these potentially private paths upstream.
func validPermissionDescriptions(values []string) bool {
	if len(values) > 64 {
		return false
	}
	for _, value := range values {
		if len(value) == 0 || len(value) > 4096 {
			return false
		}
		for _, r := range value {
			if unicode.IsControl(r) {
				return false
			}
		}
	}
	return true
}

func validCapabilityLabels(values []string, required bool) bool {
	if len(values) > 64 || (required && len(values) == 0) {
		return false
	}
	for _, value := range values {
		if !capabilityLabel.MatchString(value) {
			return false
		}
	}
	return true
}

func probeInstalledConnector(ctx context.Context, path string, selected installplan.Connector) (*protocol.ConnectorCapabilities, *protocol.ValidationResult, error) {
	c, err := NewSubprocessConnector(ctx, path, SubprocessOptions{Name: selected.ID, Version: agentVersion, Timeout: 5 * time.Second, MaxOutputBytes: 64 << 10, MaxStderrBytes: 1024})
	if err != nil {
		return nil, nil, errInstalledCapabilities
	}
	defer c.Close()
	caps, err := c.Describe(ctx)
	if err != nil {
		return nil, nil, errInstalledCapabilities
	}
	scope, err := c.ValidateScope(ctx, &protocol.Scope{Roots: selected.Scope.Roots, Include: selected.Scope.Include})
	if err != nil {
		return nil, nil, errInstalledCapabilities
	}
	return caps, scope, nil
}
