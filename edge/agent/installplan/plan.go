// Package installplan validates installation metadata, never business authority.
package installplan

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/url"
	"reflect"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

const MaxBytes = 2 << 20

var ErrInvalid = errors.New("invalid_install_plan")

type Scope struct {
	Roots   []string `json:"roots"`
	Include []string `json:"include"`
}
type Connector struct {
	ID              string `json:"id"`
	Version         string `json:"version"`
	ArtifactSHA256  string `json:"artifact_sha256"`
	ProtocolVersion string `json:"protocol_version"`
	Scope           Scope  `json:"scope"`
}
type Plan struct {
	SchemaVersion         string      `json:"schema_version"`
	PlanID                string      `json:"plan_id"`
	TenantID              string      `json:"tenant_id"`
	EnvironmentID         string      `json:"environment_id"`
	ControlPlaneOrigin    string      `json:"control_plane_origin"`
	IssuedAt              string      `json:"issued_at"`
	ExpiresAt             string      `json:"expires_at"`
	TargetOS              string      `json:"target_os"`
	TargetArch            string      `json:"target_arch"`
	ServiceMode           string      `json:"service_mode"`
	ReleaseVersion        string      `json:"release_version"`
	ReleaseManifestSHA256 string      `json:"release_manifest_sha256"`
	Connectors            []Connector `json:"connectors"`
	Purpose               string      `json:"purpose"`
}

