package openshell

import (
	"net"
	"net/url"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"
	"unicode"
)

const (
	envCLIBin   = "SIQ_AS_OPENSHELL_CLI_BIN"
	envEndpoint = "SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT"
	envInsecure = "SIQ_AS_OPENSHELL_GATEWAY_INSECURE"
	envEnvSH    = "SIQ_AS_OPENSHELL_ENV_SH"
)

var safeEnvKeys = map[string]bool{
	"PATH": true, "HOME": true, "LANG": true, "LC_ALL": true, "TMPDIR": true, "USER": true, "TERM": true,
	"XDG_CONFIG_HOME": true, "XDG_STATE_HOME": true, "XDG_DATA_HOME": true,
	"XDG_CACHE_HOME": true, "XDG_RUNTIME_DIR": true,
	"USERPROFILE": true, "APPDATA": true, "LOCALAPPDATA": true,
	"SYSTEMROOT": true, "SystemRoot": true, "WINDIR": true, "TEMP": true, "TMP": true,
}

// Runner executes CLI args (not the wrapper argv). Tests inject a fake.
type Runner func(args []string) (rc int, stdout, stderr string)

// Options construct a Client.
type Options struct {
	EnvScript         string
	Runner            Runner
	DockerRunner      Runner
	TaskRunner        TaskRunner
	Timeout           time.Duration
	ProbeTimeout      time.Duration
	PollInterval      time.Duration
	PollAttempts      int
	MaxOutput         int
	LookupEnv         func(string) (string, bool)
	LookPath          func(string) (string, error)
	policyCoordinator *policyCoordinator
}

func (c *Client) env(key string) string {
	if c.lookup != nil {
		if v, ok := c.lookup(key); ok {
			return v
		}
		return ""
	}
	return os.Getenv(key)
}

const (
	SourceNone    = "none"
	SourceInvalid = "invalid"
	SourceEnvPair = "env_pair"
	SourceEnvSH   = "env_sh"
	SourcePath    = "path"
)

const errCLIUnconfigured = "OpenShell CLI 未配置：PATH 上没有 openshell。成对设置 SIQ_AS_OPENSHELL_CLI_BIN 与 SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT，或设置 SIQ_AS_OPENSHELL_ENV_SH。运行 agentshield openshell doctor。agentshield 不会代为启动网关"

// Invocation is how AgentShield will invoke the OpenShell CLI.
type Invocation struct {
	Source    string
	CLIPath   string
	Endpoint  string
	EnvScript string
	Insecure  bool
}

// ResolveInvocation picks explicit env, then ENV_SH, then PATH. It never
// starts a gateway and never guesses a port.
func (c *Client) ResolveInvocation() (Invocation, error) {
	cliBin := c.env(envCLIBin)
	endpoint := c.env(envEndpoint)
	insecure := c.env(envInsecure) == "1"
	if (cliBin == "") != (endpoint == "") {
		return Invocation{Source: SourceInvalid}, fail("SIQ_AS_OPENSHELL_CLI_BIN 与 SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT 必须同时配置")
	}
	if cliBin != "" && endpoint != "" {
		if err := validateGatewayEndpoint(endpoint, insecure); err != nil {
			return Invocation{Source: SourceInvalid}, err
		}
		return Invocation{Source: SourceEnvPair, CLIPath: cliBin, Endpoint: endpoint, Insecure: insecure}, nil
	}
	envScript := c.EnvScript
	if envScript == "" {
		envScript = c.env(envEnvSH)
	}
	if envScript != "" {
		if !isAbsPath(envScript) {
			return Invocation{Source: SourceInvalid}, fail("SIQ_AS_OPENSHELL_ENV_SH 必须是绝对路径")
		}
		return Invocation{Source: SourceEnvSH, EnvScript: envScript}, nil
	}
	if bin := c.findOnPATH(); bin != "" {
		return Invocation{Source: SourcePath, CLIPath: bin}, nil
	}
	return Invocation{Source: SourceNone}, fail(errCLIUnconfigured)
}

func (c *Client) findOnPATH() string {
	fn := c.lookPath
	if fn == nil {
		fn = exec.LookPath
	}
	bin, err := fn("openshell")
	if err != nil || bin == "" || !isAbsPath(bin) {
		return ""
	}
	return bin
}

