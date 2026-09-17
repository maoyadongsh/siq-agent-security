package openshell

import (
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/statefs"
	"strings"
	"time"
	"unicode"
)

// Human-facing next steps. AgentShield never executes them.
const (
	MsgUnconfigured = "未在 PATH 上找到 openshell。请安装 NVIDIA OpenShell CLI 并保证 openshell 在 PATH 上，或成对设置 SIQ_AS_OPENSHELL_CLI_BIN 与 SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT。agentshield 不会代为启动网关。"
	MsgStartGateway = "已发现 OpenShell CLI，但网关不可达。请由人类运行 openshell gateway start，或 openshell gateway select <name> 后重试 probe。agentshield 不会执行 gateway start，也不会猜测端口。"
	MsgWrongProcess = "该 endpoint 连到的不是 OpenShell（常见：端口被 OpenClaw / Hermes 占用）。请把 SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT 指到真正的 OpenShell，或用 openshell gateway select 切换配置。禁止猜测端口；agentshield 不会改别人的网关，也不会 gateway start。"
	MsgEnvScript    = "已配置 SIQ_AS_OPENSHELL_ENV_SH，但 CLI 调用失败。请确认脚本存在、可 source，且网关已由人类启动。agentshield 不会执行 gateway start。"
	MsgIdentity     = "endpoint 有响应，但输出无法确认 OpenShell 身份。请核对 SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT 是否指向真正的 OpenShell 网关，或用 openshell gateway select 切换配置。禁止猜测端口。"
	MsgReady        = "已收到符合 OpenShell status 协议的响应，尚未验证执行限制。可使用 doctor --target 对指定目标执行只读策略检查。协议匹配不代表加密身份认证或隔离验证。"
)

// Diagnosis is the openshell doctor report. StartedGateway is always false.
// State uses the O04 six-state vocabulary (see
// packages/contracts/openshell-policy-safety.v2.md).
type Diagnosis struct {
	CLIFound       bool          `json:"cli_found"`
	CLIPath        string        `json:"cli_path,omitempty"`
	Source         string        `json:"source"`
	EnvScript      string        `json:"env_script,omitempty"`
	ActiveGateway  string        `json:"active_gateway,omitempty"`
	ProbeOK        bool          `json:"probe_ok"`
	IdentityOK     bool          `json:"identity_ok"`
	Tier           string        `json:"tier"`
	State          string        `json:"state"`
	Note           string        `json:"note"`
	HumanNext      string        `json:"human_next"`
	StartedGateway bool          `json:"started_gateway"`
	Capabilities   *Capabilities `json:"capabilities,omitempty"`
	ObservedAt     string        `json:"observed_at,omitempty"`
	ExpiresAt      string        `json:"expires_at,omitempty"`
	Target         string        `json:"target,omitempty"`
	Revision       string        `json:"revision,omitempty"`
	PolicyDigest   string        `json:"policy_digest,omitempty"`
}

// UnconfiguredDiagnosis is returned when the server has no OpenShell client.
func UnconfiguredDiagnosis() Diagnosis {
	return Diagnosis{
		Source:         SourceNone,
		Tier:           "L0",
		State:          StateUnconfigured,
		Note:           "未配置 CLI/网关",
		HumanNext:      MsgUnconfigured,
		StartedGateway: false,
	}
}

// Diagnose resolves the CLI, probes once, and never starts a gateway.
func (c *Client) Diagnose() Diagnosis {
	d := Diagnosis{Tier: "L0", State: StateUnconfigured, StartedGateway: false, ActiveGateway: readActiveGatewayName()}
	inv, err := c.ResolveInvocation()
	if err != nil {
		d.Source = inv.Source
		if d.Source == "" {
			d.Source = SourceNone
		}
		d.Note = err.Error()
		d.HumanNext = nextStep(inv, err)
		return d
	}
	d.Source = inv.Source
	d.CLIPath = inv.CLIPath
	d.EnvScript = inv.EnvScript
	d.CLIFound = inv.Source != SourceNone && inv.Source != SourceInvalid
	if inv.Source == SourceEnvSH {
		// Host ~/.config/openshell is a different product (often OpenClaw).
		d.ActiveGateway = ""
	}
	if inv.Source == SourceNone {
		d.Note = "OpenShell CLI 未找到"
		d.HumanNext = MsgUnconfigured
		return d
	}
	caps, err := c.Probe()
	if err != nil {
		d.Note = err.Error()
		d.HumanNext = nextStep(inv, err)
		d.IdentityOK = false
		d.ProbeOK = false
		d.Tier = "L0"
		d.State = probeErrorState(err)
		return d
	}
	if gw := caps.HandshakeGateway; gw != "" {
		d.ActiveGateway = gw
	}
	d.ProbeOK = true
	d.IdentityOK = true
	d.Tier = "L3"
	d.State = StateHandshake
	d.Note = "status 协议响应匹配 · " + caps.SchemaVersion + " · 策略读回与执行限制未经本诊断验证"
	d.HumanNext = MsgReady
	d.Capabilities = &caps
	d.ObservedAt = caps.ObservedAt
	d.ExpiresAt = time.Now().Add(15 * time.Second).UTC().Format(time.RFC3339)
	return d
}

