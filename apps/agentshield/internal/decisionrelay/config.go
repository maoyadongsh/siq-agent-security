// Package decisionrelay implements the host-owned OpenShell decision transport.
// It deliberately owns no credential: the sandbox presents its Runtime Identity
// bearer and the daemon performs the authority check on every request.
package decisionrelay

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"time"
)

const (
	SchemaVersion          = "openshell-decision-relay/v2"
	CandidateSchemaVersion = "openshell-decision-relay/v3"
	IsolatedSchemaVersion  = "openshell-decision-relay/v4"
	IsolatedLoopbackURL    = "http://127.0.0.1:47811"
	LoopbackURL            = "http://127.0.0.1:47611"
	SandboxURL             = "http://host.openshell.internal:47611"
	ListenerTransport      = "verified_docker_bridge_gateway/v1"
	MaxPayloadBytes        = int64(1 << 20)
	ListenerPortMin        = 47611
	ListenerPortMax        = 47710
)

var (
	runtimeIdentityPattern      = regexp.MustCompile(`^ri-[a-f0-9]{32}$`)
	instancePattern             = regexp.MustCompile(`^hi-[a-f0-9]{32}$`)
	agentPattern                = regexp.MustCompile(`^hri-[a-f0-9]{32}$`)
	sandboxNamePattern          = regexp.MustCompile(`^siq-analysis-[a-z0-9][a-z0-9-]{0,62}$`)
	candidateSandboxNamePattern = regexp.MustCompile(`^siq-qwen38-scoped-[a-f0-9]{16}$`)
	uuidPattern                 = regexp.MustCompile(`^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$`)
	scopePattern                = regexp.MustCompile(`^[a-f0-9]{24}$`)
	runPattern                  = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`)
	sessionNamespacePattern     = regexp.MustCompile(
		`^siq:openshell:pool:[a-f0-9]{24}:[A-Za-z0-9][A-Za-z0-9._-]{0,127}:siq_analysis$`,
	)
	containerIDPattern = regexp.MustCompile(`^[a-f0-9]{64}$`)
	networkIDPattern   = regexp.MustCompile(`^[a-f0-9]{64}$`)
)

var AllowedRoutes = []string{
	"/v1/runtime-sessions",
	"/v1/decide",
	"/v1/observe",
	"/v1/hold-status",
	"/v1/hold-executions/reserve",
	"/v1/provenance-reports",
	"/v1/raw-task-content/native-captures",
}

type Binding struct {
	Platform          string `json:"platform"`
	RuntimeIdentityID string `json:"runtime_identity_id"`
	InstanceID        string `json:"instance_id"`
	AgentID           string `json:"agent_id"`
	SandboxNamespace  string `json:"sandbox_namespace"`
	SandboxName       string `json:"sandbox_name"`
	SandboxID         string `json:"sandbox_id"`
	SandboxGeneration int    `json:"sandbox_generation"`
	Profile           string `json:"profile"`
	ScopeID           string `json:"scope_id"`
	RunID             string `json:"run_id"`
	SessionNamespace  string `json:"session_namespace"`
}

type Listener struct {
	URL               string `json:"url"`
	InheritedFD       int    `json:"inherited_fd"`
	Transport         string `json:"transport"`
	TargetContainerID string `json:"target_container_id"`
	NetworkName       string `json:"network_name"`
	NetworkID         string `json:"network_id"`
	GatewayIP         string `json:"gateway_ip"`
	HostAlias         string `json:"host_alias"`
}

type Config struct {
	SchemaVersion     string   `json:"schema_version"`
	Binding           Binding  `json:"binding"`
	Listener          Listener `json:"listener"`
	Upstream          string   `json:"upstream"`
	AllowedRoutes     []string `json:"allowed_routes"`
	MaxRequestBytes   int64    `json:"max_request_bytes"`
	MaxResponseBytes  int64    `json:"max_response_bytes"`
	UpstreamTimeoutMS int      `json:"upstream_timeout_ms"`
}

func ParseConfig(raw []byte) (Config, error) {
	var cfg Config
	if len(raw) == 0 || len(raw) > 64<<10 || !uniqueJSON(raw) {
		return cfg, errors.New("decision relay: invalid configuration")
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&cfg); err != nil {
		return Config{}, errors.New("decision relay: invalid configuration")
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF || cfg.Validate() != nil {
		return Config{}, errors.New("decision relay: invalid configuration")
	}
	return cfg, nil
}

func LoadConfig(path string) (Config, error) {
	if !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return Config{}, errors.New("decision relay: config path must be absolute and clean")
	}
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Mode()&0o077 != 0 {
		return Config{}, errors.New("decision relay: config must be a private regular file")
	}
	handle, err := os.Open(path)
	if err != nil {
		return Config{}, errors.New("decision relay: configuration unavailable")
	}
	defer handle.Close()
	opened, err := handle.Stat()
	if err != nil || !os.SameFile(info, opened) {
		return Config{}, errors.New("decision relay: configuration identity changed")
	}
	return LoadConfigFile(handle)
}

// LoadConfigFile loads a configuration from an already-open regular file.
// The privileged namespace launcher uses this path so the relay can drop all
// privileges before parsing configuration that remains private to the host
// lifecycle user. The caller retains ownership of file.
func LoadConfigFile(file *os.File) (Config, error) {
	if file == nil {
		return Config{}, errors.New("decision relay: configuration unavailable")
	}
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Mode()&0o077 != 0 || info.Mode()&(os.ModeSetuid|os.ModeSetgid) != 0 {
		return Config{}, errors.New("decision relay: config must be a private regular file")
	}
	if _, err := file.Seek(0, io.SeekStart); err != nil {
		return Config{}, errors.New("decision relay: configuration unavailable")
	}
	raw, err := io.ReadAll(io.LimitReader(file, (64<<10)+1))
	if err != nil || len(raw) > 64<<10 {
		return Config{}, errors.New("decision relay: configuration unavailable")
	}
	return ParseConfig(raw)
}

func (cfg Config) Validate() error {
	b := cfg.Binding
	validSandbox := cfg.SchemaVersion == SchemaVersion && b.SandboxNamespace == "siq-openshell-dev" && sandboxNamePattern.MatchString(b.SandboxName)
	if cfg.SchemaVersion == CandidateSchemaVersion || cfg.SchemaVersion == IsolatedSchemaVersion {
		validSandbox = b.SandboxNamespace == "siq-openshell-scope-validation" && candidateSandboxNamePattern.MatchString(b.SandboxName)
	}
	if !validSandbox || b.Platform != "hermes" ||
		!runtimeIdentityPattern.MatchString(b.RuntimeIdentityID) || !instancePattern.MatchString(b.InstanceID) ||
		!agentPattern.MatchString(b.AgentID) || b.AgentID[4:] != b.InstanceID[3:] ||
		!uuidPattern.MatchString(b.SandboxID) || b.SandboxGeneration < 1 || b.Profile != "siq_analysis" ||
		!scopePattern.MatchString(b.ScopeID) || !runPattern.MatchString(b.RunID) ||
		!sessionNamespacePattern.MatchString(b.SessionNamespace) ||
		b.SessionNamespace != "siq:openshell:pool:"+b.ScopeID+":"+b.RunID+":siq_analysis" {
		return errors.New("invalid binding")
	}
	l := cfg.Listener
	if _, err := cfg.ListenerPort(); err != nil {
		return errors.New("invalid listener")
	}
	gatewayIP := net.ParseIP(l.GatewayIP)
	if l.InheritedFD < 3 || l.InheritedFD > 1024 ||
		l.Transport != ListenerTransport || !containerIDPattern.MatchString(l.TargetContainerID) ||
		l.NetworkName != "siq-openshell-dev" || !networkIDPattern.MatchString(l.NetworkID) ||
		l.HostAlias != "host.openshell.internal" || gatewayIP == nil || gatewayIP.To4() == nil ||
		!gatewayIP.IsPrivate() || gatewayIP.IsLoopback() || gatewayIP.IsUnspecified() || gatewayIP.IsMulticast() {
		return errors.New("invalid listener")
	}
	upstream := LoopbackURL
	if cfg.SchemaVersion == IsolatedSchemaVersion {
		upstream = IsolatedLoopbackURL
	}
	if cfg.Upstream != upstream || cfg.MaxRequestBytes != MaxPayloadBytes ||
		cfg.MaxResponseBytes != MaxPayloadBytes || cfg.UpstreamTimeoutMS < 250 || cfg.UpstreamTimeoutMS > 20000 ||
		len(cfg.AllowedRoutes) != len(AllowedRoutes) {
		return errors.New("invalid transport")
	}
	for index := range AllowedRoutes {
		if cfg.AllowedRoutes[index] != AllowedRoutes[index] {
			return errors.New("invalid route allowlist")
		}
	}
	return nil
}

func (cfg Config) ListenerPort() (int, error) {
	parsed, err := url.Parse(cfg.Listener.URL)
	if err != nil || parsed.Scheme != "http" || parsed.User != nil ||
		parsed.Hostname() != "host.openshell.internal" || parsed.Path != "" || parsed.RawPath != "" ||
		parsed.RawQuery != "" || parsed.ForceQuery || parsed.Fragment != "" || parsed.String() != cfg.Listener.URL {
		return 0, errors.New("invalid listener")
	}
	port, err := strconv.Atoi(parsed.Port())
	if err != nil || port < ListenerPortMin || port > ListenerPortMax ||
		cfg.Listener.URL != fmt.Sprintf("http://host.openshell.internal:%d", port) {
		return 0, errors.New("invalid listener")
	}
	return port, nil
}

func (cfg Config) UpstreamTimeout() time.Duration {
	return time.Duration(cfg.UpstreamTimeoutMS) * time.Millisecond
}

func uniqueJSON(raw []byte) bool {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	var walk func() bool
	walk = func() bool {
		token, err := decoder.Token()
		if err != nil {
			return false
		}
		delim, compound := token.(json.Delim)
		if !compound {
			return true
		}
		switch delim {
		case '{':
			seen := map[string]bool{}
			for decoder.More() {
				key, err := decoder.Token()
				name, ok := key.(string)
				if err != nil || !ok || seen[name] {
					return false
				}
				seen[name] = true
				if !walk() {
					return false
				}
			}
			end, err := decoder.Token()
			return err == nil && end == json.Delim('}')
		case '[':
			for decoder.More() {
				if !walk() {
					return false
				}
			}
			end, err := decoder.Token()
			return err == nil && end == json.Delim(']')
		default:
			return false
		}
	}
	if !walk() {
		return false
	}
	var extra any
	return decoder.Decode(&extra) == io.EOF
}

func (cfg Config) String() string {
	return fmt.Sprintf("%s %s/%s", cfg.SchemaVersion, cfg.Binding.SandboxNamespace, cfg.Binding.SandboxName)
}
