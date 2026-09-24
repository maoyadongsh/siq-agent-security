package runtimeaction

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"net"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"runtime"
	"sort"
	"strings"

	"siq-agent-security/apps/agentshield/internal/canon"
)

// Resource contains transient normalized values. Never serialize this as evidence.
type Resource struct {
	Domain string
	Value  string
}

// ResourceRef binds an audit record to a resource without adding its plaintext.
type ResourceRef struct {
	Domain string `json:"domain"`
	Digest string `json:"digest"`
}

// Principal is supplied only by the verified authority, never the decision client.
type Principal struct {
	Type string `json:"type"`
	ID   string `json:"id"`
}

var ErrResource = errors.New("runtimeaction: invalid resource")

func NormalizeResource(domain, value string) (string, error) {
	if value == "" {
		return "", ErrResource
	}
	switch domain {
	case "filesystem":
		if !path.IsAbs(value) || strings.ContainsAny(value, "\\\x00") {
			return "", ErrResource
		}
		// Keep the existing in-root ".." contract, but refuse it when a
		// symlink component exists: cleaning first would erase a component the
		// host resolves before ".." and could bind another filesystem object.
		if runtime.GOOS != "windows" && hasDotDot(value) && hasSymlinkComponent(value) {
			return "", ErrResource
		}
		return path.Clean(value), nil
	case "network":
		return NormalizeHost(value)
	case "message":
		// Recipient identifiers are case-sensitive opaque identities, not email guesses.
		for _, r := range value {
			if r < 32 || r == 127 {
				return "", ErrResource
			}
		}
		return value, nil
	default:
		return "", ErrResource
	}
}

func hasDotDot(value string) bool {
	for _, component := range strings.Split(value, "/") {
		if component == ".." {
			return true
		}
	}
	return false
}

func hasSymlinkComponent(value string) bool {
	current := string(filepath.Separator)
	for _, component := range strings.Split(value, "/") {
		if component == "" || component == "." {
			continue
		}
		if component == ".." {
			current = filepath.Dir(current)
			continue
		}
		current = filepath.Join(current, component)
		info, err := os.Lstat(current)
		if err == nil && info.Mode()&os.ModeSymlink != 0 {
			return true
		}
		if err != nil && !os.IsNotExist(err) {
			return true
		}
	}
	return false
}

// NormalizeHost fixes the wire policy to ASCII DNS/Punycode or IP literals.
// Unicode hostnames are rejected, never mapped differently by different libraries.
func NormalizeHost(value string) (string, error) {
	if strings.Contains(value, "://") {
		u, err := url.Parse(value)
		if err != nil || u.Hostname() == "" || u.User != nil {
			return "", ErrResource
		}
		value = u.Hostname()
	}
	value = strings.ToLower(strings.TrimSuffix(value, "."))
	if ip := net.ParseIP(value); ip != nil {
		return ip.String(), nil
	}
	if len(value) == 0 || len(value) > 253 {
		return "", ErrResource
	}
	for _, label := range strings.Split(value, ".") {
		if len(label) == 0 || len(label) > 63 || label[0] == '-' || label[len(label)-1] == '-' {
			return "", ErrResource
		}
		for _, r := range label {
			if !(r >= 'a' && r <= 'z' || r >= '0' && r <= '9' || r == '-') {
				return "", ErrResource
			}
		}
	}
	return value, nil
}

// ExtractResources examines only known structured fields. It never infers a shell
// target from command text; missing/invalid values remain unavailable to matching.
func extractResources(tool string, params map[string]any) ([]Resource, error) {
	return extractResourcesWithNormalizer(tool, params, NormalizeResource)
}

func extractResourcesWithNormalizer(tool string, params map[string]any, normalize func(string, string) (string, error)) ([]Resource, error) {
	if fixed, ok := generationDescriptor(tool, params, normalize); ok {
		return fixed.Resources, fixed.ResourceError
	}
	if businessReportShape(tool, params) {
		root, err := normalize("filesystem", ResearchBusinessRoot)
		if err != nil {
			return nil, err
		}
		return []Resource{{Domain: "filesystem", Value: root}}, nil
	}
	_, effects := normalizeEffects(tool, params)
	domain := ""
	keys := []string{}
	switch effects[0] {
	case EffectFileRead, EffectFileWrite, EffectFileDelete:
		domain = "filesystem"
		keys = []string{"path", "file_path"}
	case EffectNetworkRequest:
		domain = "network"
		keys = []string{"url", "host"}
	case EffectMessageSend:
		domain = "message"
		keys = []string{"recipient", "to"}
	default:
		return nil, nil
	}
	out := []Resource{}
	seen := map[string]bool{}
	for _, key := range keys {
		raw, exists := params[key]
		if !exists {
			continue
		}
		value, ok := raw.(string)
		if !ok {
			return nil, ErrResource
		}
		value, err := normalize(domain, value)
		if err != nil {
			return nil, err
		}
		if !seen[value] {
			out = append(out, Resource{domain, value})
			seen[value] = true
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Value < out[j].Value })
	return out, nil
}
func ResourceRefs(resources []Resource) []ResourceRef {
	out := make([]ResourceRef, 0, len(resources))
	for _, r := range resources {
		raw, err := canon.Marshal(map[string]any{"domain": r.Domain, "value": r.Value})
		if err != nil {
			panic("runtimeaction: invalid canonical resource")
		}
		digest := sha256.Sum256(raw)
		out = append(out, ResourceRef{r.Domain, hex.EncodeToString(digest[:])})
	}
	return out
}

func ExtractResources(tool string, params map[string]any) ([]Resource, error) {
	d := Describe(tool, params)
	return d.Resources, d.ResourceError
}