// BuildCommand mirrors Python OpenShellCliBackend._build_command, then falls
// back to PATH discovery (AgentShield-only).
func (c *Client) BuildCommand(args []string) ([]string, error) {
	inv, err := c.ResolveInvocation()
	if err != nil {
		return nil, err
	}
	switch inv.Source {
	case SourceEnvPair:
		cmd := []string{inv.CLIPath, "--gateway-endpoint", inv.Endpoint}
		if inv.Insecure {
			cmd = append(cmd, "--gateway-insecure")
		}
		return append(cmd, args...), nil
	case SourceEnvSH:
		// After source, prefer SIQ_OPENSHELL_BIN (research-engine env.sh) so
		// we do not fall through to a global PATH openshell that talks to
		// another product's gateway. Unset → PATH openshell.
		cmd := []string{"bash", "-c", `source "$1" && shift && exec "${SIQ_OPENSHELL_BIN:-openshell}" "$@"`, "openshell-env", inv.EnvScript}
		return append(cmd, args...), nil
	case SourcePath:
		return append([]string{inv.CLIPath}, args...), nil
	default:
		return nil, fail(errCLIUnconfigured)
	}
}

func isAbsPath(p string) bool {
	if p == "" {
		return false
	}
	if p[0] == '/' {
		return true
	}
	// Windows drive path, e.g. C:\...
	if len(p) >= 3 && unicode.IsLetter(rune(p[0])) && p[1] == ':' && (p[2] == '\\' || p[2] == '/') {
		return true
	}
	return false
}

func validateGatewayEndpoint(raw string, insecure bool) error {
	u, err := url.Parse(raw)
	if err != nil {
		return fail("OpenShell gateway endpoint 无效")
	}
	if u.Scheme != "http" && u.Scheme != "https" {
		return fail("OpenShell gateway endpoint 无效")
	}
	if u.Hostname() == "" || u.User != nil {
		return fail("OpenShell gateway endpoint 无效")
	}
	if u.Path != "" && u.Path != "/" {
		return fail("OpenShell gateway endpoint 无效")
	}
	if u.RawQuery != "" || u.Fragment != "" || u.Opaque != "" {
		return fail("OpenShell gateway endpoint 无效")
	}
	if strings.Contains(u.Host, ":") {
		port := u.Port()
		n, convErr := strconv.Atoi(port)
		if convErr != nil || n < 1 || n > 65535 {
			return fail("OpenShell gateway endpoint 端口无效")
		}
	}
	loopback := isLoopbackHost(u.Hostname())
	if u.Scheme != "https" && !loopback {
		return fail("非回环 OpenShell gateway 必须使用 HTTPS")
	}
	if insecure && !loopback {
		return fail("--gateway-insecure 仅允许回环开发网关")
	}
	return nil
}

func isLoopbackHost(host string) bool {
	if host == "" {
		return false
	}
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func (c *Client) subprocess(args []string) (int, string, string) {
	cmdLine, err := c.BuildCommand(args)
	if err != nil {
		return 1, "", err.Error()
	}
	timeout := c.Timeout
	if c.ProbeTimeout > 0 && ((len(args) >= 2 && args[0] == "gateway" && args[1] == "info") || (len(args) >= 1 && args[0] == "--version") || (len(args) == 1 && args[0] == "status")) {
		timeout = c.ProbeTimeout
	}
	return runBoundedCommand(cmdLine, c.cleanEnv(), timeout, c.MaxOutput)
}

func runDockerPS(timeout time.Duration) (int, string, string) {
	return runBoundedCommand([]string{"docker", "ps", "--format", "{{.Names}}"}, (&Client{}).cleanEnv(), timeout, 2<<20)
}

func (c *Client) cleanEnv() []string {
	out := make([]string, 0, 16)
	src := os.Environ()
	for _, kv := range src {
		k, _, ok := strings.Cut(kv, "=")
		if !ok {
			continue
		}
		if safeEnvKeys[k] {
			out = append(out, kv)
		}
	}
	hasPath := false
	for _, kv := range out {
		if strings.HasPrefix(kv, "PATH=") {
			hasPath = true
			break
		}
	}
	if !hasPath {
		out = append(out, "PATH=/usr/bin:/bin")
	}
	return out
}