var (
	id        = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`)
	digest    = regexp.MustCompile(`^[a-f0-9]{64}$`)
	version   = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}$`)
	planID    = regexp.MustCompile(`^eip-[a-f0-9]{32}$`)
	timestamp = regexp.MustCompile(`^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z$`)
	origin    = regexp.MustCompile(`^(https://[^/?#@\s]+|http://(localhost|127\.0\.0\.1|\[::1\])(:[0-9]+)?)$`)
	filename  = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]*$`)
)

// Parse accepts exact keys only, rejecting duplicate keys, nulls and extra JSON.
// Errors intentionally never echo potentially secret/untrusted input.
func Parse(raw []byte) (*Plan, error) {
	if len(raw) > MaxBytes || !utf8.Valid(raw) {
		return nil, ErrInvalid
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	value, err := readValue(d, 0)
	if err != nil {
		return nil, ErrInvalid
	}
	if _, err = d.Token(); err != io.EOF {
		return nil, ErrInvalid
	}
	if !exactShape(value, reflect.TypeOf(Plan{})) {
		return nil, ErrInvalid
	}
	var p Plan
	if json.Unmarshal(raw, &p) != nil || p.Validate() != nil {
		return nil, ErrInvalid
	}
	return &p, nil
}

func readValue(d *json.Decoder, depth int) (any, error) {
	if depth > 16 {
		return nil, ErrInvalid
	}
	token, err := d.Token()
	if err != nil || token == nil {
		return nil, ErrInvalid
	}
	if delim, ok := token.(json.Delim); ok {
		switch delim {
		case '{':
			m := map[string]any{}
			for d.More() {
				k, e := d.Token()
				if e != nil {
					return nil, ErrInvalid
				}
				key, ok := k.(string)
				if !ok {
					return nil, ErrInvalid
				}
				if _, exists := m[key]; exists {
					return nil, ErrInvalid
				}
				v, e := readValue(d, depth+1)
				if e != nil {
					return nil, e
				}
				m[key] = v
			}
			end, e := d.Token()
			if e != nil || end != json.Delim('}') {
				return nil, ErrInvalid
			}
			return m, nil
		case '[':
			a := []any{}
			for d.More() {
				v, e := readValue(d, depth+1)
				if e != nil {
					return nil, e
				}
				a = append(a, v)
			}
			end, e := d.Token()
			if e != nil || end != json.Delim(']') {
				return nil, ErrInvalid
			}
			return a, nil
		default:
			return nil, ErrInvalid
		}
	}
	return token, nil
}

func exactShape(v any, t reflect.Type) bool {
	switch t.Kind() {
	case reflect.Struct:
		m, ok := v.(map[string]any)
		if !ok || len(m) != t.NumField() {
			return false
		}
		for i := 0; i < t.NumField(); i++ {
			f := t.Field(i)
			value, exists := m[f.Tag.Get("json")]
			if !exists || !exactShape(value, f.Type) {
				return false
			}
		}
		return true
	case reflect.Slice:
		a, ok := v.([]any)
		if !ok {
			return false
		}
		for _, value := range a {
			if !exactShape(value, t.Elem()) {
				return false
			}
		}
		return true
	case reflect.String:
		_, ok := v.(string)
		return ok
	case reflect.Int64:
		n, ok := v.(json.Number)
		if !ok {
			return false
		}
		_, err := n.Int64()
		return err == nil
	}
	return false
}

func (p Plan) Validate() error {
	if p.SchemaVersion != "enterprise-install-plan/v1" || !planID.MatchString(p.PlanID) || !id.MatchString(p.TenantID) || !id.MatchString(p.EnvironmentID) || p.TargetOS != "linux" || (p.TargetArch != "arm64" && p.TargetArch != "amd64") || (p.ServiceMode != "user" && p.ServiceMode != "system") || !version.MatchString(p.ReleaseVersion) || !digest.MatchString(p.ReleaseManifestSHA256) || p.Purpose != "discovery_only" {
		return ErrInvalid
	}
	if !validOrigin(p.ControlPlaneOrigin) {
		return ErrInvalid
	}
	start, e1 := time.Parse(time.RFC3339Nano, p.IssuedAt)
	end, e2 := time.Parse(time.RFC3339Nano, p.ExpiresAt)
	if !timestamp.MatchString(p.IssuedAt) || !timestamp.MatchString(p.ExpiresAt) || e1 != nil || e2 != nil || start.Year() < 1 || end.Year() < 1 || end.Sub(start) <= 0 || end.Sub(start) > 15*time.Minute {
		return ErrInvalid
	}
	if len(p.Connectors) < 1 || len(p.Connectors) > 12 {
		return ErrInvalid
	}
	seen := map[string]bool{}
	for _, c := range p.Connectors {
		if seen[c.ID] || !oneOf(c.ID, "hermes", "openclaw", "directory", "docker", "process", "systemd", "kubernetes", "mcp", "piagent", "workbuddy", "dify", "siq") || !version.MatchString(c.Version) || !digest.MatchString(c.ArtifactSHA256) || c.ProtocolVersion != "connector-protocol.v1" || !validScope(c.Scope) {
			return ErrInvalid
		}
		seen[c.ID] = true
	}
	return nil
}

// RequireCurrent binds a plan to trusted expected context, not self-declared fields.
// Manifest signature, permissions, consent and actual host architecture remain
// mandatory caller checks before installation; this method performs no writes.
func (p Plan) RequireCurrent(now time.Time, tenant, environment, controlPlane, arch string) error {
	if p.Validate() != nil || p.TenantID != tenant || p.EnvironmentID != environment || p.ControlPlaneOrigin != controlPlane || p.TargetArch != arch {
		return ErrInvalid
	}
	start, _ := time.Parse(time.RFC3339Nano, p.IssuedAt)
	end, _ := time.Parse(time.RFC3339Nano, p.ExpiresAt)
	if now.Before(start) || !now.Before(end) {
		return ErrInvalid
	}
	return nil
}

func oneOf(value string, choices ...string) bool {
	for _, c := range choices {
		if value == c {
			return true
		}
	}
	return false
}
func control(s string) bool {
	for _, r := range s {
		if r < 32 || r == 127 {
			return true
		}
	}
	return false
}
func validOrigin(s string) bool {
	if utf8.RuneCountInString(s) > 2048 || !origin.MatchString(s) || control(s) || strings.ContainsAny(s, "\\?#%") || strings.IndexFunc(s, unicode.IsSpace) >= 0 {
		return false
	}
	u, err := url.Parse(s)
	if err != nil || u.Hostname() == "" || u.User != nil || u.Path != "" || strings.HasSuffix(u.Host, ":") {
		return false
	}
	if u.Port() != "" {
		n, err := strconv.Atoi(u.Port())
		if err != nil || n < 1 || n > 65535 {
			return false
		}
	}
	return true
}
func validScope(s Scope) bool {
	if len(s.Roots) < 1 || len(s.Roots) > 32 || len(s.Include) < 1 || len(s.Include) > 32 {
		return false
	}
	seen := map[string]bool{}
	for _, root := range s.Roots {
		base := strings.TrimSuffix(root, "/*")
		if seen[root] || utf8.RuneCountInString(root) < 3 || utf8.RuneCountInString(root) > 4096 || (!strings.HasPrefix(base, "/") && !strings.HasPrefix(base, "~/")) || oneOf(base, "/", "~", "~/", "/home", "/root", "/etc", "/proc", "/sys", "/dev") || strings.ContainsAny(base, "*?[]\\") || control(root) || strings.Contains(base, "//") || strings.HasSuffix(base, "/") {
			return false
		}
		for _, part := range strings.Split(base, "/") {
			if part == "." || part == ".." {
				return false
			}
		}
		seen[root] = true
	}
	seen = map[string]bool{}
	for _, name := range s.Include {
		if seen[name] || len(name) > 128 || !filename.MatchString(name) || oneOf(strings.ToLower(name), "auth-profiles.json", "credentials.json", "id_rsa", "id_ed25519") {
			return false
		}
		seen[name] = true
	}
	return true
}
