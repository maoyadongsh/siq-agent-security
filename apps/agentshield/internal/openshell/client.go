package openshell

import (
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
)

var (
	ansiRe             = regexp.MustCompile(`\x1b\[[0-9;]*[mK]`)
	versionSubmittedRe = regexp.MustCompile(`Policy version (\d+) submitted \(hash: ([0-9a-f]+)\)`)
	versionUnchangedRe = regexp.MustCompile(`Policy unchanged \(version (\d+), hash: ([0-9a-f]+)\)`)
	versionLineRe      = regexp.MustCompile(`(?im)^[^\n]*\bversion\b[^\n0-9]{0,16}v?(\d+\.\d+\.\d+)`)
	cliVersionRe       = regexp.MustCompile(`(?im)^\s*openshell(?:\s+version)?[\s:v-]{0,4}(\d+\.\d+\.\d+)`)
)

// Client talks to OpenShell only through the CLI (never create_generation).
type Client struct {
	EnvScript    string
	Runner       Runner
	DockerRunner Runner
	Timeout      time.Duration
	ProbeTimeout time.Duration
	PollInterval time.Duration
	PollAttempts int
	MaxOutput    int
	lookup       func(string) (string, bool)
	lookPath     func(string) (string, error)

	mu              sync.Mutex
	detectedVersion string
}

// New builds a Client. A nil Runner uses a filtered subprocess.
func New(opts Options) *Client {
	c := &Client{
		EnvScript:    opts.EnvScript,
		Runner:       opts.Runner,
		DockerRunner: opts.DockerRunner,
		Timeout:      opts.Timeout,
		ProbeTimeout: opts.ProbeTimeout,
		PollInterval: opts.PollInterval,
		PollAttempts: opts.PollAttempts,
		MaxOutput:    opts.MaxOutput,
		lookup:       opts.LookupEnv,
		lookPath:     opts.LookPath,
	}
	if c.Timeout <= 0 {
		c.Timeout = 30 * time.Second
	}
	if c.PollAttempts <= 0 {
		c.PollAttempts = 10
	}
	if opts.PollInterval < 0 {
		c.PollInterval = 0
	} else if opts.PollInterval == 0 {
		c.PollInterval = time.Second
	}
	if c.MaxOutput <= 0 {
		c.MaxOutput = 2 << 20
	}
	if c.Runner == nil {
		c.Runner = c.subprocess
	}
	return c
}

func (c *Client) cli(args ...string) (string, error) {
	rc, stdout, stderr := c.Runner(args)
	cleanOut := ansiRe.ReplaceAllString(stdout, "")
	cleanErr := ansiRe.ReplaceAllString(stderr, "")
	if rc != 0 {
		msg := strings.TrimSpace(cleanErr)
		if msg == "" {
			msg = strings.TrimSpace(cleanOut)
		}
		if len(msg) > 300 {
			msg = msg[:300]
		}
		return "", failf("openshell %s 失败(rc=%d): %s", strings.Join(args, " "), rc, msg)
	}
	return cleanOut + "\n" + cleanErr, nil
}

func parseVersion(text string) string {
	if m := versionLineRe.FindStringSubmatch(text); m != nil {
		return m[1]
	}
	if m := cliVersionRe.FindStringSubmatch(text); m != nil {
		return m[1]
	}
	return ""
}

func capabilityDocument() map[string]CapabilityItem {
	return map[string]CapabilityItem{
		"sandbox_lifecycle": {Status: "unsupported", Semantics: "none",
			Basis: "实测：SandboxResponse 解码缺陷，create_generation 经 CLI 拒绝（v0.0.104 修复未在本路径实测）"},
		"filesystem": {Status: "supported", Semantics: "enforce",
			Basis: "实测：静态边界，创建时锁定，网关强制"},
		"process": {Status: "supported", Semantics: "enforce",
			Basis: "实测：process 段同属静态边界，创建时锁定"},
		"network_l34": {Status: "supported", Semantics: "enforce",
			Basis: "2026-08-13 实测：host:port 网络段热更新成功"},
		"network_l7": {Status: "unsupported", Semantics: "none",
			Basis: "实测：端点模型仅 host:port，path 级规则编译拒绝"},
		"tools_mcp": {Status: "unknown", Semantics: "none",
			Basis: "interceptor/工具治理未经实测（不猜测）"},
		"model_routing": {Status: "unsupported", Semantics: "none",
			Basis: "provider 凭据注入未经实测（保守拒绝）"},
		"secrets": {Status: "unsupported", Semantics: "none",
			Basis: "凭据注入能力未经实测（保守拒绝，§15.2 由 Provider 侧承担）"},
		"resources": {Status: "unknown", Semantics: "none",
			Basis: "资源配额语义未经实测"},
		"audit_events": {Status: "unknown", Semantics: "none",
			Basis: "无已实测事件流；stream_events 仅 policy list 回读（非行为事件）"},
		"enforcement_mode.block": {Status: "supported", Semantics: "enforce",
			Basis: "网关策略默认拦截语义（部署路径实测）"},
		"enforcement_mode.warn": {Status: "unsupported", Semantics: "none",
			Basis: "CLI 路径无 warn 执行语义的实测依据"},
		"enforcement_mode.audit_only": {Status: "unsupported", Semantics: "none",
			Basis: "CLI 路径无 audit_only 执行语义的实测依据"},
	}
}

