package receipt

import (
	"errors"
	"io/fs"
	"net"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"runtime"
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
	if g.SchemaVersion != "" {
		return windowsPathGranted(g, target, write)
	}
	if strings.ContainsAny(target, "\\\x00") {
		return "", false
	}
	target = path.Clean(target)
	// The agent and local daemon share a filesystem on Unix. Lexical scope
	// alone lets /granted/alias -> /private escape a read-only Grant, or lets
	// an alias bypass an explicit deny below the granted root. Resolve the
	// existing prefix on every decision; never cache symlink observations.
	// Windows path identity needs its own host-specific contract and remains
	// on the existing lexical path until that adapter's real-host validation.
	canonicalTarget := ""
	if runtime.GOOS != "windows" {
		var ok bool
		canonicalTarget, ok = canonicalPathWithMissingTail(target)
		if !ok {
			return "", false
		}
	}
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
		pattern = path.Clean(pattern)
		if pattern != "/" {
			pattern = strings.TrimSuffix(pattern, "/")
		}
		lexicalMatch := pattern == "/" || target == pattern || strings.HasPrefix(target, pattern+"/")
		physicalMatch := lexicalMatch
		if runtime.GOOS != "windows" {
			canonicalPattern, ok := canonicalPathWithMissingTail(pattern)
			if !ok {
				return "", false
			}
			physicalMatch = pathWithin(canonicalPattern, canonicalTarget)
		}
		if f.Effect == "deny" {
			if lexicalMatch || physicalMatch {
				return "", false
			}
			continue
		}
		if f.Effect == "allow" && lexicalMatch && physicalMatch {
			matched = f.FactID
		}
	}
	return matched, matched != ""
}

func pathWithin(root, target string) bool {
	rel, err := filepath.Rel(root, target)
	return err == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator))
}

// canonicalPathWithMissingTail resolves every existing ancestor. Writes may
// name a file that does not exist yet, so a missing tail is appended to the
// resolved ancestor. Dangling links, loops and inaccessible ancestors fail
// closed. This is a decision-time guard, not an atomic openat2-style sandbox:
// a host can still race a symlink swap after the decision.
func canonicalPathWithMissingTail(value string) (string, bool) {
	current := filepath.FromSlash(value)
	if !filepath.IsAbs(current) {
		return "", false
	}
	var missing []string
	for {
		_, err := os.Lstat(current)
		if err == nil {
			resolved, resolveErr := filepath.EvalSymlinks(current)
			if resolveErr != nil {
				return "", false
			}
			for i := len(missing) - 1; i >= 0; i-- {
				resolved = filepath.Join(resolved, missing[i])
			}
			return filepath.Clean(resolved), true
		}
		if !errors.Is(err, fs.ErrNotExist) {
			return "", false
		}
		parent := filepath.Dir(current)
		if parent == current {
			return "", false
		}
		missing = append(missing, filepath.Base(current))
		current = parent
	}
}
