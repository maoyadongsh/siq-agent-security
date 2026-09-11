package grant

import (
	"errors"
	"net"
	"regexp"
	"strconv"
	"strings"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/signing"
)

// ResourceEdit replaces the editable domain lists. Nil and empty are distinct:
// every list must be present; [] deliberately removes its existing allows.
type ResourceEdit struct {
	Tools      []string        `json:"tools"`
	Network    []NetworkPatch  `json:"network"`
	Filesystem FilesystemPatch `json:"filesystem"`
	Models     []string        `json:"models"`
}

var resourceIdentifier = regexp.MustCompile(`^[A-Za-z0-9_][A-Za-z0-9_.:/-]*$`)
var ErrResourcesInvalid = errors.New("grant_resources_invalid")

func NormalizeNetworkEndpoint(value string, wildcard bool) (string, string, bool) {
	host, port, err := net.SplitHostPort(value)
	if err != nil {
		return "", "", false
	}
	n, err := strconv.Atoi(port)
	if err != nil || n < 1 || n > 65535 {
		return "", "", false
	}
	prefix := ""
	if wildcard && strings.HasPrefix(host, "*.") {
		prefix, host = "*.", host[2:]
	}
	host, err = runtimeaction.NormalizeHost(host)
	if err != nil {
		return "", "", false
	}
	return prefix + host, strconv.Itoa(n), true
}

func EditResources(g Grant, input ResourceEdit, key *signing.Key) (Grant, DesiredPolicy, error) {
	if g.Status != "pending_approval" {
		return g, nil, errors.New("grant_resources_not_pending")
	}
	for _, values := range [][]string{input.Tools, input.Models, input.Filesystem.ReadOnly, input.Filesystem.ReadWrite} {
		if values == nil || len(values) > 32 {
			return g, nil, ErrResourcesInvalid
		}
		seen := map[string]bool{}
		for _, value := range values {
			if value == "" || seen[value] || strings.TrimSpace(value) != value {
				return g, nil, ErrResourcesInvalid
			}
			seen[value] = true
		}
	}
	for _, values := range [][]string{input.Tools, input.Models} {
		for _, value := range values {
			if utf8.RuneCountInString(value) > 128 || !resourceIdentifier.MatchString(value) {
				return g, nil, ErrResourcesInvalid
			}
		}
	}
	for _, values := range [][]string{input.Filesystem.ReadOnly, input.Filesystem.ReadWrite} {
		for _, value := range values {
			normalized, err := runtimeaction.NormalizeResource("filesystem", value)
			if err != nil || normalized != value || utf8.RuneCountInString(value) > 4096 {
				return g, nil, ErrResourcesInvalid
			}
			for _, r := range value {
				if r < 32 || r == 127 {
					return g, nil, ErrResourcesInvalid
				}
			}
		}
	}
	if input.Network == nil || len(input.Network) > 32 {
		return g, nil, ErrResourcesInvalid
	}
	network := make([]NetworkPatch, 0, len(input.Network))
	seen := map[string]bool{}
	for _, entry := range input.Network {
		host, port, ok := NormalizeNetworkEndpoint(entry.Endpoint, true)
		if !ok || utf8.RuneCountInString(entry.Endpoint) > 512 || (entry.Effect != "allow" && entry.Effect != "deny") {
			return g, nil, ErrResourcesInvalid
		}
		entry.Endpoint = net.JoinHostPort(host, port)
		identity := entry.Endpoint + "/" + entry.Effect
		if seen[identity] {
			return g, nil, ErrResourcesInvalid
		}
		seen[identity] = true
		network = append(network, entry)
	}
	return PatchDesired(g, DesiredPatch{HasTools: true, Tools: input.Tools, HasNetwork: true, Network: network, HasFilesystem: true, Filesystem: &input.Filesystem, HasModels: true, Models: input.Models, PreserveFilesystemDenies: true, PreserveModelDenies: true}, key)
}
