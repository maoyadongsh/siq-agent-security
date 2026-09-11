package receipt

import (
	"net"
	"net/url"
	"path"
	"strings"

	"siq-agent-security/apps/agentshield/internal/grant"
)

// Structured network tools must name their actual endpoint. Text in request
// payloads cannot supply missing authority or change the selected target.
func structuredGrantEndpoints(params map[string]any) ([]string, bool) {
	endpoints := []string{}
	for _, name := range []string{"url", "host"} {
		value, exists := params[name]
		if !exists {
			continue
		}
		raw, ok := value.(string)
		if !ok || raw == "" || strings.TrimSpace(raw) != raw {
			return nil, false
		}
		endpoint := raw
		if name == "url" || strings.Contains(raw, "://") {
			u, err := url.Parse(raw)
			if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.User != nil || u.Hostname() == "" {
				return nil, false
			}
			port := u.Port()
			if port == "" {
				if strings.HasSuffix(u.Host, ":") {
					return nil, false
				}
				port = "80"
				if u.Scheme == "https" {
					port = "443"
				}
			}
			endpoint = net.JoinHostPort(u.Hostname(), port)
		}
		host, port, ok := grantEndpoint(endpoint, false)
		if !ok {
			return nil, false
		}
		endpoints = append(endpoints, net.JoinHostPort(host, port))
	}
	return endpoints, len(endpoints) > 0
}

func grantEndpoint(value string, wildcard bool) (string, string, bool) {
	return grant.NormalizeNetworkEndpoint(value, wildcard)
}

func hostGranted(g *grant.Grant, endpoint string) (string, bool) {
	host, port, valid := grantEndpoint(endpoint, false)
	if !valid {
		return "", false
	}
	matched := ""
	for _, f := range g.Facts {
		if f.Domain != "network" {
			continue
		}
		if f.Effect == "deny" && f.Resource.Value == "*" {
			return "", false
		}
		pattern, wantedPort, ok := grantEndpoint(f.Resource.Value, true)
		if !ok && f.Effect == "deny" {
			return "", false
		}
		if !ok || wantedPort != port {
			continue
		}
		if pattern != host && !(strings.HasPrefix(pattern, "*.") && strings.HasSuffix(host, pattern[1:])) {
			continue
		}
		if f.Effect == "deny" {
			return "", false
		}
		if f.Effect == "allow" {
			matched = f.FactID
		}
	}
	return matched, matched != ""
}

func pathGranted(g *grant.Grant, target string, write bool) (string, bool) {
	if strings.ContainsAny(target, "\\\x00") {
		return "", false
	}
	target = path.Clean(target)
	matched := ""
	for _, f := range g.Facts {
		if f.Domain != "filesystem" || (f.Action != "fs.read" && f.Action != "fs.write") {
			continue
		}
		if write && f.Action != "fs.write" {
			continue
		}
		// A read-only denial does not independently deny writes; a read/write
		// denial covers both operations, matching read_write scope semantics.
		pattern := f.Resource.Value
		if pattern == "*" && f.Effect == "deny" {
			return "", false
		}
		if strings.ContainsAny(pattern, "\\\x00") || pattern == "" {
			continue
		}
		pattern = strings.TrimSuffix(path.Clean(pattern), "/")
		if target != pattern && !strings.HasPrefix(target, pattern+"/") {
			continue
		}
		if f.Effect == "deny" {
			return "", false
		}
		if f.Effect == "allow" {
			matched = f.FactID
		}
	}
	return matched, matched != ""
}
