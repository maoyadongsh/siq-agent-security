package openshell

import (
	"crypto/sha256"
	"fmt"
	"os"
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

// versionCacheTTL bounds how long a detected CLI version or gateway name may
// be reused. Caches are additionally bound to the invocation fingerprint: a
// changed endpoint/env-script invalidates them immediately.
const versionCacheTTL = 5 * time.Minute

// Client talks to OpenShell only through the CLI (never create_generation).
type Client struct {
	EnvScript    string
	Runner       Runner
	DockerRunner Runner
	// TaskRunner spawns one approved task command. It is a separate seam from
	// Runner so an injected fake replaces the process spawn only: the gates,
	// ordering and refusal logic in ExecTask stay shared with production.
	TaskRunner   TaskRunner
	Timeout      time.Duration
	ProbeTimeout time.Duration
	PollInterval time.Duration
	PollAttempts int
	MaxOutput    int
	lookup       func(string) (string, bool)
	lookPath     func(string) (string, error)

	mu                    sync.Mutex
	taskCancels           *TaskCanceller // lazily created; termination only, never authority
	dockerFallbackRetired bool           // conservative latch; never authorizes a capability
	detectedVersion       string
	detectedKey           string
	detectedAt            time.Time
	probedGateway         string
	probedKey             string
	probedAt              time.Time
	policy                *policyCoordinator
}

// New builds a Client. A nil Runner uses a filtered subprocess.
func New(opts Options) *Client {
	c := &Client{
		EnvScript:    opts.EnvScript,
		Runner:       opts.Runner,
		DockerRunner: opts.DockerRunner,
		TaskRunner:   opts.TaskRunner,
		Timeout:      opts.Timeout,
		ProbeTimeout: opts.ProbeTimeout,
		PollInterval: opts.PollInterval,
		PollAttempts: opts.PollAttempts,
		MaxOutput:    opts.MaxOutput,
		lookup:       opts.LookupEnv,
		lookPath:     opts.LookPath,
		policy:       processPolicyCoordinator,
	}
	if opts.policyCoordinator != nil {
		c.policy = opts.policyCoordinator
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
	if c.TaskRunner == nil {
		c.TaskRunner = c.taskSubprocess
	}
	return c
}

func (c *Client) cli(args ...string) (string, error) {
	rc, stdout, stderr := c.Runner(args)
	if len(stdout) > c.MaxOutput || len(stderr) > c.MaxOutput-len(stdout) {
		return "", fail(errOutputLimit)
	}
	cleanOut := ansiRe.ReplaceAllString(stdout, "")
	cleanErr := ansiRe.ReplaceAllString(stderr, "")
	if rc != 0 {
		if looksLikeForeignGateway(cleanOut+cleanErr) || cleanErr == errNotOpenShell {
			return "", fail(errNotOpenShell)
		}
		switch cleanErr {
		case errOutputLimit, errCommandTimeout, errPipeTimeout:
			return "", fail(cleanErr)
		default:
			return "", fail(errCommandFailed)
		}
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
	items := map[string]CapabilityItem{
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
	for key, item := range items {
		item.EvidenceLevel, item.Scope = "documented", "historical_adapter_observations_2026-08-13; not_current_target"
		items[key] = item
	}
	return items
}

// invocationFingerprint identifies the current CLI/endpoint configuration so
// cached observations never leak across endpoints. It is a one-way digest and
// never exposes the raw endpoint or script path.
func (c *Client) invocationFingerprint() string {
	inv, err := c.ResolveInvocation()
	h := sha256.New()
	if err != nil {
		return fmt.Sprintf("%x", sha256.Sum256([]byte("invalid:"+err.Error())))
	}
	switch inv.Source {
	case SourceEnvPair:
		fmt.Fprintf(h, "env_pair\x00%s\x00%s\x00%v", inv.CLIPath, inv.Endpoint, inv.Insecure)
		if inv.GatewayName != "" {
			fmt.Fprintf(h, "\x00gateway:%s", inv.GatewayName)
		}
		for _, key := range []string{"HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"} {
			fmt.Fprintf(h, "\x00%s=%s", key, c.env(key))
		}
		if st, err := os.Stat(inv.CLIPath); err == nil {
			fmt.Fprintf(h, "\x00%d\x00%d", st.Size(), st.ModTime().UnixNano())
		}
	case SourceEnvSH:
		return "" // scripts can select destinations through arbitrary external config
	case SourcePath:
		return "" // active gateway/config can change independently of CLI path
	default:
		return fmt.Sprintf("%x", sha256.Sum256([]byte("unconfigured")))
	}
	return fmt.Sprintf("%x", h.Sum(nil))
}

// InvocationFingerprint exposes the one-way digest of the current CLI/endpoint
// configuration so callers can invalidate cached probe observations.
func (c *Client) InvocationFingerprint() string { return c.invocationFingerprint() }

func (c *Client) cachedVersion(key string) string {
	if key == "" {
		return ""
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if key == "" || c.detectedKey != key || time.Since(c.detectedAt) > versionCacheTTL {
		return ""
	}
	return c.detectedVersion
}

func (c *Client) storeVersion(key, version string) {
	c.mu.Lock()
	c.detectedVersion, c.detectedKey, c.detectedAt = version, key, time.Now()
	c.mu.Unlock()
}

func (c *Client) cachedGateway(key string) string {
	if key == "" {
		return ""
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if key == "" || c.probedKey != key || time.Since(c.probedAt) > versionCacheTTL {
		return ""
	}
	return c.probedGateway
}

func (c *Client) storeGateway(key, name string) {
	c.mu.Lock()
	c.probedGateway, c.probedKey, c.probedAt = name, key, time.Now()
	c.mu.Unlock()
}

// Probe checks gateway reachability and reports capability facts with explicit
// evidence levels. `gateway info` only prints local CLI config and can succeed
// against a non-OpenShell process on the same port; `status` is the live
// handshake and must structurally match the OpenShell server-status shape.
// Either command looking like OpenClaw/Hermes is fail-closed. `cli_version`
// comes from CLI text only; `gateway_version` only from the live handshake
// output, and schema_version follows the gateway version alone. Capability
// booleans are never raised for a newer parsed version.
func (c *Client) Probe() (caps Capabilities, probeErr error) {
	defer func() {
		if probeErr != nil {
			c.mu.Lock()
			c.detectedVersion, c.detectedKey, c.probedGateway, c.probedKey = "", "", "", ""
			c.mu.Unlock()
		}
	}()
	before := c.invocationFingerprint()
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
	if !looksLikeOpenShellStatus(statusOut) {
		// rc=0 but empty/irrelevant output proves nothing about identity.
		return Capabilities{}, fail(errIdentityUnconfirmed)
	}
	key := c.invocationFingerprint()
	if key != before {
		return Capabilities{}, fail("openshell_configuration_changed")
	}
	name := parseGatewayName(statusOut)
	if name != "" {
		c.storeGateway(key, name)
	}
	cliVersion := c.detectVersion(infoOut)
	if key != c.invocationFingerprint() {
		return Capabilities{}, fail("openshell_configuration_changed")
	}
	if parts := strings.Split(cliVersion, "."); len(parts) == 3 {
		major, _ := atoi(parts[0])
		minor, _ := atoi(parts[1])
		patch, _ := atoi(parts[2])
		if major > 0 || minor > 0 || patch >= 104 {
			c.mu.Lock()
			c.dockerFallbackRetired = true
			c.mu.Unlock()
		}
	}
	gatewayVersion := parseGatewayVersion(statusOut)
	if gatewayVersion == "" {
		gatewayVersion = "unknown"
	}
	schema := "unknown-policy-v1"
	if gatewayVersion != "unknown" {
		schema = "v" + gatewayVersion + "-policy-v1"
	}
	return Capabilities{
		Backend:                     BackendName,
		SchemaVersion:               schema,
		DynamicNetworkUpdate:        true, // 2026-08-13 实测（历史依据，非本 endpoint 当前验证）
		StaticFilesystem:            true, // 实测：活沙箱 filesystem 变更被拒绝（历史依据）
		StaticProcess:               true, // 实测：process 段同属静态边界（历史依据）
		Landlock:                    true, // SIQ landlock patch / 上游内置（ADR-009）
		Interceptor:                 false,
		ProviderCredentialInjection: false,
		RevisionSupport:             true, // 实测：policy list / --rev 回读可用（历史依据）
		MaxFilesystemPaths:          1024, // 合同默认，未经网关实测上限
		Capabilities:                capabilityDocument(),

		EvidenceLevel:              EvidenceHandshake,
		HandshakeVerified:          true,
		HandshakeGateway:           name,
		CLIVersion:                 cliVersion,
		GatewayVersion:             gatewayVersion,
		EndpointFingerprint:        key,
		ObservedAt:                 time.Now().UTC().Format(time.RFC3339),
		MaxFilesystemPathsMeasured: false,
		ConfigurationCapabilities:  map[string]bool{"network.dynamic_update": true, "enforcement_mode.block": true},
	}, nil
}

func (c *Client) detectVersion(gatewayInfo string) string {
	key := c.invocationFingerprint()
	if v := c.cachedVersion(key); v != "" {
		return v
	}
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
	c.storeVersion(key, version)
	return version
}

func (c *Client) detectedVersionAtLeast(major, minor, patch int) bool {
	c.mu.Lock()
	v, key, at := c.detectedVersion, c.detectedKey, c.detectedAt
	c.mu.Unlock()
	if v == "" || v == "unknown" {
		return false
	}
	// O04: the cached version is only valid for the same invocation and while
	// fresh; a changed endpoint or an expired observation fails closed.
	if key == "" || key != c.invocationFingerprint() || time.Since(at) > versionCacheTTL {
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
		c.mu.Lock()
		retired := c.dockerFallbackRetired
		c.mu.Unlock()
		if retired || c.detectedVersionAtLeast(0, 0, 104) {
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
	if len(out) > c.MaxOutput || len(errOut) > c.MaxOutput-len(out) {
		return SandboxPage{}, fail(errOutputLimit)
	}
	if rc != 0 {
		return SandboxPage{}, fail(errCommandFailed)
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
