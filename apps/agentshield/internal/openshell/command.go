package openshell

import (
	"context"
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
}

// Runner executes CLI args (not the wrapper argv). Tests inject a fake.
type Runner func(args []string) (rc int, stdout, stderr string)

// Options construct a Client.
type Options struct {
	EnvScript    string
	Runner       Runner
	DockerRunner Runner
	Timeout      time.Duration
	ProbeTimeout time.Duration
	PollInterval time.Duration
	PollAttempts int
	MaxOutput    int
	LookupEnv    func(string) (string, bool)
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

// BuildCommand mirrors Python OpenShellCliBackend._build_command.
func (c *Client) BuildCommand(args []string) ([]string, error) {
	cliBin := c.env(envCLIBin)
	endpoint := c.env(envEndpoint)
	insecure := c.env(envInsecure) == "1"
	if (cliBin == "") != (endpoint == "") {
		return nil, fail("SIQ_AS_OPENSHELL_CLI_BIN 与 SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT 必须同时配置")
	}
	if cliBin != "" && endpoint != "" {
		if err := validateGatewayEndpoint(endpoint, insecure); err != nil {
			return nil, err
		}
		cmd := []string{cliBin, "--gateway-endpoint", endpoint}
		if insecure {
			cmd = append(cmd, "--gateway-insecure")
		}
		return append(cmd, args...), nil
	}
	envScript := c.EnvScript
	if envScript == "" {
		envScript = c.env(envEnvSH)
	}
	if envScript != "" {
		if !isAbsPath(envScript) {
			return nil, fail("SIQ_AS_OPENSHELL_ENV_SH 必须是绝对路径")
		}
		cmd := []string{"bash", "-c", `source "$1" && shift && exec openshell "$@"`, "openshell-env", envScript}
		return append(cmd, args...), nil
	}
	return nil, fail("OpenShell CLI 未配置：设置 CLI_BIN + GATEWAY_ENDPOINT，或显式设置 OPENSHELL_ENV_SH")
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
	if c.ProbeTimeout > 0 && ((len(args) >= 2 && args[0] == "gateway" && args[1] == "info") || (len(args) >= 1 && args[0] == "--version")) {
		timeout = c.ProbeTimeout
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, cmdLine[0], cmdLine[1:]...)
	cmd.Env = c.cleanEnv()
	var stdout, stderr strings.Builder
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	runErr := cmd.Run()
	so, se := stdout.String(), stderr.String()
	if len(so)+len(se) > c.MaxOutput {
		return 1, "", "openshell CLI 输出超限（fail-closed）"
	}
	if ctx.Err() == context.DeadlineExceeded {
		return 1, so, "openshell CLI 超时（fail-closed）"
	}
	if runErr != nil {
		if ee, ok := runErr.(*exec.ExitError); ok {
			return ee.ExitCode(), so, se
		}
		return 1, so, "无法执行 openshell CLI（fail-closed）: " + runErr.Error()
	}
	return 0, so, se
}

func runDockerPS(timeout time.Duration) (int, string, string) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, "docker", "ps", "--format", "{{.Names}}")
	var stdout, stderr strings.Builder
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	err := cmd.Run()
	if ctx.Err() == context.DeadlineExceeded {
		return 1, stdout.String(), "docker 目标发现超时（fail-closed）"
	}
	if err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			return ee.ExitCode(), stdout.String(), stderr.String()
		}
		return 1, stdout.String(), "无法执行 docker 目标发现（fail-closed）: " + err.Error()
	}
	return 0, stdout.String(), stderr.String()
}

func (c *Client) cleanEnv() []string {
	out := make([]string, 0, 16)
	src := os.Environ()
	for _, kv := range src {
		k, _, ok := strings.Cut(kv, "=")
		if !ok {
			continue
		}
		if safeEnvKeys[k] || strings.HasPrefix(k, "SIQ_AS_") || strings.HasPrefix(k, "OPENSHELL_") {
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
