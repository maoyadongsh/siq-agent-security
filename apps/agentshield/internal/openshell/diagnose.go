package openshell

import (
	"os"
	"path/filepath"
	"strings"
	"unicode"
)

// Human-facing next steps. AgentShield never executes them.
const (
	MsgUnconfigured = "未在 PATH 上找到 openshell。请安装 NVIDIA OpenShell CLI 并保证 openshell 在 PATH 上，或成对设置 SIQ_AS_OPENSHELL_CLI_BIN 与 SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT。agentshield 不会代为启动网关。"
	MsgStartGateway = "已发现 OpenShell CLI，但网关不可达。请由人类运行 openshell gateway start，或 openshell gateway select <name> 后重试 probe。agentshield 不会执行 gateway start，也不会猜测端口。"
	MsgWrongProcess = "该 endpoint 连到的不是 OpenShell（常见：端口被 OpenClaw / Hermes 占用）。请把 SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT 指到真正的 OpenShell，或用 openshell gateway select 切换配置。禁止猜测端口；agentshield 不会改别人的网关，也不会 gateway start。"
	MsgEnvScript    = "已配置 SIQ_AS_OPENSHELL_ENV_SH，但 CLI 调用失败。请确认脚本存在、可 source，且网关已由人类启动。agentshield 不会执行 gateway start。"
	MsgReady        = "OpenShell 网关已验明，L3 可用。filesystem/process 仍非 effective。agentshield 不会执行 gateway start。"
)

// Diagnosis is the openshell doctor report. StartedGateway is always false.
type Diagnosis struct {
	CLIFound       bool          `json:"cli_found"`
	CLIPath        string        `json:"cli_path,omitempty"`
	Source         string        `json:"source"`
	EnvScript      string        `json:"env_script,omitempty"`
	ActiveGateway  string        `json:"active_gateway,omitempty"`
	ProbeOK        bool          `json:"probe_ok"`
	IdentityOK     bool          `json:"identity_ok"`
	Tier           string        `json:"tier"`
	Note           string        `json:"note"`
	HumanNext      string        `json:"human_next"`
	StartedGateway bool          `json:"started_gateway"`
	Capabilities   *Capabilities `json:"capabilities,omitempty"`
}

// UnconfiguredDiagnosis is returned when the server has no OpenShell client.
func UnconfiguredDiagnosis() Diagnosis {
	return Diagnosis{
		Source:         SourceNone,
		Tier:           "L0",
		Note:           "未配置 CLI/网关",
		HumanNext:      MsgUnconfigured,
		StartedGateway: false,
	}
}

// Diagnose resolves the CLI, probes once, and never starts a gateway.
func (c *Client) Diagnose() Diagnosis {
	d := Diagnosis{Tier: "L0", StartedGateway: false, ActiveGateway: readActiveGatewayName()}
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
		return d
	}
	d.ProbeOK = true
	d.IdentityOK = true
	d.Tier = "L3"
	d.Note = "网络段热更新 · " + caps.SchemaVersion
	d.HumanNext = MsgReady
	d.Capabilities = &caps
	return d
}

func nextStep(inv Invocation, err error) string {
	if err == nil {
		return MsgReady
	}
	msg := err.Error()
	if inv.Source == SourceNone || strings.Contains(msg, "未配置") {
		return MsgUnconfigured
	}
	if inv.Source == SourceInvalid && strings.Contains(msg, "必须同时") {
		return "SIQ_AS_OPENSHELL_CLI_BIN 与 SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT 必须成对设置。agentshield 不会代为启动网关。"
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
		raw, err := os.ReadFile(filepath.Join(dir, "openshell", "active_gateway"))
		if err != nil {
			continue
		}
		name := strings.TrimSpace(string(raw))
		if name == "" || len(name) > 64 {
			continue
		}
		for _, r := range name {
			if r > unicode.MaxASCII || !(unicode.IsLetter(r) || unicode.IsDigit(r) || r == '-' || r == '_' || r == '.') {
				return ""
			}
		}
		return name
	}
	return ""
}