// DiagnoseTarget is an explicit, read-only target observation. No state is
// written and no behavioral claim is possible through this CLI path.
func (c *Client) DiagnoseTarget(target string) Diagnosis {
	d := c.Diagnose()
	if !d.ProbeOK {
		return d
	}
	if target == "" || sanitizeGatewayName(target) != target {
		d.State, d.ProbeOK, d.Note = StateIdentityUnconfirmed, false, "目标名称无效"
		return d
	}
	before := c.InvocationFingerprint()
	if before == "" || d.Capabilities == nil || before != d.Capabilities.EndpointFingerprint {
		d.State, d.ProbeOK = StateIdentityUnconfirmed, false
		d.Note, d.HumanNext = "当前调用无法稳定绑定目标", "请成对配置 CLI 路径和 gateway endpoint 后重试目标只读检查。"
		return d
	}
	snapshot, err := c.ReadEffective(target)
	if err != nil || before != c.InvocationFingerprint() {
		d.State, d.ProbeOK = StateEvidenceExpired, false
		d.Note, d.HumanNext = "目标策略证据不可用", "请核对目标和当前配置，重新执行只读检查。"
		return d
	}
	d.State, d.Target = StatePolicyReadable, target
	d.Revision, d.PolicyDigest = snapshot.Revision, snapshot.PolicyDigest
	d.ObservedAt = time.Now().UTC().Format(time.RFC3339)
	d.ExpiresAt = time.Now().Add(15 * time.Second).UTC().Format(time.RFC3339)
	d.Note = "指定目标策略已读回；尚未验证执行限制"
	d.HumanNext = "请按该目标的权限范围完成独立行为验收。"
	return d
}

// probeErrorState maps a probe failure to the O04 diagnostic states.
func probeErrorState(err error) string {
	if err == nil {
		return StateHandshake
	}
	msg := err.Error()
	switch {
	case msg == errCLIUnconfigured:
		return StateUnconfigured
	case msg == errNotOpenShell || msg == errIdentityUnconfirmed:
		return StateIdentityUnconfirmed
	default:
		return StateUnreachable
	}
}

func nextStep(inv Invocation, err error) string {
	if err == nil {
		return MsgReady
	}
	msg := err.Error()
	if inv.Source == SourceNone || msg == errCLIUnconfigured {
		return MsgUnconfigured
	}
	if inv.Source == SourceInvalid && strings.Contains(msg, "必须同时") {
		return "SIQ_AS_OPENSHELL_CLI_BIN 与 SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT 必须成对设置。agentshield 不会代为启动网关。"
	}
	if msg == errIdentityUnconfirmed {
		return MsgIdentity
	}
	if strings.Contains(msg, "不是 OpenShell") || looksLikeForeignGateway(msg) {
		return MsgWrongProcess
	}
	if inv.Source == SourceEnvSH {
		return MsgEnvScript
	}
	return MsgStartGateway
}

func readActiveGatewayName() string {
	var dirs []string
	if xdg := strings.TrimSpace(os.Getenv("XDG_CONFIG_HOME")); xdg != "" {
		dirs = append(dirs, xdg)
	}
	if home, err := os.UserHomeDir(); err == nil && home != "" {
		dirs = append(dirs, filepath.Join(home, ".config"))
	}
	for _, dir := range dirs {
		raw, err := statefs.ReadFile(filepath.Join(dir, "openshell", "active_gateway"))
		if err != nil {
			continue
		}
		name := strings.TrimSpace(string(raw))
		if n := sanitizeGatewayName(name); n != "" {
			return n
		}
	}
	return ""
}

func parseGatewayName(text string) string {
	for _, line := range strings.Split(text, "\n") {
		line = strings.TrimSpace(line)
		if !strings.HasPrefix(line, "Gateway:") {
			continue
		}
		return sanitizeGatewayName(strings.TrimSpace(strings.TrimPrefix(line, "Gateway:")))
	}
	return ""
}

func sanitizeGatewayName(name string) string {
	name = strings.TrimSpace(name)
	if name == "" || len(name) > 64 {
		return ""
	}
	for _, r := range name {
		if r > unicode.MaxASCII || !(unicode.IsLetter(r) || unicode.IsDigit(r) || r == '-' || r == '_' || r == '.') {
			return ""
		}
	}
	return name
}