// Probe checks gateway reachability and reports already-measured capabilities.
// `gateway info` only prints local CLI config and can succeed against a
// non-OpenShell process on the same port; `status` is the live handshake.
// Either command looking like OpenClaw/Hermes is fail-closed. An unparseable
// version becomes "unknown" and never invents a version string. Capability
// booleans are not raised for a newer parsed version.
func (c *Client) Probe() (Capabilities, error) {
	infoOut, err := c.cli("gateway", "info")
	if err != nil {
		if looksLikeForeignGateway(err.Error()) {
			return Capabilities{}, fail(errNotOpenShell)
		}
		return Capabilities{}, err
	}
	if !looksLikeOpenShellGateway(infoOut) {
		return Capabilities{}, fail(errNotOpenShell)
	}
	statusOut, err := c.cli("status")
	if err != nil {
		if looksLikeForeignGateway(err.Error()) {
			return Capabilities{}, fail(errNotOpenShell)
		}
		return Capabilities{}, err
	}
	if looksLikeForeignGateway(statusOut) {
		return Capabilities{}, fail(errNotOpenShell)
	}
	version := c.detectVersion(infoOut)
	schema := "unknown-policy-v1"
	if version != "unknown" {
		schema = "v" + version + "-policy-v1"
	}
	return Capabilities{
		Backend:                     BackendName,
		SchemaVersion:               schema,
		DynamicNetworkUpdate:        true,  // 2026-08-13 实测：网络段热更新成功（静态段锁定）
		StaticFilesystem:            true,  // 实测：活沙箱 filesystem 变更被拒绝
		StaticProcess:               true,  // 实测：process 段同属静态边界
		Landlock:                    true,  // SIQ landlock patch / 上游内置（ADR-009）
		Interceptor:                 false, // 未经实测
		ProviderCredentialInjection: false, // 未经实测
		RevisionSupport:             true,  // 实测：policy list / --rev 回读可用
		MaxFilesystemPaths:          1024,  // 合同默认，未经网关实测上限
		Capabilities:                capabilityDocument(),
	}, nil
}

func (c *Client) detectVersion(gatewayInfo string) string {
	version := parseVersion(gatewayInfo)
	if version == "" {
		out, err := c.cli("--version")
		if err == nil {
			version = parseVersion(out)
		}
	}
	if version == "" {
		version = "unknown"
	}
	c.mu.Lock()
	c.detectedVersion = version
	c.mu.Unlock()
	return version
}

func (c *Client) detectedVersionAtLeast(major, minor, patch int) bool {
	c.mu.Lock()
	v := c.detectedVersion
	c.mu.Unlock()
	if v == "" || v == "unknown" {
		return false
	}
	parts := strings.Split(v, ".")
	if len(parts) != 3 {
		return false
	}
	var n [3]int
	for i := 0; i < 3; i++ {
		var err error
		n[i], err = atoi(parts[i])
		if err != nil {
			return false
		}
	}
	if n[0] != major {
		return n[0] > major
	}
	if n[1] != minor {
		return n[1] > minor
	}
	return n[2] >= patch
}

func atoi(s string) (int, error) {
	n := 0
	if s == "" {
		return 0, fail("empty")
	}
	for _, r := range s {
		if r < '0' || r > '9' {
			return 0, fail("not a number")
		}
		n = n*10 + int(r-'0')
	}
	return n, nil
}

// ListTargets lists sandboxes. On the SandboxResponse decode bug (versions
// below 0.0.104, or unknown) it may fall back to docker ps; v0.0.104+ raises.
func (c *Client) ListTargets() (SandboxPage, error) {
	out, err := c.cli("sandbox", "list")
	if err != nil {
		if c.detectedVersionAtLeast(0, 0, 104) {
			return SandboxPage{}, err
		}
		return c.listTargetsDockerFallback()
	}
	var targets []map[string]string
	lines := strings.Split(out, "\n")
	for i, line := range lines {
		if i == 0 {
			continue
		}
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		name := strings.Fields(line)[0]
		if name != "" && name != "No" {
			targets = append(targets, map[string]string{"id": name})
		}
	}
	return SandboxPage{Targets: targets}, nil
}

func (c *Client) listTargetsDockerFallback() (SandboxPage, error) {
	runner := c.DockerRunner
	var rc int
	var out, errOut string
	if runner != nil {
		rc, out, errOut = runner([]string{"docker", "ps", "--format", "{{.Names}}"})
	} else {
		rc, out, errOut = runDockerPS(10 * time.Second)
	}
	if rc != 0 {
		msg := strings.TrimSpace(errOut)
		if len(msg) > 200 {
			msg = msg[:200]
		}
		return SandboxPage{}, failf("docker 目标发现失败(rc=%d): %s", rc, msg)
	}
	names := map[string]struct{}{}
	const prefix, uuidLen = "openshell-", 36
	for _, line := range strings.Split(out, "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, prefix) && len(line) > len(prefix)+uuidLen {
			names[line[len(prefix):len(line)-uuidLen-1]] = struct{}{}
		}
	}
	ids := make([]string, 0, len(names))
	for n := range names {
		ids = append(ids, n)
	}
	sort.Strings(ids)
	targets := make([]map[string]string, 0, len(ids))
	for _, id := range ids {
		targets = append(targets, map[string]string{"id": id})
	}
	return SandboxPage{Targets: targets}, nil
}

// CreateGeneration is refused: the CLI path must not call sandbox create.
func (c *Client) CreateGeneration(target string) error {
	_ = target
	return fail("sandbox create 经 CLI 受网关 SandboxResponse 解码缺陷影响；请通过受控生命周期创建，或升级到已修复的 OpenShell 版本后启用")
}
